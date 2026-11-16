"""RdfExporter: DuckDB rows -> N-Triples / N-Quads, one file per named graph.

Streams straight from SQL cursors and writes pre-formatted N-Triples lines;
no rdflib graph is built for data graphs (only the small ontology graph goes
through rdflib). Output is deterministic: rows are read in a fixed SQL order
(by record id / canonical key / link key), predicates are written in a fixed
order per subject, and multi-valued objects are sorted, so exporting the same
DuckDB state twice gives byte-identical files.

Graph kinds (PLAN.md, named graph layout):

* ``source``    ``urn:graph:source:{source}:{snapshot_date}``: the snapshot node,
                every record seen in that snapshot (latest version per record id),
                and the facts the records assert (Licence for asic_afsl /
                asic_credit / asic_liquidator, Ban for asic_banned_org, Ownership
                for GLEIF L2 consolidation edges). Facts point at RECORDS
                (bg:aboutRecord / bg:counterpartyRecord), never at parties.
* ``canonical`` ``urn:graph:canonical``: parties from ``party_canonical`` plus the
                ``identifier`` and ``alias`` tables (each optional).
* ``links``     ``urn:graph:links:{matcher_version}``: bg:Link and bg:Abstention
                nodes plus the party-level role shortcuts (bg:licensee,
                bg:bannedParty, bg:owned, bg:owner) derived from the links.
* ``ontology``  ``urn:graph:ontology``: ontology/schema.ttl.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from bizgraph.rdf.vocab import (
    ABSTAIN_REASONS,
    GRAPH_CANONICAL,
    GRAPH_ONTOLOGY,
    MATCH_TYPES,
    RELATIONSHIP_KINDS,
    C,
    IriFactory,
    P,
    bg,
    iri,
    lit,
    lit_date,
    lit_decimal,
    lit_integer,
)

LICENCE_SOURCES = {"asic_afsl": C.AFSL, "asic_credit": C.ACL, "asic_liquidator": C.REGISTERED_LIQUIDATOR}
BAN_SOURCES = frozenset({"asic_banned_org", "asic_banned"})
OWNERSHIP_SOURCE = "gleif_l2"
FACT_SOURCES = frozenset({*LICENCE_SOURCES, *BAN_SOURCES, OWNERSHIP_SOURCE})
LEI_RECORD_SOURCE = "gleif_l1"  # Ownership facts point at the L1 records of both ends
PARTY_TYPES = {"organisation": C.Organisation, "person": C.Person}
_ID_SCHEMES = ("abn", "acn", "arbn", "lei")

_BATCH = 20_000


@dataclass(frozen=True)
class NamedGraph:
    kind: str  # source | canonical | links | ontology
    iri: str
    source: str | None = None
    snapshot_date: date | None = None
    matcher_version: str | None = None

    @property
    def file_stem(self) -> str:
        if self.kind == "source":
            return f"source__{self.source}__{self.snapshot_date.isoformat()}"
        if self.kind == "links":
            return f"links__{_fs_safe(self.matcher_version or '')}"
        return self.kind

    @staticmethod
    def canonical() -> NamedGraph:
        return NamedGraph("canonical", GRAPH_CANONICAL)

    @staticmethod
    def ontology() -> NamedGraph:
        return NamedGraph("ontology", GRAPH_ONTOLOGY)

    @staticmethod
    def links(matcher_version: str) -> NamedGraph:
        return NamedGraph("links", IriFactory.links_graph(matcher_version), matcher_version=matcher_version)

    @staticmethod
    def source_snapshot(source: str, snapshot_date: date) -> NamedGraph:
        return NamedGraph("source", IriFactory.source_graph(source, snapshot_date), source, snapshot_date)


def _fs_safe(s: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in s)


@dataclass
class ExportResult:
    graph: NamedGraph
    path: Path
    triples: int
    seconds: float
    counts: dict[str, int] = field(default_factory=dict)  # e.g. records, facts, parties


def _json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


class RdfExporter:
    """Export named graphs from a DuckDB connection (read-only use is enough)."""

    def __init__(self, con: duckdb.DuckDBPyConnection | Any, ontology_dir: Path | None = None) -> None:
        self.con = getattr(con, "con", con)  # accept a DuckDBStore too
        if ontology_dir is None:
            from bizgraph.config import get_settings

            ontology_dir = get_settings().ontology_dir
        self.ontology_dir = Path(ontology_dir)
        self.iris = IriFactory()

    # ------------------------------------------------------------------ catalogue

    def _has_table(self, name: str) -> bool:
        return bool(
            self.con.execute(
                "SELECT count(*) FROM duckdb_tables() WHERE table_name = ? AND schema_name = 'main'", [name]
            ).fetchall()[0][0]
        )

    def _columns(self, table: str) -> set[str]:
        if not self._has_table(table):
            return set()
        return {r[0] for r in self.con.execute(f"DESCRIBE {table}").fetchall()}

    def latest_snapshot(self, source: str) -> date | None:
        row = self.con.execute(
            "SELECT max(last_seen_snapshot) FROM source_record WHERE source = ?", [source]
        ).fetchall()
        return row[0][0] if row else None

    def source_graphs(self, source: str | None = None) -> list[NamedGraph]:
        """One graph per source at its latest snapshot."""
        sql = "SELECT source, max(last_seen_snapshot) FROM source_record"
        params: list[Any] = []
        if source:
            sql += " WHERE source = ?"
            params.append(source)
        rows = self.con.execute(sql + " GROUP BY source ORDER BY source", params).fetchall()
        return [NamedGraph.source_snapshot(s, d) for s, d in rows if d is not None]

    def matcher_versions(self) -> list[str]:
        parts = []
        if self._has_table("link"):
            parts.append("SELECT DISTINCT matcher_version FROM link")
        if self._has_table("abstention"):
            parts.append("SELECT DISTINCT matcher_version FROM abstention")
        if not parts:
            return []
        rows = self.con.execute(" UNION ".join(parts) + " ORDER BY 1").fetchall()
        return [r[0] for r in rows if r[0]]

    def graphs(self, kinds: Iterable[str] | None = None, source: str | None = None,
               matcher_version: str | None = None) -> list[NamedGraph]:
        kinds = set(kinds or ("ontology", "source", "canonical", "links"))
        out: list[NamedGraph] = []
        if "ontology" in kinds:
            out.append(NamedGraph.ontology())
        if "source" in kinds:
            out.extend(self.source_graphs(source))
        if "canonical" in kinds and self._has_table("party_canonical"):
            out.append(NamedGraph.canonical())
        if "links" in kinds:
            versions = [matcher_version] if matcher_version else self.matcher_versions()
            out.extend(NamedGraph.links(v) for v in versions)
        return out

    # ------------------------------------------------------------------ export

    def export(self, graph: NamedGraph, out: Path, fmt: str | None = None) -> ExportResult:
        """Write one graph. `out` is a directory (file named after the graph) or a file path.
        fmt: 'nt' (default) or 'nq' (each line carries the graph IRI, for the bulk loader)."""
        out = Path(out)
        if out.suffix.lower() in (".nt", ".nq"):
            path = out
            fmt = fmt or out.suffix.lower()[1:]
        else:
            fmt = fmt or "nt"
            path = out / f"{graph.file_stem}.{fmt}"
        path.parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        counts: dict[str, int] = {}
        end = f" <{graph.iri}> .\n" if fmt == "nq" else " .\n"
        tmp = path.with_name(path.name + ".tmp")
        n = 0
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            buf: list[str] = []
            for t in self.triples(graph, counts):
                buf.append(t)
                if len(buf) >= _BATCH:
                    fh.write(end.join(buf) + end)
                    n += len(buf)
                    buf.clear()
            if buf:
                fh.write(end.join(buf) + end)
                n += len(buf)
        os.replace(tmp, path)
        return ExportResult(graph, path, n, time.perf_counter() - started, counts)

    def export_all(self, out_dir: Path, graphs: Iterable[NamedGraph] | None = None,
                   fmt: str = "nt") -> list[ExportResult]:
        return [self.export(g, out_dir, fmt) for g in (graphs if graphs is not None else self.graphs())]

    def triples(self, graph: NamedGraph, counts: dict[str, int] | None = None) -> Iterator[str]:
        """Yield 's p o' strings (no terminating ' .')."""
        counts = counts if counts is not None else {}
        if graph.kind == "source":
            yield from self._source_triples(graph.source, graph.snapshot_date, counts)
        elif graph.kind == "canonical":
            yield from self._canonical_triples(counts)
        elif graph.kind == "links":
            yield from self._links_triples(graph.matcher_version, counts)
        elif graph.kind == "ontology":
            yield from self._ontology_triples(counts)
        else:
            raise ValueError(f"unknown graph kind {graph.kind!r}")

    # ------------------------------------------------------------------ helpers

    def _stream(self, sql: str, params: list[Any] | None = None) -> Iterator[tuple[Any, ...]]:
        cur = self.con.cursor()
        try:
            cur.execute(sql, params or [])
            while rows := cur.fetchmany(_BATCH):
                yield from rows
        finally:
            cur.close()

    # ------------------------------------------------------------------ source graphs

    def _source_triples(self, source: str, snapshot: date | None, counts: dict[str, int]) -> Iterator[str]:
        if snapshot is None:
            snapshot = self.latest_snapshot(source)
            if snapshot is None:
                return
        g_iri = IriFactory.source_graph(source, snapshot)
        snap = self.con.execute(
            """SELECT file_hash, records_in FROM source_snapshot
               WHERE source = ? AND snapshot_date = ?
               ORDER BY loaded_at DESC, file_hash LIMIT 1""",
            [source, snapshot],
        ).fetchall()
        if snap:
            s = iri(g_iri)
            yield f"{s} {P.type} {C.SourceSnapshot}"
            yield f"{s} {P.sourceId} {lit(source)}"
            yield f"{s} {P.snapshotDate} {lit_date(snapshot)}"
            if snap[0][0]:
                yield f"{s} {P.fileHash} {lit(snap[0][0])}"
            if snap[0][1] is not None:
                yield f"{s} {P.recordsIn} {lit_integer(snap[0][1])}"

        want_payload = source in FACT_SOURCES
        sql = f"""
            SELECT record_id, content_hash, first_seen_snapshot, name_raw, name_norm, party_type,
                   abn, acn, lei, identifiers, {'payload' if want_payload else 'NULL'}
            FROM source_record
            WHERE source = ? AND first_seen_snapshot <= ? AND last_seen_snapshot >= ?
            QUALIFY row_number() OVER (
                PARTITION BY record_id
                ORDER BY last_seen_snapshot DESC, load_seq DESC NULLS LAST, content_hash) = 1
            ORDER BY record_id"""
        src_lit = lit(source)
        records = facts = 0
        for rid, chash, first_seen, name_raw, name_norm, ptype, abn, acn, lei, ids, payload in self._stream(
            sql, [source, snapshot, snapshot]
        ):
            records += 1
            r_iri = IriFactory.source_record(source, rid)
            s = iri(r_iri)
            yield f"{s} {P.type} {C.SourceRecord}"
            yield f"{s} {P.sourceId} {src_lit}"
            yield f"{s} {P.recordId} {lit(rid)}"
            d = lit_date(first_seen)
            if d:
                yield f"{s} {P.snapshotDate} {d}"
            if chash:
                yield f"{s} {P.contentHash} {lit(chash)}"
            if name_raw:
                yield f"{s} {P.nameRaw} {lit(name_raw)}"
            if name_norm:
                yield f"{s} {P.nameNorm} {lit(name_norm)}"
            if ptype:
                yield f"{s} {P.partyTypeHint} {lit(ptype)}"
            if abn:
                yield f"{s} {P.abn} {lit(abn)}"
            if acn:
                yield f"{s} {P.acn} {lit(acn)}"
            if ids and "arbn" in ids:
                for arbn in sorted({v for sch, v in (_json(ids) or []) if sch == "arbn"}):
                    yield f"{s} {P.arbn} {lit(arbn)}"
            if lei:
                yield f"{s} {P.lei} {lit(lei)}"
            if want_payload:
                for t in self._fact_triples(source, rid, s, _json(payload) or {}):
                    if t is _FACT_MARK:
                        facts += 1
                    else:
                        yield t
        counts["records"] = counts.get("records", 0) + records
        counts["facts"] = counts.get("facts", 0) + facts

    def _fact_triples(self, source: str, rid: str, rec: str, p: dict[str, Any]) -> Iterator[Any]:
        if source in LICENCE_SOURCES:
            yield from self._licence(source, rid, rec, p)
        elif source in BAN_SOURCES:
            yield from self._ban(source, rid, rec, p)
        elif source == OWNERSHIP_SOURCE:
            yield from self._ownership(source, rid, rec, p)

    @staticmethod
    def _validity(f: str, start: Any, end: Any) -> Iterator[str]:
        a, b = lit_date(start), lit_date(end)
        if a:
            yield f"{f} {P.validFrom} {a}"
        if b:
            yield f"{f} {P.validTo} {b}"

    def _licence(self, source: str, rid: str, rec: str, p: dict[str, Any]) -> Iterator[Any]:
        if source == "asic_liquidator":
            number = (p.get("liquidator_number") or rid or "").lstrip("0")
            start, end = p.get("registration_start"), None
        else:
            number = (p.get("licence_number") or rid or "").lstrip("0")
            start, end = p.get("licence_start"), p.get("licence_end")
        if not number:
            return
        f = iri(IriFactory.fact(source, rid))
        yield _FACT_MARK
        yield f"{f} {P.type} {C.Licence}"
        yield f"{f} {P.licenceNumber} {lit(number)}"
        yield f"{f} {P.licenceKind} {LICENCE_SOURCES[source]}"
        if p.get("status"):
            yield f"{f} {P.licenceStatus} {lit(p['status'])}"
        auths = [a for a in (p.get("authorisations") or []) if isinstance(a, str) and a.strip()]
        if auths and source == "asic_afsl" and p.get("authorisation_format") == 1:
            # Format 1: the condition is one text split into lines; keep it as one literal.
            auths = ["\n".join(auths)]
        for a in sorted(set(auths)):
            yield f"{f} {P.authorisation} {lit(a)}"
        yield from self._validity(f, start, end)
        yield f"{f} {P.aboutRecord} {rec}"
        yield f"{f} {P.derived} {rec}"

    def _ban(self, source: str, rid: str, rec: str, p: dict[str, Any]) -> Iterator[Any]:
        f = iri(IriFactory.fact(source, rid))
        yield _FACT_MARK
        yield f"{f} {P.type} {C.Ban}"
        if p.get("ban_type"):
            yield f"{f} {P.banType} {lit(p['ban_type'])}"
        if p.get("comment"):
            yield f"{f} {P.description} {lit(p['comment'])}"
        yield from self._validity(f, p.get("ban_start"), p.get("ban_end"))
        yield f"{f} {P.aboutRecord} {rec}"
        yield f"{f} {P.derived} {rec}"

    def _ownership(self, source: str, rid: str, rec: str, p: dict[str, Any]) -> Iterator[Any]:
        child, parent = p.get("child_lei"), p.get("parent_lei")
        if not child or not parent:  # only accounting-consolidation edges are ownership
            return
        kind = p.get("relationship_type")
        f = iri(IriFactory.fact(source, rid))
        yield _FACT_MARK
        yield f"{f} {P.type} {C.Ownership}"
        if kind in RELATIONSHIP_KINDS:
            yield f"{f} {P.relationshipKind} {bg(kind)}"
        if p.get("relationship_status"):
            yield f"{f} {P.relationshipStatus} {lit(p['relationship_status'])}"
        pct = ownership_percentage(p.get("quantifiers"))
        if pct:
            yield f"{f} {P.ownershipPercentage} {pct}"
        yield from self._validity(f, p.get("valid_from"), p.get("valid_to"))
        yield f"{f} {P.aboutRecord} {iri(IriFactory.source_record(LEI_RECORD_SOURCE, child))}"
        yield f"{f} {P.counterpartyRecord} {iri(IriFactory.source_record(LEI_RECORD_SOURCE, parent))}"
        yield f"{f} {P.derived} {rec}"

    # ------------------------------------------------------------------ canonical graph

    def _canonical_triples(self, counts: dict[str, int]) -> Iterator[str]:
        cols = self._columns("party_canonical")
        if not cols:
            return
        want = [
            "canonical_key", "party_type", "name", "name_norm", "abn", "acn", "lei", "entity_type",
            "status", "state", "postcode", "anzsic", "valid_from", "valid_to", "source", "record_id",
            "asic_record_id",
        ]
        select = ", ".join(f"p.{c}" if c in cols else f"NULL AS {c}" for c in want)
        ctes, joins, extra = [], [], []
        if self._has_table("identifier"):
            ctes.append(
                "ids AS (SELECT canonical_key, "
                + ", ".join(
                    f"list(DISTINCT value ORDER BY value) FILTER (WHERE scheme = '{s}') AS id_{s}"
                    for s in _ID_SCHEMES
                )
                + " FROM identifier GROUP BY canonical_key)"
            )
            joins.append("LEFT JOIN ids ON ids.canonical_key = p.canonical_key")
            extra += [f"ids.id_{s}" for s in _ID_SCHEMES]
        else:
            extra += [f"NULL AS id_{s}" for s in _ID_SCHEMES]
        acols = self._columns("alias")
        if {"canonical_key", "alias"} <= acols:
            ctes.append(
                "al AS (SELECT canonical_key, list(DISTINCT alias ORDER BY alias) AS aliases "
                "FROM alias WHERE alias IS NOT NULL AND alias <> '' GROUP BY canonical_key)"
            )
            joins.append("LEFT JOIN al ON al.canonical_key = p.canonical_key")
            extra.append("al.aliases")
        else:
            extra.append("NULL AS aliases")
        sql = (
            ("WITH " + ", ".join(ctes) + " " if ctes else "")
            + f"SELECT {select}, {', '.join(extra)} FROM party_canonical p {' '.join(joins)} "
            + "ORDER BY p.canonical_key"
        )
        parties = 0
        for row in self._stream(sql):
            (key, ptype, name, name_norm, abn, acn, lei, etype, status, state, postcode, anzsic,
             vfrom, vto, src, rid, asic_rid, id_abn, id_acn, id_arbn, id_lei, aliases) = row
            p_iri = IriFactory.party(abn, acn, lei, key)
            if not p_iri:
                continue
            parties += 1
            s = iri(p_iri)
            yield f"{s} {P.type} {PARTY_TYPES.get((ptype or '').lower(), C.Party)}"
            if name:
                yield f"{s} {P.name} {lit(name)}"
            if name_norm:
                yield f"{s} {P.nameNorm} {lit(name_norm)}"
            for pred, col, extra_ids in (
                (P.abn, abn, id_abn), (P.acn, acn, id_acn), (P.arbn, None, id_arbn), (P.lei, lei, id_lei)
            ):
                values = {v for v in (extra_ids or []) if v}
                if col:
                    values.add(col)
                for v in sorted(values):
                    yield f"{s} {pred} {lit(v)}"
            for pred, v in ((P.entityType, etype), (P.registrationStatus, status), (P.state, state),
                            (P.postcode, postcode), (P.anzsic, anzsic)):
                if v:
                    yield f"{s} {pred} {lit(v)}"
            a, b = lit_date(vfrom), lit_date(vto)
            if a:
                yield f"{s} {P.registeredOn} {a}"
            if b:
                yield f"{s} {P.deregisteredOn} {b}"
            for other in sorted({x for x in (aliases or []) if x and x != name}):
                yield f"{s} {P.otherName} {lit(other)}"
            prov = set()
            if src and rid:
                prov.add(IriFactory.source_record(src, rid))
            if asic_rid:
                prov.add(IriFactory.source_record("asic_company", asic_rid))
            for r in sorted(prov):
                yield f"{s} {P.derived} {iri(r)}"
        counts["parties"] = counts.get("parties", 0) + parties

    # ------------------------------------------------------------------ links graph

    def _party_join(self, alias: str, col: str) -> tuple[str, str]:
        """(select-list, join) resolving canonical key column `col` to the party's identifier columns,
        so link targets get the same IRI as the canonical graph (urn:abn > urn:acn > urn:lei)."""
        if self._has_table("party_canonical"):
            return (f"{alias}.abn, {alias}.acn, {alias}.lei",
                    f"LEFT JOIN party_canonical {alias} ON {alias}.canonical_key = {col}")
        return "NULL, NULL, NULL", ""

    def _links_triples(self, version: str | None, counts: dict[str, int]) -> Iterator[str]:
        if not version:
            return
        mv = lit(version)
        n_links = n_abst = n_roles = 0

        if self._has_table("link"):
            pcols, pjoin = self._party_join("pc", "l.canonical_key")
            sql = f"""SELECT l.source, l.record_id, l.canonical_key, l.match_type, l.confidence,
                             CAST(l.evidence AS VARCHAR), {pcols}
                      FROM link l {pjoin}
                      WHERE l.matcher_version = ?
                      ORDER BY l.source, l.record_id, l.canonical_key, l.link_id"""
            for src, rid, key, mtype, conf, evidence, abn, acn, lei in self._stream(sql, [version]):
                n_links += 1
                s = iri(IriFactory.link(version, src, rid))
                yield f"{s} {P.type} {C.Link}"
                yield f"{s} {P.sourceRecord} {iri(IriFactory.source_record(src, rid))}"
                yield f"{s} {P.party} {iri(IriFactory.party(abn, acn, lei, key))}"
                if mtype:
                    m = str(mtype).upper()
                    yield f"{s} {P.matchType} {bg(m) if m in MATCH_TYPES else lit(mtype)}"
                c = lit_decimal(conf)
                if c:
                    yield f"{s} {P.confidence} {c}"
                yield f"{s} {P.evidence} {lit(_canonical_json(evidence))}"
                yield f"{s} {P.matcherVersion} {mv}"

        if self._has_table("abstention"):
            pcols, pjoin = self._party_join("pc", "a.best_candidate")
            sql = f"""SELECT a.source, a.record_id, a.best_candidate, a.best_score, a.reason, {pcols}
                      FROM abstention a {pjoin}
                      WHERE a.matcher_version = ?
                      ORDER BY a.source, a.record_id"""
            for src, rid, best, score, reason, abn, acn, lei in self._stream(sql, [version]):
                n_abst += 1
                s = iri(IriFactory.abstention(version, src, rid))
                yield f"{s} {P.type} {C.Abstention}"
                yield f"{s} {P.sourceRecord} {iri(IriFactory.source_record(src, rid))}"
                if reason:
                    r = str(reason).upper()
                    yield f"{s} {P.abstainReason} {bg(r) if r in ABSTAIN_REASONS else lit(reason)}"
                if best:
                    yield f"{s} {P.bestCandidate} {iri(IriFactory.party(abn, acn, lei, best))}"
                sc = lit_decimal(score)
                if sc:
                    yield f"{s} {P.score} {sc}"
                yield f"{s} {P.matcherVersion} {mv}"

        if self._has_table("link"):
            for t in self._role_triples(version):
                n_roles += 1
                yield t
        counts.update(links=n_links, abstentions=n_abst, role_triples=n_roles)

    def _role_triples(self, version: str) -> Iterator[str]:
        """Party-level role shortcuts derived from links: written only into the links graph."""
        role_by_source = {**{s: P.licensee for s in LICENCE_SOURCES}, **{s: P.bannedParty for s in BAN_SOURCES}}
        srcs = ", ".join(f"'{s}'" for s in sorted(role_by_source))
        pcols, pjoin = self._party_join("pc", "l.canonical_key")
        sql = f"""WITH recs AS (SELECT DISTINCT source, record_id FROM source_record WHERE source IN ({srcs}))
                  SELECT r.source, r.record_id, l.canonical_key, {pcols}
                  FROM recs r
                  JOIN link l ON l.source = r.source AND l.record_id = r.record_id AND l.matcher_version = ?
                  {pjoin}
                  ORDER BY r.source, r.record_id, l.canonical_key"""
        for src, rid, key, abn, acn, lei in self._stream(sql, [version]):
            yield f"{iri(IriFactory.fact(src, rid))} {role_by_source[src]} {iri(IriFactory.party(abn, acn, lei, key))}"

        pc_c, jc = self._party_join("pcc", "lc.canonical_key")
        pc_p, jp = self._party_join("pcp", "lp.canonical_key")
        sql = f"""WITH own AS (
                      SELECT DISTINCT record_id, payload->>'child_lei' AS child, payload->>'parent_lei' AS parent
                      FROM source_record
                      WHERE source = '{OWNERSHIP_SOURCE}' AND payload->>'child_lei' IS NOT NULL
                        AND payload->>'parent_lei' IS NOT NULL)
                  SELECT o.record_id, lc.canonical_key, {pc_c}, lp.canonical_key, {pc_p}
                  FROM own o
                  LEFT JOIN link lc ON lc.source = '{LEI_RECORD_SOURCE}' AND lc.record_id = o.child
                                   AND lc.matcher_version = ?
                  LEFT JOIN link lp ON lp.source = '{LEI_RECORD_SOURCE}' AND lp.record_id = o.parent
                                   AND lp.matcher_version = ?
                  {jc} {jp}
                  WHERE lc.canonical_key IS NOT NULL OR lp.canonical_key IS NOT NULL
                  ORDER BY o.record_id, lc.canonical_key, lp.canonical_key"""
        seen: set[str] = set()
        for rid, ck, cabn, cacn, clei, pk, pabn, pacn, plei in self._stream(sql, [version, version]):
            f = iri(IriFactory.fact(OWNERSHIP_SOURCE, rid))
            for t in (
                f"{f} {P.owned} {iri(IriFactory.party(cabn, cacn, clei, ck))}" if ck else None,
                f"{f} {P.owner} {iri(IriFactory.party(pabn, pacn, plei, pk))}" if pk else None,
            ):
                if t and t not in seen:
                    seen.add(t)
                    yield t

    # ------------------------------------------------------------------ ontology graph

    def _ontology_triples(self, counts: dict[str, int]) -> Iterator[str]:
        from rdflib import Graph
        from rdflib.compare import to_canonical_graph

        g = to_canonical_graph(Graph().parse(self.ontology_dir / "schema.ttl", format="turtle"))
        lines = sorted(
            ln[:-2].rstrip() for ln in g.serialize(format="nt", encoding="utf-8").decode("utf-8").splitlines()
            if ln.strip()
        )
        counts["schema_triples"] = len(lines)
        yield from lines


_FACT_MARK = object()  # sentinel yielded by fact builders to count facts without a side channel


def ownership_percentage(quantifiers: Any) -> str | None:
    """xsd:decimal literal from GLEIF L2 quantifiers (ACCOUNTING_CONSOLIDATION, percentage units)."""
    for q in quantifiers or []:
        if not isinstance(q, dict):
            continue
        if (q.get("method") or "ACCOUNTING_CONSOLIDATION") != "ACCOUNTING_CONSOLIDATION":
            continue
        if q.get("units") not in (None, "", "PERCENTAGE"):
            continue
        value = lit_decimal(q.get("amount"))
        if value:
            return value
    return None


def _canonical_json(evidence: Any) -> str:
    """Evidence as compact, key-sorted JSON so the literal is stable across exports."""
    if evidence is None:
        return "{}"
    obj = _json(evidence) if isinstance(evidence, str) else evidence
    if obj is None:
        return str(evidence)
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
