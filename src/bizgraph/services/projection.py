"""ProjectionService: selection criteria -> dataset projection (FR6, ARCHITECTURE.md 2.6, 3.7).

A `CriteriaSpec` (JSON) is a boolean tree (`all` / `any` / `not`) of `Predicate`s over fact
types, each with an optional time window relative to the spec's `as_of` date. The
`QueryPlanner` sends each predicate to the engine that holds the fact:

* graph predicates (SPARQL on Fuseki): `notice`, `ban`, `licence`. The fact lives in a
  source graph and points at a record; the party comes from the role edge in ONE links
  graph (`urn:graph:links:{matcher_version}`), and the `bg:Link` gives match type and
  confidence. Validity windows compile to `bg:validFrom` / `bg:validTo` filters.
* tabular predicates (DuckDB SQL): `licence_event` (only exists in DuckDB: it is derived
  by diffing register snapshots) and `party` attribute filters on `party_canonical`.

Results join on the party IRI (the canonical key rendered the way the graph renders it).
`all` evaluates its children cheapest-first and pushes the surviving keys into later SQL
predicates; `any` unions; `not` subtracts (only inside `all`). The output is one row per
party with, for every predicate, the best evidence row (most recent) and provenance
columns: source graph or table, record, link id, match type, confidence.

Dates on `licence_event` are honest bounds: `event_date` is the first snapshot that shows
the licence gone (UPPER bound), `observed_after` the last snapshot that still showed it
(LOWER bound, exclusive). "Cancelled in the last 3 months" tests `event_date` by default;
`"certain": true` also requires `observed_after` inside the window. Both columns are
always projected.
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from bizgraph.rdf.vocab import IriFactory
from bizgraph.services.endpoint import (
    GRAPH_CANONICAL,
    LINKS_GRAPH_PREFIX,
    PREFIXES,
    SparqlEndpoint,
    date_lit,
    iri_term,
    local,
    pick_links_graph,
    str_lit,
    values_clause,
)

GRAPH_FACTS = ("notice", "ban", "licence")
SQL_FACTS = ("licence_event", "party")
PARTY_FIELDS = ("state", "postcode", "entity_type", "status", "party_type", "anzsic", "name_norm",
                "abn_status", "asic_status", "asic_type", "asic_class")
SQL_OPS = {"=": "=", "!=": "<>", "in": "IN", "like": "LIKE", "is_null": "IS NULL", "not_null": "IS NOT NULL"}
_DURATION = re.compile(r"^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?$")
_SCHEME_TYPES = {"scheme", "managed_investment_scheme", "mis"}


# --------------------------------------------------------------------------- spec


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    import calendar

    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


@dataclass
class TimeWindow:
    """`last` is an ISO-8601 duration back from as_of (P3M, P90D, P1Y); or explicit
    `start` / `end` dates. Closed interval."""

    last: str | None = None
    start: date | None = None
    end: date | None = None

    def bounds(self, as_of: date) -> tuple[date, date]:
        if self.last:
            m = _DURATION.match(self.last.upper())
            if not m:
                raise ValueError(f"bad duration {self.last!r} (use e.g. P3M, P90D, P1Y)")
            y, mo, w, d = (int(x or 0) for x in m.groups())
            start = _add_months(as_of, -(12 * y + mo)) - timedelta(weeks=w, days=d)
            return start, self.end or as_of
        return self.start or date.min, self.end or as_of

    @classmethod
    def from_obj(cls, obj: Any) -> TimeWindow | None:
        if obj is None:
            return None
        if isinstance(obj, str):
            return cls(last=obj)
        return cls(obj.get("last"), _date(obj.get("start")), _date(obj.get("end")))


def _date(v: Any) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


@dataclass
class Predicate:
    fact: str
    id: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    window: TimeWindow | None = None
    min_confidence: float | None = None

    @property
    def engine(self) -> str:
        if self.fact in GRAPH_FACTS:
            return "sparql"
        if self.fact in SQL_FACTS:
            return "sql"
        raise ValueError(f"unknown fact type {self.fact!r}; known: {GRAPH_FACTS + SQL_FACTS}")

    @classmethod
    def from_obj(cls, obj: dict[str, Any], n: int) -> Predicate:
        obj = dict(obj)
        fact = obj.pop("fact")
        pid = obj.pop("id", None) or f"p{n}"
        window = TimeWindow.from_obj(obj.pop("window", None))
        minc = obj.pop("min_confidence", None)
        return cls(fact, pid, obj, window, float(minc) if minc is not None else None)

    def to_obj(self) -> dict[str, Any]:
        d: dict[str, Any] = {"fact": self.fact, "id": self.id, **self.params}
        if self.window:
            d["window"] = {k: (v.isoformat() if isinstance(v, date) else v)
                           for k, v in asdict(self.window).items() if v is not None}
        if self.min_confidence is not None:
            d["min_confidence"] = self.min_confidence
        return d


@dataclass
class BoolNode:
    op: str  # all | any | not | pred
    children: list[BoolNode] = field(default_factory=list)
    pred: Predicate | None = None

    def predicates(self) -> list[Predicate]:
        if self.pred:
            return [self.pred]
        return [p for c in self.children for p in c.predicates()]

    def to_obj(self) -> Any:
        if self.pred:
            return self.pred.to_obj()
        if self.op == "not":
            return {"not": self.children[0].to_obj()}
        return {self.op: [c.to_obj() for c in self.children]}


@dataclass
class CriteriaSpec:
    match: BoolNode
    name: str = "projection"
    description: str = ""
    as_of: date = field(default_factory=date.today)
    columns: list[str] | None = None
    min_confidence: float = 0.0
    matcher_version: str | None = None
    limit: int | None = None

    @property
    def predicates(self) -> list[Predicate]:
        return self.match.predicates()

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CriteriaSpec:
        counter = [0]

        def build(obj: Any) -> BoolNode:
            if isinstance(obj, list):
                return BoolNode("all", [build(o) for o in obj])
            if "all" in obj or "any" in obj:
                op = "all" if "all" in obj else "any"
                return BoolNode(op, [build(o) for o in obj[op]])
            if "not" in obj:
                return BoolNode("not", [build(obj["not"])])
            counter[0] += 1
            return BoolNode("pred", pred=Predicate.from_obj(obj, counter[0]))

        match = build(d["match"])
        ids = [p.id for p in match.predicates()]
        if len(ids) != len(set(ids)):
            raise ValueError(f"predicate ids must be unique: {ids}")
        _check_not(match)
        return cls(match, d.get("name", "projection"), d.get("description", ""),
                   _date(d.get("as_of")) or date.today(), d.get("columns"),
                   float(d.get("min_confidence", 0.0)), d.get("matcher_version"), d.get("limit"))

    @classmethod
    def from_json(cls, text_or_path: str | Path) -> CriteriaSpec:
        p = Path(str(text_or_path))
        text = p.read_text(encoding="utf-8") if p.suffix.lower() == ".json" and p.exists() else str(text_or_path)
        return cls.from_dict(json.loads(text))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "as_of": self.as_of.isoformat(),
                "match": self.match.to_obj(), "columns": self.columns, "min_confidence": self.min_confidence,
                "matcher_version": self.matcher_version, "limit": self.limit}


def _check_not(node: BoolNode, parent: str | None = None) -> None:
    if node.op == "not" and parent != "all":
        raise ValueError("'not' is only allowed directly inside 'all' (it subtracts from its siblings)")
    for c in node.children:
        _check_not(c, node.op)


# The brief's example, as a named spec. Notice at any time (set a window on p1 to restrict);
# AFSL gone from the register within the last 3 months by its upper-bound date.
NAMED_SPECS: dict[str, dict[str, Any]] = {
    "accc_notice_and_afsl_cancelled_3m": {
        "name": "accc_notice_and_afsl_cancelled_3m",
        "description": "Companies with an ACCC infringement notice (any time) AND an AFSL that "
                       "disappeared from the register (CANCELLED_OR_LAPSED) in the last 3 months. "
                       "event_date is an upper bound, observed_after a lower bound; both are projected.",
        "match": {"all": [
            {"id": "accc_notice", "fact": "notice", "regulator": "ACCC"},
            {"id": "afsl_cancelled", "fact": "licence_event", "event_type": "CANCELLED_OR_LAPSED",
             "licence_kind": "AFSL", "window": {"last": "P3M"}},
        ]},
        "min_confidence": 0.0,
    },
    "accc_notice_in_window_and_afsl_cancelled_3m": {
        "name": "accc_notice_in_window_and_afsl_cancelled_3m",
        "description": "As above, but the notice must also fall in the last 12 months.",
        "match": {"all": [
            {"id": "accc_notice", "fact": "notice", "regulator": "ACCC", "window": {"last": "P12M"}},
            {"id": "afsl_cancelled", "fact": "licence_event", "event_type": "CANCELLED_OR_LAPSED",
             "licence_kind": "AFSL", "window": {"last": "P3M"}},
        ]},
    },
    "banned_and_licensed": {
        "name": "banned_and_licensed",
        "description": "Parties with a ban attributed at confidence >= 0.95 and a licence of any kind.",
        "match": {"all": [
            {"id": "ban", "fact": "ban", "min_confidence": 0.95},
            {"id": "licence", "fact": "licence"},
        ]},
    },
}


def load_spec(name_or_path: str, as_of: date | None = None) -> CriteriaSpec:
    if name_or_path in NAMED_SPECS:
        spec = CriteriaSpec.from_dict(NAMED_SPECS[name_or_path])
    else:
        spec = CriteriaSpec.from_json(name_or_path)
    if as_of:
        spec.as_of = as_of
    return spec


# --------------------------------------------------------------------------- compilers


@dataclass
class CompiledQuery:
    pred: Predicate
    engine: str
    text: str
    params: list[Any] = field(default_factory=list)


class QueryCompiler:
    engine = "?"

    def compile(self, pred: Predicate, spec: CriteriaSpec, **ctx: Any) -> CompiledQuery:  # pragma: no cover
        raise NotImplementedError


class SparqlCompiler(QueryCompiler):
    """Graph predicates. Every query returns ?party ?fact ?g ?rec ?link ?mt ?conf ?from ?to
    plus fact-specific columns."""

    engine = "sparql"

    def __init__(self, links_graph: str | None) -> None:
        self.links_graph = links_graph

    def compile(self, pred: Predicate, spec: CriteriaSpec, restrict: Sequence[str] | None = None,
                **ctx: Any) -> CompiledQuery:
        if not self.links_graph:
            raise ValueError("graph predicates need a links graph (no urn:graph:links:* loaded)")
        p = pred.params
        minc = pred.min_confidence if pred.min_confidence is not None else spec.min_confidence
        win = pred.window.bounds(spec.as_of) if pred.window else None
        if pred.fact == "notice":
            cls, role = "bg:InfringementNotice", "bg:noticeRecipient"
            extra_sel = "?reg ?amt ?desc"
            extra = """OPTIONAL { ?fact bg:regulator ?reg0 } OPTIONAL { ?fact bg:amountAud ?amt }
                       OPTIONAL { ?fact bg:description ?desc } OPTIONAL { ?rec bg:sourceId ?srcid }"""
            # regulator literal if the exporter wrote one, else implied by the ACCC register source
            filters = ['BIND(COALESCE(?reg0, IF(?srcid = "accc_notice", "ACCC", ?reg0)) AS ?reg)']
            if p.get("regulator"):
                filters.append(f"FILTER(?reg = {str_lit(str(p['regulator']).upper())})")
            if win:  # an event: its date (validFrom) must fall inside the window
                filters.append(f"FILTER(BOUND(?from) && ?from >= {date_lit(win[0])} && ?from <= {date_lit(win[1])})")
        elif pred.fact == "ban":
            cls, role = "bg:Ban", "bg:bannedParty"
            extra_sel = "?bt ?desc"
            extra = "OPTIONAL { ?fact bg:banType ?bt } OPTIONAL { ?fact bg:description ?desc }"
            filters = []
            if p.get("ban_type"):
                filters.append(f"FILTER(?bt = {str_lit(p['ban_type'])})")
            filters += self._overlap(win, p.get("active_on_as_of"), spec.as_of)
        elif pred.fact == "licence":
            cls, role = "bg:Licence", "bg:licensee"
            extra_sel = "?lk ?num ?status"
            extra = """OPTIONAL { ?fact bg:licenceKind ?lk } OPTIONAL { ?fact bg:licenceNumber ?num }
                       OPTIONAL { ?fact bg:licenceStatus ?status }"""
            filters = []
            if p.get("licence_kind"):
                filters.append(f"FILTER(?lk = bg:{p['licence_kind']})")
            if p.get("status"):
                vals = p["status"] if isinstance(p["status"], list) else [p["status"]]
                filters.append(f"FILTER(?status IN ({', '.join(str_lit(v) for v in vals)}))")
            filters += self._overlap(win, p.get("active_on_as_of"), spec.as_of)
        else:
            raise ValueError(f"{pred.fact} is not a graph predicate")
        if minc:
            filters.append(f"FILTER(!BOUND(?conf) || ?conf >= {float(minc)})")
        restrict_clause = values_clause("party", restrict) if restrict is not None else ""
        text = PREFIXES + f"""SELECT ?party ?fact ?g ?rec ?link ?mt ?conf ?from ?to {extra_sel} WHERE {{
  {restrict_clause}
  GRAPH ?g {{ ?fact a {cls} ; bg:aboutRecord ?rec .
    OPTIONAL {{ ?fact bg:validFrom ?from }} OPTIONAL {{ ?fact bg:validTo ?to }} }}
  GRAPH {iri_term(self.links_graph)} {{
    ?fact {role} ?party .
    OPTIONAL {{ ?link bg:sourceRecord ?rec ; bg:party ?party .
               OPTIONAL {{ ?link bg:matchType ?mt }} OPTIONAL {{ ?link bg:confidence ?conf }} }} }}
  {extra}
  {' '.join(filters)}
}}"""
        return CompiledQuery(pred, "sparql", text)

    @staticmethod
    def _overlap(win: tuple[date, date] | None, active: Any, as_of: date) -> list[str]:
        out = []
        if win:  # the validity interval overlaps the window
            out.append(f"FILTER((!BOUND(?from) || ?from <= {date_lit(win[1])}) && (!BOUND(?to) || ?to >= {date_lit(win[0])}))")
        if active:
            out.append(f"FILTER((!BOUND(?from) || ?from <= {date_lit(as_of)}) && (!BOUND(?to) || ?to >= {date_lit(as_of)}))")
        return out


class SqlCompiler(QueryCompiler):
    """Tabular predicates on DuckDB. Every query returns canonical_key, abn, acn, lei,
    party_type, arsn_flag plus evidence columns."""

    engine = "sql"

    def __init__(self, matcher_version: str | None) -> None:
        self.matcher_version = matcher_version

    def compile(self, pred: Predicate, spec: CriteriaSpec, restrict_table: str | None = None,
                **ctx: Any) -> CompiledQuery:
        p = pred.params
        params: list[Any] = []
        restrict = f" AND pc.canonical_key IN (SELECT canonical_key FROM {restrict_table})" if restrict_table else ""
        if pred.fact == "licence_event":
            conds = ["1 = 1"]
            if p.get("event_type"):
                conds.append("ev.event_type = ?")
                params.append(p["event_type"])
            if p.get("licence_kind"):
                conds.append("ev.licence_kind = ?")
                params.append(p["licence_kind"])
            if pred.window:
                lo, hi = pred.window.bounds(spec.as_of)
                conds.append("ev.event_date BETWEEN ? AND ?")
                params += [lo, hi]
                if p.get("certain"):
                    conds.append("ev.observed_after >= ?")
                    params.append(lo)
            mv = "AND l.matcher_version = ?" if self.matcher_version else ""
            mv_params = [self.matcher_version] if self.matcher_version else []
            minc = pred.min_confidence if pred.min_confidence is not None else spec.min_confidence
            text = f"""
