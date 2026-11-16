"""TraversalService: bounded graph traversals over the published graph (FR7, ARCHITECTURE.md 2.7, 3.7).

Three things the brief asks for live here:

* **Ultimate parent** (`ultimate_parent`): a breadth-first walk in Python over one-hop
  SPARQL queries. Each hop asks "direct parents of this node, valid on `as_of`", so the
  walk controls depth, keeps a visited set, records every edge it took, and stops with a
  named status (TOP_REACHED, NO_PARENT, CYCLE, TRUNCATED, AMBIGUOUS). Ownership is not a
  tree: GLEIF allows one direct parent, but shareholdings and links from several records
  to one party give a node several parents, and data errors give cycles.
* **Graph-only questions** (`within_hops`, `near_flagged`, `group_exposure`): N-hop
  neighbourhoods over any party-to-party relationship, and the corporate-group question
  (licensed entities in the same group as a regulatory flag), which needs a variable-depth
  walk up and back down the ownership forest joined against facts on other entities.
* **Caps** (`TraversalBudget`, `entity_view`): every fact type has a quota, items are
  ranked (active before historical, regulatory before licences before ownership before
  products, recent first) and `truncated_counts` says what was dropped.

Nodes. Facts point at source records (`bg:aboutRecord`), party roles exist only in the
links graph `urn:graph:links:{matcher_version}`. A node is therefore the canonical party
when a link (or LEI equality with a canonical party) attributes the record, else the
record itself (`urn:src:gleif_l1:{lei}`). The walk works on both and says which it used.
"""

from __future__ import annotations

import re
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from bizgraph.services.endpoint import (
    BG,
    GRAPH_CANONICAL,
    GRAPH_ONTOLOGY,
    PREFIXES,
    SparqlEndpoint,
    date_lit,
    iri_term,
    local,
    pick_links_graph,
    values_clause,
)

DIRECT = f"{BG}IS_DIRECTLY_CONSOLIDATED_BY"
ULTIMATE = f"{BG}IS_ULTIMATELY_CONSOLIDATED_BY"
SHAREHOLDING = f"{BG}SHAREHOLDING"
DEFAULT_PARENT_KINDS = (DIRECT, SHAREHOLDING)
LEI_RE = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")
GLEIF_L1 = "urn:src:gleif_l1:"
_VALUES_CHUNK = 400  # IRIs per VALUES block (keeps request bodies small)

# Party-level role properties expanded by generic traversals. Read from the ontology graph
# (bg:traversalPolicy "expand", sub-property of bg:subject or bg:counterparty) when it is
# loaded; this list is the fallback and must stay in step with ontology/schema.ttl.
FALLBACK_ROLES = ("owner", "owned", "trust", "trustee", "member", "affiliatedWith",
                  "licensee", "bannedParty", "noticeRecipient", "sponsor")
SINGLE_PARTY_ROLES = ("licensee", "bannedParty", "noticeRecipient", "sponsor")

# Category order for entity views and fan-out ranking: regulatory first, products last.
CATEGORY_ORDER = ("bans", "notices", "licences", "parents", "ultimate_parents", "trusteeships",
                  "affiliations", "subsidiaries", "products", "other")
RELATION_PRIORITY = {"Ownership": 0, "Trusteeship": 1, "Affiliation": 2, "SameIdentifier": 3}
INACTIVE_STATUSES = {"INACTIVE", "inactive", "suspended", "SUSP", "cancelled", "CANCELLED",
                     "lapsed", "LAPSED", "RETIRED", "ANNULLED"}
SUSPENDED_STATUSES = {"suspended", "SUSP", "SUSPENDED"}


# --------------------------------------------------------------------------- data classes


@dataclass(frozen=True)
class NodeRef:
    """A party (canonical IRI) or, when no party attributes it, a source record."""

    key: str
    kind: str  # "party" | "record"
    name: str | None = None
    lei: str | None = None
    records: tuple[str, ...] = ()
    attribution: str | None = None  # link | lei_equality | abn_equality | acn_equality | canonical | none
    link: str | None = None
    match_type: str | None = None
    confidence: float | None = None

    def short(self) -> str:
        return f"{self.name or '?'} [{self.key}]"


@dataclass
class OwnershipEdge:
    fact: str
    kind: str | None
    child: str
    parent: str
    percentage: float | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    status: str | None = None
    source_graph: str | None = None
    source_records: list[str] = field(default_factory=list)
    level: str = "record"  # record (aboutRecord/counterpartyRecord) | party (links-graph roles)
    rule: str | None = None  # single | majority | plurality (set when chosen by the walk)


@dataclass
class OwnershipChain:
    start: NodeRef
    as_of: date
    nodes: list[NodeRef] = field(default_factory=list)
    edges: list[OwnershipEdge] = field(default_factory=list)
    status: str = "NO_PARENT"  # NO_PARENT | TOP_REACHED | CYCLE | TRUNCATED | AMBIGUOUS | NOT_FOUND
    ultimate_parent: NodeRef | None = None
    cycle_detected: bool = False
    cycle_path: list[str] = field(default_factory=list)
    truncated: bool = False
    max_depth: int = 10
    ambiguous_parents: list[OwnershipEdge] = field(default_factory=list)
    gleif_ultimate: list[NodeRef] = field(default_factory=list)
    gleif_check: str | None = None  # agree | disagree_on_chain | disagree_off_chain | no_gleif_ultimate
    links_graph: str | None = None
    queries: int = 0
    elapsed_ms: float = 0.0

    @property
    def depth(self) -> int:
        return len(self.edges)

    @property
    def top(self) -> NodeRef:
        """Last node reached (the ultimate parent only when status is TOP_REACHED/NO_PARENT)."""
        return self.nodes[-1] if self.nodes else self.start

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["depth"] = self.depth
        return d

    def summary(self) -> str:
        parts = [n.short() for n in self.nodes]
        arrow = " -> ".join(parts)
        tail = {
            "CYCLE": f"  CYCLE: {' -> '.join(self.cycle_path)}",
            "TRUNCATED": f"  TRUNCATED at max_depth={self.max_depth}",
            "AMBIGUOUS": f"  AMBIGUOUS: {len(self.ambiguous_parents)} parents, no majority",
        }.get(self.status, "")
        return f"[{self.status}] depth={self.depth}: {arrow}{tail}"


@dataclass
class TraversalBudget:
    """Caps for one traversal. `per_fact_type` keys are entity-view categories
    (bans, notices, licences, parents, subsidiaries, products, ...) plus
    `identifiers`, `source_records` and `neighbours_per_node` (fan-out per node in
    `within_hops`). `max_nodes` caps a neighbourhood."""

    max_depth: int = 10
    max_nodes: int = 200
    per_fact_type: dict[str, int] = field(default_factory=lambda: {
        "identifiers": 30, "source_records": 20, "bans": 20, "notices": 20, "licences": 10,
        "parents": 5, "ultimate_parents": 5, "trusteeships": 10, "affiliations": 10,
        "subsidiaries": 15, "products": 5, "other": 10, "neighbours_per_node": 50,
    })
    rank_by: tuple[str, ...] = ("category", "active", "recency")

    def cap(self, category: str, default: int = 10) -> int:
        return int(self.per_fact_type.get(category, default))


@dataclass
class FactItem:
    fact: str
    category: str
    type: str
    active: bool
    valid_from: date | None = None
    valid_to: date | None = None
    status: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    source_graph: str | None = None
    about_record: str | None = None
    other: str | None = None  # counterparty record/party for relationships
    other_name: str | None = None
    attribution: str | None = None  # link | record | same_identifier

    def sort_key(self) -> tuple[Any, ...]:
        d = self.valid_from or self.valid_to or date.min
        return (0 if self.active else 1, -d.toordinal(), self.fact)


@dataclass
class EntityView:
    party: NodeRef
    identifiers: list[dict[str, str]] = field(default_factory=list)
    source_records: list[dict[str, Any]] = field(default_factory=list)
    facts_by_type: dict[str, list[FactItem]] = field(default_factory=dict)
    truncated_counts: dict[str, int] = field(default_factory=dict)
    totals: dict[str, int] = field(default_factory=dict)
    as_of: date | None = None
    links_graph: str | None = None
    elapsed_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def truncation_note(self) -> str:
        if not self.truncated_counts:
            return "nothing truncated"
        return "; ".join(f"{n} more {k} truncated" for k, n in sorted(self.truncated_counts.items()))