WITH ev AS (SELECT * FROM licence_event ev WHERE {' AND '.join(conds)}),
linked AS (
  SELECT ev.*, l.link_id, l.canonical_key, l.match_type, l.confidence, 'link' AS attribution
  FROM ev JOIN link l ON l.source = ev.source
                     AND ltrim(l.record_id, '0') = ltrim(ev.licence_no, '0') {mv}
  WHERE coalesce(l.confidence, 1.0) >= ?),
by_id AS (
  SELECT ev.*, NULL AS link_id, pc.canonical_key,
         CASE WHEN pc.abn = ev.holder_abn_before THEN 'EVENT_HOLDER_ABN' ELSE 'EVENT_HOLDER_ACN' END AS match_type,
         NULL::DOUBLE AS confidence, 'holder_identifier' AS attribution
  FROM ev JOIN party_canonical pc
    ON (ev.holder_abn_before IS NOT NULL AND pc.abn = ev.holder_abn_before)
    OR (ev.holder_abn_before IS NULL AND ev.holder_acn_before IS NOT NULL AND pc.acn = ev.holder_acn_before)
  WHERE NOT EXISTS (SELECT 1 FROM linked x WHERE x.source = ev.source AND x.licence_no = ev.licence_no
                                            AND x.event_date = ev.event_date))
SELECT pc.canonical_key, pc.abn, pc.acn, pc.lei, pc.party_type, pc.name,
       e.source, e.licence_kind, e.licence_no, e.event_type, e.event_date, e.observed_after,
       e.holder_name_before, e.record_iri, e.link_id, e.match_type, e.confidence, e.attribution
FROM (SELECT * FROM linked UNION ALL SELECT * FROM by_id) e
JOIN party_canonical pc ON pc.canonical_key = e.canonical_key
WHERE 1 = 1{restrict}
ORDER BY pc.canonical_key, e.event_date DESC"""
            # placeholder order: ev conditions, then the link join's matcher version, then confidence
            return CompiledQuery(pred, "sql", text, [*params, *mv_params, float(minc or 0.0)])
        if pred.fact == "party":
            fld, op, val = p.get("field"), p.get("op", "="), p.get("value")
            if fld not in PARTY_FIELDS:
                raise ValueError(f"party field {fld!r} not allowed; use one of {PARTY_FIELDS}")
            if op not in SQL_OPS:
                raise ValueError(f"op {op!r} not allowed; use one of {sorted(SQL_OPS)}")
            if op in ("is_null", "not_null"):
                cond = f"pc.{fld} {SQL_OPS[op]}"
            elif op == "in":
                vals = list(val or [])
                cond = f"pc.{fld} IN ({', '.join('?' for _ in vals)})" if vals else "1 = 0"
                params += vals
            else:
                cond = f"pc.{fld} {SQL_OPS[op]} ?"
                params.append(val)
            text = f"""SELECT pc.canonical_key, pc.abn, pc.acn, pc.lei, pc.party_type, pc.name, pc.{fld} AS value,
       'party_canonical' AS source