@dataclass
class Neighbour:
    node: NodeRef
    distance: int
    via: list[dict[str, Any]]  # path of hops from the start: relation, fact, from, to


@dataclass
class Neighbourhood:
    start: NodeRef
    hops: int
    neighbours: list[Neighbour] = field(default_factory=list)
    truncated_counts: dict[str, int] = field(default_factory=dict)
    queries: int = 0
    elapsed_ms: float = 0.0


# --------------------------------------------------------------------------- helpers


def _chunks(items: Sequence[str], n: int = _VALUES_CHUNK) -> Iterable[Sequence[str]]:
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v) if not isinstance(v, float) else v
    except (TypeError, ValueError):
        return None


def _d(v: Any) -> date | None:
    if v is None or isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def is_valid_on(valid_from: date | None, valid_to: date | None, on: date) -> bool:
    return (valid_from is None or valid_from <= on) and (valid_to is None or valid_to >= on)


def validity_filter(as_of: date, f: str = "from", t: str = "to") -> str:
    """SPARQL FILTER: open-ended intervals are valid; a closed interval must contain as_of."""
    d = date_lit(as_of)
    return f"FILTER ((!BOUND(?{f}) || ?{f} <= {d}) && (!BOUND(?{t}) || ?{t} >= {d}))"


def choose_parent(cands: list[OwnershipEdge]) -> tuple[OwnershipEdge | None, str]:
    """The majority/percentage rule. One parent: follow it. A parent above 50 per cent:
    follow it (it controls whatever the others hold). All percentages known and one
    strictly highest: follow it, flagged 'plurality'. Otherwise ambiguous: stop."""
    if len(cands) == 1:
        return cands[0], "single"
    for c in cands:
        if c.percentage is not None and c.percentage > 50:
            return c, "majority"
    pcts = [c.percentage for c in cands]
    if all(p is not None for p in pcts):
        top = max(pcts)
        if pcts.count(top) == 1:
            return cands[pcts.index(top)], "plurality"
    return None, "ambiguous"


def walk_chain(start: NodeRef, parents_of: Callable[[NodeRef], list[tuple[OwnershipEdge, NodeRef]]],
               max_depth: int, as_of: date) -> OwnershipChain:
    """The bounded walk. Pure: `parents_of` is the only I/O, so the same code runs over
    one-hop SPARQL queries and over an in-memory index."""
    chain = OwnershipChain(start=start, as_of=as_of, nodes=[start], max_depth=max_depth)
    visited: dict[str, int] = {start.key: 0}
    cur = start
    while True:
        found = parents_of(cur)
        by_parent: dict[str, tuple[OwnershipEdge, NodeRef]] = {}
        for edge, node in found:  # the same parent through several facts counts once
            prev = by_parent.get(node.key)
            if prev is None or (edge.percentage or -1) > (prev[0].percentage or -1):
                by_parent[node.key] = (edge, node)
        if not by_parent:
            chain.status = "NO_PARENT" if chain.depth == 0 else "TOP_REACHED"
            chain.ultimate_parent = cur if chain.depth else None
            break
        cands = sorted(by_parent.values(), key=lambda en: en[1].key)
        chosen, rule = choose_parent([e for e, _ in cands])
        if chosen is None:
            chain.status = "AMBIGUOUS"
            chain.ambiguous_parents = [e for e, _ in cands]
            break
        if chain.depth >= max_depth:
            chain.status, chain.truncated = "TRUNCATED", True
            break
        chosen.rule = rule
        parent = next(n for e, n in cands if e is chosen)
        chain.edges.append(chosen)
        if parent.key in visited:
            chain.status, chain.cycle_detected = "CYCLE", True
            loop = [n.key for n in chain.nodes[visited[parent.key]:]] + [parent.key]
            chain.cycle_path = loop
            break
        visited[parent.key] = len(chain.nodes)
        chain.nodes.append(parent)
        cur = parent
    return chain


# Shown in outputs/graph_queries.md next to the Python walk.
PROPERTY_PATH_QUERY = PREFIXES + """
# All ancestors through any fact whose subject record is ?x and whose counterparty is a record.
SELECT DISTINCT ?ancestor WHERE {
  <START> (^bg:aboutRecord/bg:counterpartyRecord)+ ?ancestor .
  FILTER NOT EXISTS { ?ancestor ^bg:aboutRecord/bg:counterpartyRecord ?higher }
}"""

PROPERTY_PATH_WHY_NOT = (
    "A property path cannot (1) filter the intermediate bg:Ownership node on relationshipKind "
    "or validity, so it mixes DIRECT and ULTIMATE edges and expired ones; (2) bound the depth "
    "(SPARQL 1.1 has no {1,10}); (3) return the path, the depth or the percentages taken; "
    "(4) pick one parent when there are several; and (5) say anything about cycles: '+' has set "
    "semantics so it terminates, but every node in a cycle has a parent, so the 'no higher "
    "ancestor' filter returns nothing and the cycle is invisible."
)


# --------------------------------------------------------------------------- service