FROM party_canonical pc WHERE {cond}{restrict} ORDER BY pc.canonical_key"""
            return CompiledQuery(pred, "sql", text, params)
        raise ValueError(f"{pred.fact} is not a tabular predicate")


# --------------------------------------------------------------------------- planner


@dataclass
class QueryPlan:
    spec: CriteriaSpec
    steps: list[CompiledQuery]
    links_graph: str | None
    matcher_version: str | None

    def explain(self) -> str:
        lines = [f"spec {self.spec.name} as_of={self.spec.as_of} links_graph={self.links_graph}",
                 f"boolean: {json.dumps(self.spec.match.to_obj(), default=str)}"]
        for s in self.steps:
            lines.append(f"-- {s.pred.id} [{s.engine}] {s.pred.fact}")
            lines.append(s.text.strip())
            if s.params:
                lines.append(f"-- params: {s.params}")
        return "\n".join(lines)


ENGINE_COST = {"sparql": 0, "sql": 1}  # graph predicates are the selective ones in this data


class QueryPlanner:
    def __init__(self, links_graph: str | None, matcher_version: str | None) -> None:
        self.links_graph = links_graph
        self.matcher_version = matcher_version
        self.sparql = SparqlCompiler(links_graph)
        self.sql = SqlCompiler(matcher_version)

    def compiler(self, pred: Predicate) -> QueryCompiler:
        return self.sparql if pred.engine == "sparql" else self.sql

    def order(self, children: list[BoolNode]) -> list[BoolNode]:
        """Within 'all': graph predicates first, then SQL, 'not' last."""
        def cost(n: BoolNode) -> int:
            if n.op == "not":
                return 9
            if n.pred:
                return ENGINE_COST[n.pred.engine] + (2 if n.pred.fact == "party" else 0)
            return 5
        return sorted(children, key=cost)

    def plan(self, spec: CriteriaSpec) -> QueryPlan:
        """Unrestricted compiled text per predicate (what `explain` shows). At run time the
        service recompiles later predicates with the surviving keys pushed in."""
        steps = [self.compiler(p).compile(p, spec) for p in spec.predicates]
        return QueryPlan(spec, steps, self.links_graph, self.matcher_version)


# --------------------------------------------------------------------------- service


def party_iri(key: str | None, abn: str | None, acn: str | None, lei: str | None,
              party_type: str | None = None) -> str | None:
    """The canonical key rendered as the graph's party IRI (same rule as the exporter)."""
    if (party_type or "").lower() in _SCHEME_TYPES:
        acn = None
    return IriFactory.party(abn, acn, lei, key)