class TraversalService:
    def __init__(self, fuseki: SparqlEndpoint, store: Any = None, matcher_version: str | None = None,
                 links_graph: str | None = "auto") -> None:
        self.ep = fuseki
        self.store = store
        if links_graph == "auto":
            links_graph = pick_links_graph(fuseki, matcher_version, store)
        self.links_graph = links_graph
        self.n_queries = 0
        self._node_cache: dict[str, NodeRef] = {}
        self._roles: tuple[str, ...] | None = None

    # ------------------------------------------------------------------ plumbing

    def q(self, body: str) -> list[dict[str, Any]]:
        self.n_queries += 1
        return self.ep.query(PREFIXES + body)

    def _links(self, body: str) -> str:
        """Wrap a pattern in the links graph, or return a pattern that matches nothing."""
        if not self.links_graph:
            return "FILTER(false)"
        return f"GRAPH {iri_term(self.links_graph)} {{ {body} }}"

    def roles(self) -> tuple[str, ...]:
        if self._roles is None:
            rows = self.q(f"""SELECT DISTINCT ?r WHERE {{ GRAPH <{GRAPH_ONTOLOGY}> {{
                ?r bg:traversalPolicy "expand" ; rdfs:subPropertyOf ?sup .
                VALUES ?sup {{ bg:subject bg:counterparty }} }} }}""")
            found = tuple(sorted(local(r["r"]) for r in rows))
            self._roles = found or FALLBACK_ROLES
        return self._roles

    # ------------------------------------------------------------------ node resolution

    def resolve(self, key: str) -> NodeRef | None:
        """A user key (LEI, ABN, ACN, party IRI, record IRI) -> node."""
        k = key.strip()
        if k in self._node_cache:
            return self._node_cache[k]
        node: NodeRef | None = None
        if LEI_RE.match(k.upper()):
            node = self._node_for_lei(k.upper())
        elif k.startswith("urn:src:"):
            node = self.nodes_for_records([k]).get(k)
        elif k.startswith("urn:lei:"):
            node = self._party(k) or self._node_for_lei(k.split(":", 2)[2])
        elif k.startswith("urn:"):
            node = self._party(k)
            if node is None and k.startswith(("urn:abn:", "urn:acn:")):
                node = self._node_for_identifier(k.split(":")[1], k.split(":", 2)[2])
        elif k.isdigit() and len(k) in (9, 11):
            scheme = "abn" if len(k) == 11 else "acn"
            node = self._party(f"urn:{scheme}:{k}") or self._node_for_identifier(scheme, k)
        if node:
            self._node_cache[k] = node
        return node

    def _party(self, iri: str) -> NodeRef | None:
        rows = self.q(f"""SELECT ?name ?lei WHERE {{ GRAPH <{GRAPH_CANONICAL}> {{
            {iri_term(iri)} a ?t . OPTIONAL {{ {iri_term(iri)} bg:name ?name }}
            OPTIONAL {{ {iri_term(iri)} bg:lei ?lei }} }} }} LIMIT 1""")
        if not rows:
            return None
        return NodeRef(iri, "party", rows[0].get("name"), rows[0].get("lei"),
                       tuple(self.records_of_party(iri)), attribution="canonical")

    def _node_for_lei(self, lei: str) -> NodeRef:
        rows = self.q(f"""SELECT ?p WHERE {{ GRAPH <{GRAPH_CANONICAL}> {{ ?p bg:lei "{lei}" }} }} LIMIT 2""")
        if len(rows) == 1:
            p = self._party(rows[0]["p"])
            if p:
                return p
        rec = GLEIF_L1 + lei
        return self.nodes_for_records([rec])[rec]

    def _node_for_identifier(self, scheme: str, value: str) -> NodeRef | None:
        rows = self.q(f"""SELECT ?r ?src WHERE {{ ?r a bg:SourceRecord ; bg:{scheme} "{value}" ;
            bg:sourceId ?src }} ORDER BY ?src ?r LIMIT 50""")
        if not rows:
            return None
        recs = sorted({r["r"] for r in rows}, key=lambda r: (not r.startswith(GLEIF_L1), r))
        return self.nodes_for_records(recs[:1])[recs[0]]

    def records_of_party(self, party: str) -> list[str]:
        """Linked records, the records the party was derived from, its GLEIF record by LEI,
        and GLEIF records carrying its ABN/ACN (so ownership is reachable before GLEIF is
        resolved; nodes_for_records applies the same equality rule in the other direction)."""
        rows = self.q(f"""SELECT DISTINCT ?rec WHERE {{
            {{ {self._links(f'?l bg:party {iri_term(party)} ; bg:sourceRecord ?rec .')} }}
            UNION {{ GRAPH <{GRAPH_CANONICAL}> {{ {iri_term(party)} prov:wasDerivedFrom ?rec }} }}
            UNION {{ GRAPH <{GRAPH_CANONICAL}> {{ {iri_term(party)} bg:lei ?lei }}
                     BIND(IRI(CONCAT("{GLEIF_L1}", ?lei)) AS ?rec) }}
            UNION {{ GRAPH <{GRAPH_CANONICAL}> {{ {iri_term(party)} ?scheme ?v }} VALUES ?scheme {{ bg:abn bg:acn }}
                     ?rec ?scheme ?v ; bg:sourceId "gleif_l1" . }}
        }}""")
        return sorted({r["rec"] for r in rows})

    def nodes_for_records(self, recs: Iterable[str]) -> dict[str, NodeRef]:
        """Record -> node: the linked party (links graph), else the canonical party with the
        same LEI (GLEIF records), else the record itself."""
        recs = sorted(set(recs))
        out: dict[str, NodeRef] = {}
        todo = [r for r in recs if r not in self._node_cache]
        for r in recs:
            if r in self._node_cache:
                out[r] = self._node_cache[r]
        for chunk in _chunks(todo):
            rows = self.q(f"""SELECT ?rec ?p ?l ?mt ?conf ?pname ?plei ?how ?rname ?rlei WHERE {{
                {values_clause('rec', chunk)}
                OPTIONAL {{ ?rec bg:nameRaw ?rname }} OPTIONAL {{ ?rec bg:lei ?rlei }}
                OPTIONAL {{
                  {{ {self._links('?l bg:sourceRecord ?rec ; bg:party ?p . OPTIONAL { ?l bg:matchType ?mt } OPTIONAL { ?l bg:confidence ?conf }')}
                     BIND("link" AS ?how) }}
                  UNION
                  {{ ?rec bg:lei ?lei0 . GRAPH <{GRAPH_CANONICAL}> {{ ?p bg:lei ?lei0 }} BIND("lei_equality" AS ?how) }}
                  UNION
                  {{ ?rec bg:abn ?abn0 . GRAPH <{GRAPH_CANONICAL}> {{ ?p bg:abn ?abn0 }} BIND("abn_equality" AS ?how) }}
                  UNION
                  {{ ?rec bg:acn ?acn0 . GRAPH <{GRAPH_CANONICAL}> {{ ?p bg:acn ?acn0 }} BIND("acn_equality" AS ?how) }}
                  OPTIONAL {{ GRAPH <{GRAPH_CANONICAL}> {{ ?p bg:name ?pname }} }}
                  OPTIONAL {{ GRAPH <{GRAPH_CANONICAL}> {{ ?p bg:lei ?plei }} }}
                }}
            }}""")
            # precedence: a resolver link, then equality of one identifier with exactly ONE
            # canonical party (lei > abn > acn); an identifier shared by several parties attributes nothing
            rank = {"link": 0, "lei_equality": 1, "abn_equality": 2, "acn_equality": 3}
            cands: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
            base: dict[str, dict[str, Any]] = {}
            for row in rows:
                base.setdefault(row["rec"], {k: row.get(k) for k in ("rec", "rname", "rlei")})
                if row.get("p") and row.get("how"):
                    cands[(row["rec"], row["how"])][row["p"]] = row
            best: dict[str, dict[str, Any]] = dict(base)
            for (r, how), by_p in sorted(cands.items(), key=lambda kv: rank.get(kv[0][1], 9)):
                if len(by_p) != 1 or best.get(r, {}).get("p"):
                    continue
                best[r] = next(iter(by_p.values()))
            for r in chunk:
                row = best.get(r, {})
                if row.get("p"):
                    node = NodeRef(row["p"], "party", row.get("pname") or row.get("rname"),
                                   row.get("plei") or row.get("rlei"), (r,), row.get("how"),
                                   row.get("l"), local(row.get("mt")), _num(row.get("conf")))
                else:
                    lei = row.get("rlei") or (r[len(GLEIF_L1):] if r.startswith(GLEIF_L1) else None)
                    node = NodeRef(r, "record", row.get("rname"), lei, (r,), "none")
                self._node_cache[r] = node
                out[r] = node
        return out

    def _records_of(self, node: NodeRef) -> list[str]:
        if node.kind == "party":
            return sorted(set(node.records) | set(self.records_of_party(node.key)))
        return list(node.records) or [node.key]

    # ------------------------------------------------------------------ ownership hop

    def ownership_hop_query(self, recs: Sequence[str], as_of: date, kinds: Sequence[str],
                            current_only: bool, direction: str = "up") -> str:
        """One hop of direct ownership for a set of records. direction 'up' = parents."""
        me, other = ("aboutRecord", "counterpartyRecord") if direction == "up" else ("counterpartyRecord", "aboutRecord")
        status = 'FILTER (!BOUND(?status) || ?status != "INACTIVE")' if current_only else ""
        return f"""SELECT ?rec ?f ?g ?kind ?other ?pct ?from ?to ?status ?src WHERE {{
  {values_clause('rec', recs)}
  {values_clause('kind', kinds)}
  GRAPH ?g {{
    ?f a bg:Ownership ; bg:relationshipKind ?kind ; bg:{me} ?rec ; bg:{other} ?other .
    OPTIONAL {{ ?f bg:ownershipPercentage ?pct }}
    OPTIONAL {{ ?f bg:validFrom ?from }}  OPTIONAL {{ ?f bg:validTo ?to }}
    OPTIONAL {{ ?f bg:relationshipStatus ?status }}
    OPTIONAL {{ ?f prov:wasDerivedFrom ?src }}
  }}
  {validity_filter(as_of)}
  {status}
}}"""

    def _party_ownership_query(self, party: str, as_of: date, direction: str = "up") -> str:
        me, other = ("owned", "owner") if direction == "up" else ("owner", "owned")
        return f"""SELECT ?f ?g ?kind ?otherParty ?pct ?from ?to ?status ?src WHERE {{
  {self._links(f'?f bg:{me} {iri_term(party)} ; bg:{other} ?otherParty .')}
  OPTIONAL {{ GRAPH ?g {{ ?f a bg:Ownership .
    OPTIONAL {{ ?f bg:relationshipKind ?kind }} OPTIONAL {{ ?f bg:ownershipPercentage ?pct }}
    OPTIONAL {{ ?f bg:validFrom ?from }} OPTIONAL {{ ?f bg:validTo ?to }}
    OPTIONAL {{ ?f bg:relationshipStatus ?status }} OPTIONAL {{ ?f prov:wasDerivedFrom ?src }} }} }}
  {validity_filter(as_of)}
}}"""

    def _edges_from_rows(self, node: NodeRef, rows: list[dict[str, Any]], other_nodes: dict[str, NodeRef],
                         level: str, direction: str, kinds: Sequence[str],
                         current_only: bool) -> list[tuple[OwnershipEdge, NodeRef]]:
        by_fact: dict[str, OwnershipEdge] = {}
        targets: dict[str, NodeRef] = {}
        for r in rows:
            if level == "party":
                if r.get("kind") and r["kind"] not in kinds:
                    continue
                if current_only and r.get("status") == "INACTIVE":
                    continue
            other = r.get("other") or r.get("otherParty")
            tgt = other_nodes.get(other)
            if tgt is None:
                continue
            if tgt.key == node.key and r.get("rec") not in (None, other):
                # two records of one party owning each other: an identity collapse, not a
                # cycle in the data (a record that owns itself is kept and reported as a cycle)
                continue
            e = by_fact.get(r["f"])
            if e is None:
                child, parent = (node.key, tgt.key) if direction == "up" else (tgt.key, node.key)
                e = OwnershipEdge(r["f"], local(r.get("kind")), child, parent, _num(r.get("pct")),
                                  _d(r.get("from")), _d(r.get("to")), r.get("status"), r.get("g"), [], level)
                by_fact[r["f"]] = e
                targets[r["f"]] = tgt
            if r.get("src") and r["src"] not in e.source_records:
                e.source_records.append(r["src"])
        return [(by_fact[f], targets[f]) for f in sorted(by_fact)]

    def direct_relatives(self, node: NodeRef, as_of: date, kinds: Sequence[str] = DEFAULT_PARENT_KINDS,
                         current_only: bool = True, direction: str = "up") -> list[tuple[OwnershipEdge, NodeRef]]:
        recs = self._records_of(node)
        rows: list[dict[str, Any]] = []
        for chunk in _chunks(recs):
            rows += self.q(self.ownership_hop_query(chunk, as_of, kinds, current_only, direction))
        others = self.nodes_for_records({r["other"] for r in rows})
        out = self._edges_from_rows(node, rows, others, "record", direction, kinds, current_only)
        if node.kind == "party" and self.links_graph:
            prow = self.q(self._party_ownership_query(node.key, as_of, direction))
            seen = {e.fact for e, _ in out}
            prow = [r for r in prow if r["f"] not in seen]
            pnodes = {r["otherParty"]: self._party(r["otherParty"]) or NodeRef(r["otherParty"], "party")
                      for r in prow}
            out += self._edges_from_rows(node, prow, pnodes, "party", direction, kinds, current_only)
        return out

    # ------------------------------------------------------------------ ultimate parent

    def ultimate_parent(self, party_or_lei: str, as_of: date | None = None, max_depth: int = 10,
                        kinds: Sequence[str] = DEFAULT_PARENT_KINDS, cross_check: bool = True) -> OwnershipChain:
        t0 = time.perf_counter()
        q0 = self.n_queries
        current_only = as_of is None
        as_of = as_of or date.today()
        start = self.resolve(party_or_lei)
        if start is None:
            chain = OwnershipChain(start=NodeRef(party_or_lei, "record"), as_of=as_of, status="NOT_FOUND",
                                   max_depth=max_depth, links_graph=self.links_graph)
            chain.elapsed_ms = (time.perf_counter() - t0) * 1000
            return chain
        chain = walk_chain(start, lambda n: self.direct_relatives(n, as_of, kinds, current_only, "up"),
                           max_depth, as_of)
        chain.links_graph = self.links_graph
        if cross_check:
            self._cross_check(chain, as_of, current_only)
        chain.queries = self.n_queries - q0
        chain.elapsed_ms = (time.perf_counter() - t0) * 1000
        return chain

    def _cross_check(self, chain: OwnershipChain, as_of: date, current_only: bool) -> None:
        """Compare with GLEIF's own IS_ULTIMATELY_CONSOLIDATED_BY edge for the start node."""
        rel = self.direct_relatives(chain.start, as_of, (ULTIMATE,), current_only, "up")
        chain.gleif_ultimate = sorted({n.key: n for _, n in rel}.values(), key=lambda n: n.key)
        chain.gleif_check = compare_with_gleif(chain)

    def property_path_ancestors(self, party_or_lei: str) -> dict[str, Any]:
        """Run the property-path version for comparison (record level, no filters)."""
        node = self.resolve(party_or_lei)
        if node is None:
            return {"query": None, "tops": [], "elapsed_ms": 0.0}
        recs = self._records_of(node)
        rec = sorted(recs, key=lambda r: (not r.startswith(GLEIF_L1), r))[0]  # ownership lives on GLEIF records
        sparql = PROPERTY_PATH_QUERY.replace("<START>", iri_term(rec))
        t0 = time.perf_counter()
        rows = self.ep.query(sparql)
        return {"query": sparql, "tops": sorted(r["ancestor"] for r in rows),
                "elapsed_ms": (time.perf_counter() - t0) * 1000, "why_not_enough": PROPERTY_PATH_WHY_NOT}

    # ------------------------------------------------------------------ bulk index (reports)

    def ownership_index(self, as_of: date | None = None,
                        kinds: Sequence[str] = DEFAULT_PARENT_KINDS) -> OwnershipIndex:
        return OwnershipIndex.load(self, as_of, kinds)

    # ------------------------------------------------------------------ facts about a node

    # Two phases: (1) which facts touch these records / this party (cheap, selective joins),
    # (2) the attributes of exactly those facts (VALUES ?f). Putting the attribute block after
    # a UNION in one query made Jena scan every typed fact (5 s instead of 30 ms).
    FACT_ATTRS = """?f a ?type .
    OPTIONAL { ?f bg:relationshipKind ?kind } OPTIONAL { ?f bg:licenceKind ?lk }
    OPTIONAL { ?f bg:licenceNumber ?num } OPTIONAL { ?f bg:licenceStatus ?status }
    OPTIONAL { ?f bg:relationshipStatus ?rstatus }
    OPTIONAL { ?f bg:validFrom ?from } OPTIONAL { ?f bg:validTo ?to }
    OPTIONAL { ?f bg:ownershipPercentage ?pct } OPTIONAL { ?f bg:regulator ?reg }
    OPTIONAL { ?f bg:amountAud ?amt } OPTIONAL { ?f bg:banType ?bt }
    OPTIONAL { ?f bg:description ?desc } OPTIONAL { ?f bg:counterpartyAcn ?cpacn }"""

    def facts_query(self, recs: Sequence[str]) -> str:
        """Phase 1, record level: facts about (subject) or pointing at (counterparty) the records."""
        return f"""SELECT ?f ?rec ?role ?other ?oname WHERE {{
  {values_clause('rec', recs)}
  {{ ?f bg:aboutRecord ?rec . BIND("subject" AS ?role)
     OPTIONAL {{ ?f bg:counterpartyRecord ?other . OPTIONAL {{ ?other bg:nameRaw ?oname }} }} }}
  UNION
  {{ ?f bg:counterpartyRecord ?rec ; bg:aboutRecord ?other . BIND("counterparty" AS ?role)
     OPTIONAL {{ ?other bg:nameRaw ?oname }} }}
}}"""
    # The name lookups stay inside each branch: after the UNION, a fact without a counterparty
    # leaves ?other unbound and the OPTIONAL would bind it to every named record.

    def _party_facts_query(self, party: str) -> str:
        """Phase 1, party level: facts whose role edge in the links graph names the party."""
        roles = " ".join(f"bg:{r}" for r in self.roles())
        return f"""SELECT ?f ?role ?other WHERE {{
  VALUES ?role {{ {roles} }}
  {self._links(f'?f ?role {iri_term(party)} . OPTIONAL {{ ?f ?role2 ?other . VALUES ?role2 {{ {roles} }} FILTER(?other != {iri_term(party)}) }}')}
}}"""

    def fact_attributes(self, facts: Iterable[str]) -> dict[str, dict[str, Any]]:
        """Phase 2: attributes and source graph of the given facts."""
        out: dict[str, dict[str, Any]] = {}
        for chunk in _chunks(sorted(set(facts))):
            for r in self.q(f"""SELECT ?f ?g ?type ?kind ?lk ?num ?status ?rstatus ?from ?to ?pct ?reg ?amt ?bt
                                        ?desc ?cpacn WHERE {{
                    {values_clause('f', chunk)} GRAPH ?g {{ {self.FACT_ATTRS} }} }}"""):
                if r.get("rstatus") and not r.get("status"):
                    r["status"] = r["rstatus"]
                cur = out.get(r["f"])
                if cur is None or (local(r.get("type")) not in ("Fact", "Relationship") and
                                   local(cur.get("type")) in ("Fact", "Relationship")):
                    out[r["f"]] = r
        return out

    @staticmethod
    def _category(ftype: str | None, role: str | None, kind: str | None) -> str:
        t = local(ftype) or ""
        if t == "Ban":
            return "bans"
        if t == "InfringementNotice":
            return "notices"
        if t == "Licence":
            return "licences"
        if t == "Ownership":
            up = role in ("subject", "owned")
            if kind == "IS_ULTIMATELY_CONSOLIDATED_BY":
                return "ultimate_parents" if up else "other"
            return "parents" if up else "subsidiaries"
        if t == "Trusteeship":
            return "trusteeships"
        if t == "Affiliation":
            return "affiliations"
        if t == "ProductSponsorship":
            return "products"
        return "other"

    def facts_of(self, node: NodeRef, as_of: date, records: Sequence[str] | None = None) -> list[FactItem]:
        recs = list(records) if records is not None else self._records_of(node)
        hits: list[tuple[dict[str, Any], str]] = []
        for chunk in _chunks(recs):
            hits += [(r, "record") for r in self.q(self.facts_query(chunk))]
        if node.kind == "party" and self.links_graph:
            hits += [(r, "link") for r in self.q(self._party_facts_query(node.key))]
        attrs = self.fact_attributes(r["f"] for r, _ in hits)
        other_names: dict[str, str] = {}
        party_others = sorted({r["other"] for r, how in hits if how == "link" and r.get("other")})
        for chunk in _chunks(party_others):
            for r in self.q(f"""SELECT ?o ?n WHERE {{ {values_clause('o', chunk)}
                    GRAPH <{GRAPH_CANONICAL}> {{ ?o bg:name ?n }} }}"""):
                other_names[r["o"]] = r["n"]
        items: dict[tuple[str, str], FactItem] = {}
        for h, attribution in hits:
            a = attrs.get(h["f"], {})
            role = local(h.get("role"))
            kind = local(a.get("kind"))
            cat = self._category(a.get("type"), role, kind)
            if cat == "other" and local(a.get("type")) in (None, "Fact"):
                continue
            key = (h["f"], cat)
            vf, vt = _d(a.get("from")), _d(a.get("to"))
            status = a.get("status")
            active = is_valid_on(vf, vt, as_of) and status not in INACTIVE_STATUSES
            it = items.get(key)
            if it is None:
                detail = {k: (float(v) if isinstance(v, Decimal) else v) for k, v in {
                    "kind": kind, "licence_kind": local(a.get("lk")), "licence_number": a.get("num"),
                    "percentage": a.get("pct"), "regulator": a.get("reg"), "amount_aud": a.get("amt"),
                    "ban_type": a.get("bt"), "description": (a.get("desc") or "")[:300] or None,
                    "counterparty_acn": a.get("cpacn"), "role": role,
                }.items() if v is not None}
                other = h.get("other")
                it = FactItem(h["f"], cat, local(a.get("type")) or "?", active, vf, vt, status, detail,
                              a.get("g"), h.get("rec"), other, h.get("oname") or other_names.get(other or ""),
                              attribution)
                items[key] = it
            elif attribution == "link" and it.attribution == "record":
                it.attribution = "record+link"
        return list(items.values())

    # ------------------------------------------------------------------ entity view

    def entity_view(self, key: str, budget: TraversalBudget | None = None, as_of: date | None = None,
                    same_identifier: bool = True) -> EntityView | None:
        """Identifiers, source records, licences, bans, notices, parents, subsidiaries, capped.

        `same_identifier`: also gather records that carry the same ABN/ACN/LEI as the node
        (its records, or the party's canonical identifiers) and that no link gives to another
        party. They are labelled `same_identifier:{scheme}`, never presented as resolver links."""
        t0 = time.perf_counter()
        budget = budget or TraversalBudget()
        as_of = as_of or date.today()
        node = self.resolve(key)
        if node is None:
            return None
        recs = self._records_of(node)
        # "party": a record of the party (link, derived-from, or unique LEI/ABN/ACN equality);
        # "self": the record node itself; "same_identifier:*": widened by exact identifier equality
        joined = {r: ("party" if node.kind == "party" else "self") for r in recs}
        if same_identifier:
            for r, scheme in self.same_identifier_records(recs, node.key if node.kind == "party" else None).items():
                joined.setdefault(r, f"same_identifier:{scheme}")
        view = EntityView(party=node, as_of=as_of, links_graph=self.links_graph)

        # identifiers and source records
        rec_rows: list[dict[str, Any]] = []
        for chunk in _chunks(sorted(joined)):
            rec_rows += self.q(f"""SELECT ?rec ?g ?src ?name ?snap ?p ?v WHERE {{
                {values_clause('rec', chunk)}
                GRAPH ?g {{ ?rec a bg:SourceRecord ; bg:sourceId ?src .
                  OPTIONAL {{ ?rec bg:nameRaw ?name }} OPTIONAL {{ ?rec bg:snapshotDate ?snap }}
                  OPTIONAL {{ ?rec ?p ?v . VALUES ?p {{ bg:abn bg:acn bg:lei bg:arbn bg:arsn bg:nzbn
                     bg:afslNumber bg:aclNumber bg:liquidatorNumber }} }} }} }}""")
        ids: dict[tuple[str, str], set[str]] = defaultdict(set)
        if node.kind == "party":
            for r in self.q(f"""SELECT ?p ?v WHERE {{ GRAPH <{GRAPH_CANONICAL}> {{ {iri_term(node.key)} ?p ?v .
                VALUES ?p {{ bg:abn bg:acn bg:lei bg:arbn bg:arsn bg:nzbn bg:nzCompanyNumber }} }} }}"""):
                ids[(local(r["p"]), r["v"])].add("canonical")
        records: dict[str, dict[str, Any]] = {}
        for r in rec_rows:
            d = records.setdefault(r["rec"], {"record": r["rec"], "source": r.get("src"), "graph": r.get("g"),
                                              "name": r.get("name"), "snapshot": r.get("snap"),
                                              "joined_by": joined.get(r["rec"])})
            if r.get("p"):
                ids[(local(r["p"]), r["v"])].add(d["source"] or "?")
        id_list = [{"scheme": s, "value": v, "seen_in": ",".join(sorted(src))} for (s, v), src in sorted(ids.items())]
        rec_list = sorted(records.values(), key=lambda d: (d["joined_by"] not in ("party", "self"),
                                                          -((d.get("snapshot") or date.min).toordinal()), d["record"]))
        view.totals["identifiers"], view.totals["source_records"] = len(id_list), len(rec_list)
        view.identifiers = id_list[:budget.cap("identifiers")]
        view.source_records = rec_list[:budget.cap("source_records")]
        for k, full, kept in (("identifiers", id_list, view.identifiers), ("source_records", rec_list, view.source_records)):
            if len(full) > len(kept):
                view.truncated_counts[k] = len(full) - len(kept)

        # facts, capped per category
        facts = self.facts_of(node, as_of, sorted(joined))
        for f in facts:
            if f.about_record in joined and joined[f.about_record].startswith("same_identifier"):
                f.attribution = joined[f.about_record]
        by_cat: dict[str, list[FactItem]] = defaultdict(list)
        for f in facts:
            by_cat[f.category].append(f)
        for cat in CATEGORY_ORDER:
            items = sorted(by_cat.get(cat, []), key=FactItem.sort_key)
            if not items:
                continue
            cap = budget.cap(cat)
            view.totals[cat] = len(items)
            view.facts_by_type[cat] = items[:cap]
            if len(items) > cap:
                view.truncated_counts[cat] = len(items) - cap
        view.elapsed_ms = (time.perf_counter() - t0) * 1000
        return view

    def same_identifier_records(self, recs: Sequence[str], party: str | None = None) -> dict[str, str]:
        """Records sharing an ABN, ACN or LEI with any of `recs` or with the canonical
        identifiers of `party` (exact identifier equality). Records that a link attributes to
        a DIFFERENT party are left out: identifier equality never overrides a resolver decision."""
        out: dict[str, str] = {}
        for chunk in _chunks(list(recs)):
            for r in self.q(f"""SELECT DISTINCT ?o ?scheme WHERE {{
                {values_clause('x', chunk)} VALUES ?scheme {{ bg:abn bg:acn bg:lei }}
                ?x ?scheme ?v . ?o ?scheme ?v . ?o a bg:SourceRecord . FILTER(?o != ?x) }}"""):
                if r["o"] not in recs:
                    out.setdefault(r["o"], local(r["scheme"]))
        if party:
            for r in self.q(f"""SELECT DISTINCT ?o ?scheme WHERE {{ VALUES ?scheme {{ bg:abn bg:acn bg:lei }}
                    GRAPH <{GRAPH_CANONICAL}> {{ {iri_term(party)} ?scheme ?v }}
                    ?o ?scheme ?v ; a bg:SourceRecord . }}"""):
                if r["o"] not in recs:
                    out.setdefault(r["o"], local(r["scheme"]))
        if out:
            owners = self.nodes_for_records(out)
            out = {r: sch for r, sch in out.items()
                   if owners[r].kind == "record" or (party is not None and owners[r].key == party)}
        return out

    # ------------------------------------------------------------------ N-hop neighbourhood

    def relations_of(self, node: NodeRef, as_of: date | None) -> list[tuple[dict[str, Any], NodeRef]]:
        """Party-to-party relationships of a node: ownership (both ways, DIRECT and shareholding,
        never the derived ULTIMATE edge), trusteeship (by link roles, or record-level by the
        trustee ACN), affiliations and any other two-party relationship whose roles are marked
        'expand' in the ontology. Phase 1 finds (fact, other end); phase 2 reads attributes."""
        recs = self._records_of(node)
        hops: list[tuple[str, str, str, str]] = []  # (fact, other record or party IRI, direction, level)
        for chunk in _chunks(recs):
            for r in self.q(f"""SELECT ?f ?other ?dir WHERE {{
              {values_clause('x', chunk)}
              {{ ?f bg:aboutRecord ?x ; bg:counterpartyRecord ?other . BIND("out" AS ?dir) }}
              UNION {{ ?f bg:counterpartyRecord ?x ; bg:aboutRecord ?other . BIND("in" AS ?dir) }}
              UNION {{ ?f bg:aboutRecord ?x ; bg:counterpartyAcn ?acn . ?other bg:acn ?acn ; a bg:SourceRecord .
                       BIND("out" AS ?dir) }}
              UNION {{ ?x bg:acn ?acn . ?f bg:counterpartyAcn ?acn ; bg:aboutRecord ?other . BIND("in" AS ?dir) }}
            }}"""):
                hops.append((r["f"], r["other"], r["dir"], "record"))
        if node.kind == "party" and self.links_graph:
            two_party = [r for r in self.roles() if r not in SINGLE_PARTY_ROLES]
            roles = " ".join(f"bg:{r}" for r in two_party)
            for r in self.q(f"""SELECT ?f ?r1 ?other WHERE {{
              VALUES ?r1 {{ {roles} }} VALUES ?r2 {{ {roles} }}
              {self._links(f'?f ?r1 {iri_term(node.key)} ; ?r2 ?other . FILTER(?other != {iri_term(node.key)})')}
            }}"""):
                hops.append((r["f"], r["other"], "out" if local(r["r1"]) in ("owned", "trust", "member") else "in",
                             "party"))
        attrs = self.fact_attributes(f for f, _, _, _ in hops)
        on = as_of or date.today()
        infos: list[tuple[dict[str, Any], str]] = []
        for f, other, direction, level in hops:
            a = attrs.get(f, {})
            kind = local(a.get("kind"))
            if kind == "IS_ULTIMATELY_CONSOLIDATED_BY":
                continue
            vf, vt = _d(a.get("from")), _d(a.get("to"))
            if as_of and not is_valid_on(vf, vt, on):
                continue
            infos.append(({"fact": f, "relation": local(a.get("type")) or "Relationship", "kind": kind,
                           "direction": direction, "valid_from": vf, "valid_to": vt,
                           "source_graph": a.get("g"), "level": level}, other))
        nodes = self.nodes_for_records([o for _, o in infos if o.startswith("urn:src:")])
        out: list[tuple[dict[str, Any], NodeRef]] = []
        seen: set[tuple[str, str]] = set()
        for info, other in infos:
            tgt = nodes.get(other) if other.startswith("urn:src:") else (
                self._node_cache.get(other) or self._party(other) or NodeRef(other, "party"))
            if tgt is None or tgt.key == node.key or (info["fact"], tgt.key) in seen:
                continue
            if not other.startswith("urn:src:"):
                self._node_cache[other] = tgt
            seen.add((info["fact"], tgt.key))
            out.append((info, tgt))
        return out

    def within_hops(self, key: str, hops: int = 2, budget: TraversalBudget | None = None,
                    as_of: date | None = None) -> Neighbourhood:
        t0 = time.perf_counter()
        q0 = self.n_queries
        budget = budget or TraversalBudget()
        start = self.resolve(key)
        if start is None:
            return Neighbourhood(NodeRef(key, "record"), hops)
        hood = Neighbourhood(start, hops)
        seen: dict[str, Neighbour] = {start.key: Neighbour(start, 0, [])}
        frontier = [seen[start.key]]
        fan = budget.cap("neighbours_per_node", 50)
        dropped: Counter[str] = Counter()
        for depth in range(1, hops + 1):
            nxt: list[Neighbour] = []
            for cur in frontier:
                rels = self.relations_of(cur.node, as_of)
                rels.sort(key=lambda rn: (
                    0 if is_valid_on(rn[0]["valid_from"], rn[0]["valid_to"], as_of or date.today()) else 1,
                    RELATION_PRIORITY.get(rn[0]["relation"], 9),
                    -((rn[0]["valid_from"] or date.min).toordinal()), rn[1].key))
                if len(rels) > fan:
                    dropped["neighbours_per_node"] += len(rels) - fan
                    rels = rels[:fan]
                for info, tgt in rels:
                    if tgt.key in seen:
                        continue
                    if len(seen) - 1 >= budget.max_nodes:
                        dropped["max_nodes"] += 1
                        continue
                    hop = {**info, "from": cur.node.key, "to": tgt.key, "to_name": tgt.name}
                    nb = Neighbour(tgt, depth, cur.via + [hop])
                    seen[tgt.key] = nb
                    nxt.append(nb)
            frontier = nxt
        hood.neighbours = sorted((n for n in seen.values() if n.distance > 0), key=lambda n: (n.distance, n.node.key))
        hood.truncated_counts = dict(dropped)
        hood.queries = self.n_queries - q0
        hood.elapsed_ms = (time.perf_counter() - t0) * 1000
        return hood

    def flagged_seeds(self, flag: str = "ban", as_of: date | None = None, active_only: bool = False) -> list[NodeRef]:
        """Nodes carrying a regulatory flag: 'ban' (bg:Ban), 'notice' (bg:InfringementNotice)
        or 'suspended' (licence with a suspended status). Record-level facts plus link roles."""
        cls = {"ban": "bg:Ban", "notice": "bg:InfringementNotice", "suspended": "bg:Licence"}[flag]
        extra = 'FILTER(?status IN ("suspended", "SUSP"))' if flag == "suspended" else ""
        rows = self.q(f"""SELECT DISTINCT ?rec ?from ?to WHERE {{ ?f a {cls} ; bg:aboutRecord ?rec .
            OPTIONAL {{ ?f bg:licenceStatus ?status }} OPTIONAL {{ ?f bg:validFrom ?from }}
            OPTIONAL {{ ?f bg:validTo ?to }} {extra} }}""")
        if active_only and as_of:
            rows = [r for r in rows if is_valid_on(_d(r.get("from")), _d(r.get("to")), as_of)]
        nodes = self.nodes_for_records({r["rec"] for r in rows})
        return sorted({n.key: n for n in nodes.values()}.values(), key=lambda n: n.key)

    def near_flagged(self, flag: str = "ban", hops: int = 2, budget: TraversalBudget | None = None,
                     as_of: date | None = None, same_identifier: bool = True) -> dict[str, Any]:
        """Every party within `hops` relationship hops of a flagged (banned / noticed /
        suspended) party. Record-level seeds are first widened to records with the same
        ABN/ACN/LEI (labelled as such), since without a links graph that is the only bridge
        from a ban record to the GLEIF and licence records of the same company."""
        t0 = time.perf_counter()
        q0 = self.n_queries
        budget = budget or TraversalBudget()
        seeds = self.flagged_seeds(flag, as_of)
        rows: list[dict[str, Any]] = []
        bridged = 0
        for seed in seeds:
            starts = [seed]
            if same_identifier:
                extra = self.same_identifier_records(list(seed.records),
                                                     seed.key if seed.kind == "party" else None)
                bridged += len(extra)
                starts += [n for n in self.nodes_for_records(extra).values() if n.key != seed.key]
            for s in starts:
                hood = self.within_hops(s.key, hops, budget, as_of)
                for nb in hood.neighbours:
                    rows.append({"seed": seed.key, "seed_name": seed.name, "via_identity": s.key != seed.key,
                                 "node": nb.node.key, "name": nb.node.name, "kind": nb.node.kind,
                                 "distance": nb.distance,
                                 "path": " | ".join(f"{h['relation']}:{h.get('kind') or ''} {h['from']}->{h['to']}"
                                                    for h in nb.via),
                                 "truncated": hood.truncated_counts})
        return {"flag": flag, "hops": hops, "seeds": len(seeds), "identity_bridged_records": bridged,
                "rows": sorted(rows, key=lambda r: (r["distance"], r["seed"], r["node"])),
                "queries": self.n_queries - q0, "elapsed_ms": (time.perf_counter() - t0) * 1000}

    # ------------------------------------------------------------------ group exposure

    def group_exposure(self, as_of: date | None = None, max_depth: int = 10,
                       recent_cancel_window_days: int = 92,
                       home_countries: Sequence[str] = ("AU", "NZ")) -> dict[str, Any]:
        """The graph-only question: which licensed entities sit in the same corporate group
        (same bounded ultimate parent over DIRECT consolidation) as an entity carrying a
        regulatory flag (ban, ACCC notice, suspended licence, licence CANCELLED_OR_LAPSED in
        the window)? Also returns licence concentration per group and the licensees whose
        ultimate parent is registered outside `home_countries` (foreign-controlled licensees,
        with the number of hops to the controller).

        Group membership needs a variable-depth walk up to the top and back down; the
        licences and flags sit on other entities, in other sources, reached through links
        (or same-identifier equality in record mode). No single table holds the group."""
        t0 = time.perf_counter()
        q0 = self.n_queries
        current_only = as_of is None
        as_of = as_of or date.today()
        idx = self.ownership_index(as_of if not current_only else None)
        groups = idx.groups(max_depth)
        members = sorted({m for g in groups.values() for m in g["members"]})
        member_nodes = {k: idx.nodes[k] for k in members}
        # licences and flags on members: record level by same ABN/ACN (or the records themselves),
        # party level by link roles
        rec_to_member: dict[str, str] = {}
        for k, n in member_nodes.items():
            for r in n.records:
                rec_to_member[r] = k
        member_recs = sorted(rec_to_member)
        lic_rows: list[dict[str, Any]] = []
        for chunk in _chunks(member_recs):
            lic_rows += self.q(f"""SELECT DISTINCT ?m ?f ?type ?lk ?num ?status ?from ?to ?how WHERE {{
                {values_clause('m', chunk)}
                {{ ?f bg:aboutRecord ?m . BIND("record" AS ?how) }}
                UNION {{ ?m bg:acn ?v . ?r bg:acn ?v . ?r a bg:SourceRecord . ?f bg:aboutRecord ?r .
                         FILTER(?r != ?m) BIND("same_identifier:acn" AS ?how) }}
                UNION {{ ?m bg:abn ?w . ?r bg:abn ?w . ?r a bg:SourceRecord . ?f bg:aboutRecord ?r .
                         FILTER(?r != ?m) BIND("same_identifier:abn" AS ?how) }}
                ?f a ?type . VALUES ?type {{ bg:Licence bg:Ban bg:InfringementNotice }}
                OPTIONAL {{ ?f bg:licenceKind ?lk }} OPTIONAL {{ ?f bg:licenceNumber ?num }}
                OPTIONAL {{ ?f bg:licenceStatus ?status }}
                OPTIONAL {{ ?f bg:validFrom ?from }} OPTIONAL {{ ?f bg:validTo ?to }} }}""")
        party_keys = [k for k, n in member_nodes.items() if n.kind == "party"]
        if party_keys and self.links_graph:
            for chunk in _chunks(party_keys):
                for r in self.q(f"""SELECT DISTINCT ?m ?f ?type ?lk ?num ?status ?from ?to WHERE {{
                    {values_clause('m', chunk)} VALUES ?role {{ bg:licensee bg:bannedParty bg:noticeRecipient }}
                    {self._links('?f ?role ?m .')}
                    ?f a ?type . OPTIONAL {{ ?f bg:licenceKind ?lk }} OPTIONAL {{ ?f bg:licenceNumber ?num }}
                    OPTIONAL {{ ?f bg:licenceStatus ?status }}
                    OPTIONAL {{ ?f bg:validFrom ?from }} OPTIONAL {{ ?f bg:validTo ?to }} }}"""):
                    r["how"] = "link"
                    lic_rows.append(r)
        per_member: dict[str, list[dict[str, Any]]] = defaultdict(list)
        seen_f: set[tuple[str, str]] = set()
        lic_rows.sort(key=lambda r: {"link": 0, "record": 1}.get(r.get("how"), 2))  # strongest attribution wins
        for r in lic_rows:
            m = rec_to_member.get(r["m"], r["m"])
            if (m, r["f"]) in seen_f:
                continue
            seen_f.add((m, r["f"]))
            t = local(r.get("type"))
            status = r.get("status")
            flag = None
            if t == "Ban":
                flag = "ban" + ("" if is_valid_on(_d(r.get("from")), _d(r.get("to")), as_of) else "_expired")
            elif t == "InfringementNotice":
                flag = "notice"
            elif status in SUSPENDED_STATUSES:
                flag = "licence_suspended"
            per_member[m].append({"fact": r["f"], "type": t, "licence_kind": local(r.get("lk")),
                                  "licence_number": r.get("num"), "status": status, "flag": flag,
                                  "how": r.get("how")})
        # licence events from DuckDB (CANCELLED_OR_LAPSED in the window), joined by holder ABN/ACN
        for m, ev in self._cancel_events(member_nodes, as_of, recent_cancel_window_days):
            per_member[m].append(ev)

        top_country: dict[str, str] = {}
        tops_recs = {r: top for top in groups for r in idx.nodes[top].records}
        for chunk in _chunks(sorted(tops_recs)):
            for r in self.q(f"""SELECT ?r ?c WHERE {{ {values_clause('r', chunk)} ?r bg:country ?c }}"""):
                top_country[tops_recs[r["r"]]] = r["c"]
        out_groups = []
        exposures = []
        foreign = []
        for top, g in groups.items():
            lic = {m: [f for f in per_member.get(m, []) if f["type"] == "Licence"] for m in g["members"]}
            flagged = {m: [f for f in per_member.get(m, []) if f.get("flag")] for m in g["members"]}
            n_lic = sum(len(v) for v in lic.values())
            licensed_members = [m for m, v in lic.items() if v]
            flagged_members = [m for m, v in flagged.items() if v]
            country = top_country.get(top)
            if country and country not in home_countries:
                for lm in licensed_members:
                    if lm == top:
                        continue
                    foreign.append({"licensee": lm, "licensee_name": idx.nodes[lm].name,
                                    "licences": sorted({f"{f['licence_kind']} {f['licence_number']}" for f in lic[lm]}),
                                    "depth": g["depth"].get(lm), "ultimate_parent": top,
                                    "ultimate_parent_name": idx.nodes[top].name, "country": country,
                                    "attribution": sorted({f["how"] for f in lic[lm]})})
            out_groups.append({"top": top, "top_name": idx.nodes[top].name, "top_country": country,
                               "members": len(g["members"]),
                               "max_depth": g["max_depth"], "licensed_members": len(licensed_members),
                               "licences": n_lic, "flagged_members": len(flagged_members)})
            for fm in flagged_members:
                for lm in licensed_members:
                    if lm == fm:
                        continue
                    exposures.append({
                        "group_top": top, "group_top_name": idx.nodes[top].name,
                        "flagged": fm, "flagged_name": idx.nodes[fm].name,
                        "flags": sorted({f["flag"] for f in flagged[fm]}),
                        "licensee": lm, "licensee_name": idx.nodes[lm].name,
                        "licences": sorted({f"{f['licence_kind']} {f['licence_number']}" for f in lic[lm]}),
                        "attribution": sorted({f["how"] for f in lic[lm] + flagged[fm]}),
                    })
        out_groups.sort(key=lambda g: (-g["licences"], -g["members"], g["top"]))
        foreign.sort(key=lambda r: (-(r["depth"] or 0), r["country"], r["licensee_name"] or ""))
        return {"as_of": as_of, "groups": out_groups, "exposures": exposures, "foreign_controlled": foreign,
                "unresolved_tops": idx.unresolved, "members_scanned": len(members),
                "queries": self.n_queries - q0, "elapsed_ms": (time.perf_counter() - t0) * 1000,
                "links_graph": self.links_graph}

    def _cancel_events(self, member_nodes: dict[str, NodeRef], as_of: date,
                       window_days: int) -> list[tuple[str, dict[str, Any]]]:
        con = getattr(self.store, "con", self.store)
        if con is None:
            return []
        try:
            has = con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'licence_event'").fetchone()[0]
        except Exception:  # noqa: BLE001
            return []
        if not has:
            return []
        by_id: dict[str, str] = {}
        recs = sorted({r for n in member_nodes.values() for r in n.records})
        for chunk in _chunks(recs):
            for r in self.q(f"""SELECT ?m ?v WHERE {{ {values_clause('m', chunk)} ?m ?p ?v .
                    VALUES ?p {{ bg:abn bg:acn }} }}"""):
                by_id[r["v"]] = r["m"]
        rec_to_member = {r: k for k, n in member_nodes.items() for r in n.records}
        rows = con.execute(
            """SELECT licence_kind, licence_no, event_date, observed_after, holder_abn_before, holder_acn_before
               FROM licence_event WHERE event_type = 'CANCELLED_OR_LAPSED'
                 AND event_date <= ? AND event_date >= ? - (? * INTERVAL 1 DAY)""",
            [as_of, as_of, window_days]).fetchall()
        out = []
        for kind, no, ed, oa, abn, acn in rows:
            rec = by_id.get(abn or "") or by_id.get(acn or "")
            if rec and rec in rec_to_member:
                out.append((rec_to_member[rec], {"fact": f"licence_event:{kind}:{no}:{ed}", "type": "LicenceEvent",
                                                 "licence_kind": kind, "licence_number": no, "status": "CANCELLED_OR_LAPSED",
                                                 "flag": "licence_cancelled_or_lapsed", "event_date": ed,
                                                 "observed_after": oa, "how": "event_holder_identifier"}))
        return out