@dataclass
class Evidence:
    rows: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))


class ProjectionService:
    def __init__(self, fuseki: SparqlEndpoint | None, store: Any = None, matcher_version: str | None = None,
                 links_graph: str | None = "auto") -> None:
        self.ep = fuseki
        self.store = store
        self.con = getattr(store, "con", store)
        if links_graph == "auto":
            links_graph = pick_links_graph(fuseki, matcher_version, store) if fuseki is not None else None
        self.links_graph = links_graph
        self.matcher_version = matcher_version or (
            links_graph[len(LINKS_GRAPH_PREFIX):] if links_graph and links_graph.startswith(LINKS_GRAPH_PREFIX) else None)
        self.planner = QueryPlanner(self.links_graph, self.matcher_version)
        self.last_run: dict[str, Any] = {}

    # ------------------------------------------------------------------ execution

    def _run_sparql(self, pred: Predicate, spec: CriteriaSpec, restrict: set[str] | None) -> dict[str, list[dict]]:
        if self.ep is None:
            raise ValueError("graph predicate without a SPARQL endpoint")
        out: dict[str, list[dict]] = defaultdict(list)
        if restrict is not None and not restrict:
            return out
        batches: Iterable[Sequence[str] | None] = [None] if restrict is None else [
            sorted(restrict)[i:i + 500] for i in range(0, len(restrict), 500)]
        for b in batches:
            cq = self.planner.sparql.compile(pred, spec, restrict=b)
            self.last_run.setdefault("queries", []).append({"id": pred.id, "engine": "sparql", "text": cq.text})
            for r in self.ep.query(cq.text):
                r = {k: (float(v) if isinstance(v, Decimal) else v) for k, v in r.items()}
                out[r["party"]].append({
                    "fact": r["fact"], "date": r.get("from"), "valid_from": r.get("from"), "valid_to": r.get("to"),
                    "source": r.get("g"), "record": r.get("rec"), "link": r.get("link"),
                    "match_type": local(r.get("mt")), "confidence": r.get("conf"), "attribution": "link",
                    **{k: (local(v) if isinstance(v, str) else v) for k, v in r.items()
                       if k in ("reg", "amt", "desc", "bt", "lk", "num", "status")},
                })
        return out

    def _run_sql(self, pred: Predicate, spec: CriteriaSpec, restrict: set[str] | None,
                 keys_by_iri: dict[str, str]) -> dict[str, list[dict]]:
        if self.con is None:
            raise ValueError(f"tabular predicate {pred.id} ({pred.fact}) needs a DuckDB store")
        out: dict[str, list[dict]] = defaultdict(list)
        table = None
        if restrict is not None:
            if not restrict:
                return out
            keys = self._keys_for_iris(restrict, keys_by_iri)
            table = "_proj_restrict"
            self.con.execute(f"CREATE OR REPLACE TEMP TABLE {table} (canonical_key VARCHAR)")
            if keys:
                self.con.executemany(f"INSERT INTO {table} VALUES (?)", [[k] for k in sorted(keys)])
        cq = self.planner.sql.compile(pred, spec, restrict_table=table)
        self.last_run.setdefault("queries", []).append({"id": pred.id, "engine": "sql", "text": cq.text,
                                                        "params": [str(p) for p in cq.params]})
        cur = self.con.execute(cq.text, cq.params)
        cols = [c[0] for c in cur.description]
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            iri = party_iri(r["canonical_key"], r.get("abn"), r.get("acn"), r.get("lei"), r.get("party_type"))
            keys_by_iri[iri] = r["canonical_key"]
            if pred.fact == "licence_event":
                ev = {"fact": f"licence_event:{r['source']}:{r['licence_no']}:{r['event_type']}:{r['event_date']}",
                      "date": r["event_date"], "event_date": r["event_date"], "observed_after": r["observed_after"],
                      "source": "duckdb:licence_event", "record": r.get("record_iri"), "link": r.get("link_id"),
                      "match_type": r.get("match_type"), "confidence": r.get("confidence"),
                      "attribution": r.get("attribution"), "lk": r.get("licence_kind"), "num": r.get("licence_no"),
                      "holder_name_before": r.get("holder_name_before")}
            else:
                ev = {"fact": f"party_canonical:{r['canonical_key']}", "date": None, "source": "duckdb:party_canonical",
                      "value": r.get("value"), "attribution": "attribute", "confidence": None}
            out[iri].append(ev)
        if table:
            self.con.execute(f"DROP TABLE IF EXISTS {table}")
        return out

    def _keys_for_iris(self, iris: Iterable[str], known: dict[str, str]) -> set[str]:
        keys, todo = set(), []
        for i in iris:
            if i in known:
                keys.add(known[i])
            else:
                todo.append(i)
        if todo:
            df = pd.DataFrame({"iri": todo})
            self.con.register("_proj_iris", df)
            try:
                rows = self.con.execute("""
                    SELECT i.iri, pc.canonical_key FROM _proj_iris i JOIN party_canonical pc
                      ON (i.iri LIKE 'urn:abn:%' AND pc.abn = substr(i.iri, 9))
                      OR (i.iri LIKE 'urn:acn:%' AND pc.acn = substr(i.iri, 9) AND pc.abn IS NULL)
                      OR (i.iri LIKE 'urn:lei:%' AND pc.lei = substr(i.iri, 9) AND pc.abn IS NULL AND pc.acn IS NULL)
                      OR pc.canonical_key = i.iri""").fetchall()
            finally:
                self.con.unregister("_proj_iris")
            for iri, key in rows:
                known[iri] = key
                keys.add(key)
        return keys

    def _eval(self, node: BoolNode, spec: CriteriaSpec, restrict: set[str] | None, ev: Evidence,
              keys_by_iri: dict[str, str]) -> set[str]:
        if node.pred:
            p = node.pred
            res = (self._run_sparql(p, spec, restrict) if p.engine == "sparql"
                   else self._run_sql(p, spec, restrict, keys_by_iri))
            for k, rows in res.items():
                ev.rows[(p.id, k)] += rows  # type: ignore[index]
            return set(res) if restrict is None else set(res) & restrict
        if node.op == "all":
            cur = restrict
            for c in self.planner.order(node.children):
                if c.op == "not":
                    if cur is None:
                        raise ValueError("'not' needs a positive sibling evaluated before it")
                    cur = cur - self._eval(c.children[0], spec, cur, ev, keys_by_iri)
                else:
                    got = self._eval(c, spec, cur, ev, keys_by_iri)
                    cur = got if cur is None else cur & got
                if not cur:
                    return set()
            return cur or set()
        if node.op == "any":
            acc: set[str] = set()
            for c in node.children:
                acc |= self._eval(c, spec, restrict, ev, keys_by_iri)
            return acc
        raise ValueError(f"unexpected node {node.op}")

    def plan(self, spec: CriteriaSpec) -> QueryPlan:
        return self.planner.plan(spec)

    def project(self, spec: CriteriaSpec | dict[str, Any] | str) -> pd.DataFrame:
        if isinstance(spec, dict):
            spec = CriteriaSpec.from_dict(spec)
        elif isinstance(spec, str):
            spec = load_spec(spec)
        t0 = time.perf_counter()
        self.last_run = {"spec": spec.name, "as_of": spec.as_of.isoformat(), "links_graph": self.links_graph,
                         "queries": []}
        ev = Evidence()
        keys_by_iri: dict[str, str] = {}
        parties = self._eval(spec.match, spec, None, ev, keys_by_iri)
        df = self._assemble(spec, sorted(parties), ev, keys_by_iri)
        self.last_run["rows"] = len(df)
        self.last_run["elapsed_ms"] = (time.perf_counter() - t0) * 1000
        return df

    # ------------------------------------------------------------------ assembly

    def _party_attrs(self, iris: Sequence[str], keys_by_iri: dict[str, str]) -> dict[str, dict[str, Any]]:
        attrs: dict[str, dict[str, Any]] = {i: {} for i in iris}
        if self.ep is not None:
            for i in range(0, len(iris), 400):
                chunk = iris[i:i + 400]
                for r in self.ep.query(PREFIXES + f"""SELECT ?p ?name ?abn ?acn ?lei ?type WHERE {{
                        {values_clause('p', chunk)}
                        GRAPH <{GRAPH_CANONICAL}> {{ ?p a ?type . OPTIONAL {{ ?p bg:name ?name }}
                          OPTIONAL {{ ?p bg:abn ?abn }} OPTIONAL {{ ?p bg:acn ?acn }} OPTIONAL {{ ?p bg:lei ?lei }} }} }}"""):
                    a = attrs[r["p"]]
                    for k in ("name", "abn", "acn", "lei"):
                        if r.get(k) and not a.get(k):
                            a[k] = r[k]
                    a.setdefault("party_type", local(r.get("type")))
        if self.con is not None:
            missing = [i for i in iris if not attrs[i].get("name")]
            if missing:
                self._keys_for_iris(missing, keys_by_iri)
                keys = {keys_by_iri[i]: i for i in missing if i in keys_by_iri}
                if keys:
                    df = pd.DataFrame({"k": list(keys)})
                    self.con.register("_proj_keys", df)
                    try:
                        for k, name, abn, acn, lei, pt in self.con.execute(
                                "SELECT canonical_key, name, abn, acn, lei, party_type FROM party_canonical "
                                "WHERE canonical_key IN (SELECT k FROM _proj_keys)").fetchall():
                            attrs[keys[k]].update({"name": name, "abn": abn, "acn": acn, "lei": lei,
                                                   "party_type": pt})
                    finally:
                        self.con.unregister("_proj_keys")
        for i in iris:
            attrs[i]["canonical_key"] = keys_by_iri.get(i)
        return attrs

    def _assemble(self, spec: CriteriaSpec, parties: list[str], ev: Evidence,
                  keys_by_iri: dict[str, str]) -> pd.DataFrame:
        attrs = self._party_attrs(parties, keys_by_iri)
        recs = []
        for party in parties:
            a = attrs.get(party, {})
            row: dict[str, Any] = {"party": party, "canonical_key": a.get("canonical_key"), "name": a.get("name"),
                                   "abn": a.get("abn"), "acn": a.get("acn"), "lei": a.get("lei"),
                                   "party_type": a.get("party_type"), "links_graph": self.links_graph,
                                   "as_of": spec.as_of}
            confs = []
            matched = []
            for p in spec.predicates:
                rows = ev.rows.get((p.id, party), [])  # type: ignore[call-overload]
                if not rows:
                    continue
                matched.append(p.id)
                best = sorted(rows, key=lambda r: (r.get("date") or date.min), reverse=True)[0]
                pre = f"{p.id}__"
                row[pre + "n_matches"] = len({r["fact"] for r in rows})
                for k_out, k_in in (("fact", "fact"), ("date", "date"), ("valid_from", "valid_from"),
                                    ("valid_to", "valid_to"), ("event_date", "event_date"),
                                    ("observed_after", "observed_after"), ("source", "source"),
                                    ("record", "record"), ("link", "link"), ("match_type", "match_type"),
                                    ("confidence", "confidence"), ("attribution", "attribution"),
                                    ("regulator", "reg"), ("amount_aud", "amt"), ("ban_type", "bt"),
                                    ("licence_kind", "lk"), ("licence_number", "num"), ("status", "status"),
                                    ("holder_name_before", "holder_name_before"), ("value", "value")):
                    if k_in in best:
                        row[pre + k_out] = best[k_in]
                if p.fact == "licence_event":
                    row.setdefault(pre + "event_date", None)
                    row.setdefault(pre + "observed_after", None)
                if best.get("confidence") is not None:
                    confs.append(float(best["confidence"]))
            row["matched_predicates"] = ",".join(matched)
            row["min_link_confidence"] = min(confs) if confs else None
            recs.append(row)
        df = pd.DataFrame.from_records(recs)
        if df.empty:
            cols = ["party", "canonical_key", "name", "abn", "acn", "lei", "party_type", "links_graph", "as_of",
                    "matched_predicates", "min_link_confidence"]
            for p in spec.predicates:
                cols += [f"{p.id}__fact", f"{p.id}__source", f"{p.id}__link", f"{p.id}__match_type",
                         f"{p.id}__confidence"]
                if p.fact == "licence_event":
                    cols += [f"{p.id}__event_date", f"{p.id}__observed_after"]
            df = pd.DataFrame(columns=cols)
        if spec.columns:
            keep: list[str] = []
            for c in spec.columns:
                if c.endswith("*"):
                    keep += [x for x in df.columns if x.startswith(c[:-1]) and x not in keep]
                elif c in df.columns and c not in keep:
                    keep.append(c)
            df = df[keep]
        if spec.limit:
            df = df.head(spec.limit)
        return df.reset_index(drop=True)


def write_projection(df: pd.DataFrame, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path, index=False)
    return path