def compare_with_gleif(chain: OwnershipChain) -> str:
    if not chain.gleif_ultimate:
        return "no_gleif_ultimate"
    g = {n.key for n in chain.gleif_ultimate}
    if chain.status in ("TOP_REACHED", "NO_PARENT") and chain.top.key in g:
        return "agree"
    on_chain = {n.key for n in chain.nodes}
    if g & on_chain:
        return "disagree_on_chain"  # GLEIF's ultimate is on our chain but not where we stopped
    return "disagree_off_chain"


# --------------------------------------------------------------------------- bulk index


class OwnershipIndex:
    """All direct ownership edges (and GLEIF ULTIMATE edges) loaded with a handful of
    queries, so the same bounded walk can run over every entity for reports."""

    def __init__(self) -> None:
        self.nodes: dict[str, NodeRef] = {}
        self.parents: dict[str, list[tuple[OwnershipEdge, NodeRef]]] = defaultdict(list)
        self.ultimate: dict[str, set[str]] = defaultdict(set)
        self.unresolved: dict[str, int] = {}
        self.load_ms = 0.0
        self.queries = 0

    @classmethod
    def load(cls, svc: TraversalService, as_of: date | None, kinds: Sequence[str]) -> OwnershipIndex:
        t0 = time.perf_counter()
        q0 = svc.n_queries
        current_only = as_of is None
        as_of = as_of or date.today()
        idx = cls()
        status = 'FILTER (!BOUND(?status) || ?status != "INACTIVE")' if current_only else ""
        rows = svc.q(f"""SELECT ?f ?g ?kind ?child ?parent ?pct ?from ?to ?status ?src WHERE {{
            {values_clause('kind', list(kinds) + [ULTIMATE])}
            GRAPH ?g {{ ?f a bg:Ownership ; bg:relationshipKind ?kind ; bg:aboutRecord ?child ;
                        bg:counterpartyRecord ?parent .
              OPTIONAL {{ ?f bg:ownershipPercentage ?pct }} OPTIONAL {{ ?f bg:validFrom ?from }}
              OPTIONAL {{ ?f bg:validTo ?to }} OPTIONAL {{ ?f bg:relationshipStatus ?status }}
              OPTIONAL {{ ?f prov:wasDerivedFrom ?src }} }}
            {validity_filter(as_of)} {status} }}""")
        recs = {r["child"] for r in rows} | {r["parent"] for r in rows}
        rec_nodes = svc.nodes_for_records(recs)
        for n in rec_nodes.values():
            prev = idx.nodes.get(n.key)
            if prev is None:
                idx.nodes[n.key] = n
            elif n.kind == "party":  # merge the records of a party seen through several LEIs
                idx.nodes[n.key] = NodeRef(**{**asdict(prev), "records": tuple(sorted(set(prev.records) | set(n.records)))})
        seen: set[tuple[str, str]] = set()
        for r in rows:
            c, p = rec_nodes[r["child"]], rec_nodes[r["parent"]]
            if r["kind"] == ULTIMATE:
                idx.ultimate[c.key].add(p.key)
                continue
            if (c.key, r["f"]) in seen:
                continue
            seen.add((c.key, r["f"]))
            e = OwnershipEdge(r["f"], local(r["kind"]), c.key, p.key, _num(r.get("pct")), _d(r.get("from")),
                              _d(r.get("to")), r.get("status"), r.get("g"),
                              [r["src"]] if r.get("src") else [], "record")
            idx.parents[c.key].append((e, idx.nodes[p.key]))
        if svc.links_graph:  # party-level ownership not backed by GLEIF records (e.g. shareholdings)
            for r in svc.q(f"""SELECT ?f ?c ?p ?kind ?pct ?from ?to WHERE {{
                    {svc._links('?f bg:owned ?c ; bg:owner ?p .')}
                    OPTIONAL {{ ?f bg:relationshipKind ?kind }} OPTIONAL {{ ?f bg:ownershipPercentage ?pct }}
                    OPTIONAL {{ ?f bg:validFrom ?from }} OPTIONAL {{ ?f bg:validTo ?to }}
                    {validity_filter(as_of)} }}"""):
                if r.get("kind") and r["kind"] not in kinds:
                    continue
                if any(e.fact == r["f"] for e, _ in idx.parents.get(r["c"], [])):
                    continue
                for k in (r["c"], r["p"]):
                    idx.nodes.setdefault(k, NodeRef(k, "party"))
                idx.parents[r["c"]].append((OwnershipEdge(r["f"], local(r.get("kind")), r["c"], r["p"],
                                                          _num(r.get("pct")), _d(r.get("from")), _d(r.get("to")),
                                                          None, svc.links_graph, [], "party"), idx.nodes[r["p"]]))
        idx.as_of, idx.current_only = as_of, current_only
        idx.queries = svc.n_queries - q0
        idx.load_ms = (time.perf_counter() - t0) * 1000
        return idx

    def walk(self, key: str, max_depth: int = 10) -> OwnershipChain:
        chain = walk_chain(self.nodes[key], lambda n: list(self.parents.get(n.key, [])), max_depth,
                           getattr(self, "as_of", date.today()))
        chain.gleif_ultimate = [self.nodes[k] for k in sorted(self.ultimate.get(key, ()))]
        chain.gleif_check = compare_with_gleif(chain)
        return chain

    def children(self) -> list[str]:
        return sorted(k for k, v in self.parents.items() if v)

    def all_chains(self, max_depth: int = 10) -> list[OwnershipChain]:
        return [self.walk(k, max_depth) for k in self.children()]

    def groups(self, max_depth: int = 10) -> dict[str, dict[str, Any]]:
        """top -> members (every node whose bounded chain reaches that top). Chains that end
        in a cycle, a truncation or an ambiguity are not assigned to a group (counted in
        `unresolved`)."""
        groups: dict[str, dict[str, Any]] = {}
        unresolved: Counter[str] = Counter()
        for k in self.children():
            ch = self.walk(k, max_depth)
            if ch.status != "TOP_REACHED":
                unresolved[ch.status] += 1
                continue
            g = groups.setdefault(ch.top.key, {"members": {ch.top.key}, "max_depth": 0, "depth": {ch.top.key: 0}})
            g["members"].add(k)
            g["depth"][k] = ch.depth
            g["max_depth"] = max(g["max_depth"], ch.depth)
        self.unresolved = dict(unresolved)
        return groups
