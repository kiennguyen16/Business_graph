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
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb

from bizgraph.rdf.vocab import (
    ABSTAIN_REASONS,
    GRAPH_LICENCE_HISTORY,
    XSD_ANYURI,
    as_date,
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
    lit_typed,
)

LICENCE_SOURCES = {"asic_afsl": C.AFSL, "asic_credit": C.ACL, "asic_liquidator": C.REGISTERED_LIQUIDATOR}
BAN_SOURCES = frozenset({"asic_banned_org", "asic_banned"})
OWNERSHIP_SOURCE = "gleif_l2"
NOTICE_SOURCES = frozenset({"accc_notice"})
FACT_SOURCES = frozenset({*LICENCE_SOURCES, *BAN_SOURCES, *NOTICE_SOURCES, OWNERSHIP_SOURCE})
LEI_RECORD_SOURCE = "gleif_l1"
ASIC_COMPANY_SOURCE = "asic_company"  # Ownership facts point at the L1 records of both ends
PARTY_TYPES = {"organisation": C.Organisation, "person": C.Person}
_SCHEME_TYPES = frozenset({"scheme", "managed_investment_scheme", "mis"})
_ID_SCHEMES = ("abn", "acn", "arbn", "lei", "arsn", "nzbn", "nz_company_no")

# identifiers taken from source_record.identifiers (abn/acn/lei come from their own columns)
RECORD_ID_PREDICATES = (
    ("arbn", P.arbn), ("arsn", P.arsn), ("nzbn", P.nzbn), ("nz_company_no", P.nzCompanyNumber),
    ("afsl", P.afslNumber), ("acl", P.aclNumber), ("liquidator_no", P.liquidatorNumber),
)
_LICENCE_NO_PRED = {"asic_afsl": P.afslNumber, "asic_credit": P.aclNumber, "asic_liquidator": P.liquidatorNumber}
_STRIP_ZEROS = frozenset({"afsl", "acl", "liquidator_no"})
_DESC_PRED = {
    "state": P.state, "registration_status": P.registrationStatus, "entity_type": P.entityType,
    "country": P.country, "legal_jurisdiction": P.legalJurisdiction, "legal_form_code": P.legalFormCode,
    "lei_registration_status": P.leiRegistrationStatus, "source_url": P.sourceUrl,
    "foreign_reference": P.foreignReference,
}


def _descriptive_sql(source: str) -> list[tuple[str, str]]:
    """(attribute, SQL expression) for the descriptive literals a source's records carry.
    Licence registers keep their status on the bg:Licence fact, not on the record."""
    cols = [("state", "state")]
    if source == "gleif_l1":
        cols += [
            ("registration_status", "payload->>'entity_status'"),
            # legal address country, headquarters country as fallback
            ("country", "coalesce(payload->'legal_address'->>'country', "
                        "payload->'headquarters_address'->>'country', payload->>'country')"),
            ("legal_jurisdiction", "payload->>'legal_jurisdiction'"),
            ("legal_form_code", "payload->>'legal_form_code'"),
            ("lei_registration_status", "payload->>'lei_status'"),
        ]
    elif source == "abr":
        cols += [("registration_status", "payload->>'abn_status'"), ("entity_type", "payload->>'entity_type_code'")]
    elif source == "asic_company":
        cols += [("registration_status", "payload->>'status'"), ("entity_type", "payload->>'type'")]
    elif source in ("asic_afsl", "asic_liquidator"):
        cols += [("country", "payload->>'country'")]
    elif source in NOTICE_SOURCES:
        cols += [
            ("source_url", "payload->>'url'"),
            ("foreign_reference", "CASE WHEN coalesce(payload->>'reference_kind', '') LIKE 'foreign%' "
                                  "THEN payload->>'reference_number' END"),
        ]
    return cols


def _ids_by_scheme(ids: Any) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for pair in _json(ids) or []:
        if isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[1]:
            out.setdefault(str(pair[0]), set()).add(str(pair[1]))
    return out

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
        if self.kind == "derived":
            return "derived__licence_history"
        return self.kind

    @staticmethod
    def canonical() -> NamedGraph:
        return NamedGraph("canonical", GRAPH_CANONICAL)

    @staticmethod
    def ontology() -> NamedGraph:
        return NamedGraph("ontology", GRAPH_ONTOLOGY)

    @staticmethod
    def licence_history() -> NamedGraph:
        return NamedGraph("derived", GRAPH_LICENCE_HISTORY)

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

    def __init__(self, con: duckdb.DuckDBPyConnection | Any, ontology_dir: Path | None = None,
                 all_asic_company: bool = False) -> None:
        """all_asic_company=False (default) publishes only the ASIC company records the graph can
        reach (see `_asic_company_scope_sql`); True publishes the whole register."""
        self.con = getattr(con, "con", con)  # accept a DuckDBStore too
        self.all_asic_company = all_asic_company
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

    def has_licence_events(self) -> bool:
        return {"source", "licence_no", "event_type", "event_date", "observed_after"} <= self._columns(
            "licence_event"
        )

    def graphs(self, kinds: Iterable[str] | None = None, source: str | None = None,
               matcher_version: str | None = None) -> list[NamedGraph]:
        """The PUBLISHED set: ontology, one graph per source at its LATEST snapshot, canonical,
        links per matcher version, and the derived licence-history graph. Historical snapshot
        graphs are exportable for audit (NamedGraph.source_snapshot) but never listed here:
        one record IRI per record id means two snapshots of a source in one union disagree
        on the record's snapshot-specific literals."""
        kinds = set(kinds or ("ontology", "source", "canonical", "links", "derived"))
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
        if "derived" in kinds and self.has_licence_events():
            out.append(NamedGraph.licence_history())
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
        elif graph.kind == "derived":
            yield from self._licence_history_triples(counts)
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

        self._end_bounds = self._licence_end_bounds(source, snapshot)
        want_payload = source in FACT_SOURCES
        scope = ""
        if source == ASIC_COMPANY_SOURCE and not self.all_asic_company:
            scope = f"AND record_id IN ({self._asic_company_scope_sql()})"
        desc = ", ".join(f"{expr} AS {name}" for name, expr in _descriptive_sql(source))
        trustee = "payload->>'trustee_acn'" if source == LEI_RECORD_SOURCE else "NULL"
        sql = f"""
            SELECT record_id, content_hash, first_seen_snapshot, name_raw, name_norm, party_type,
                   abn, acn, lei, CAST(identifiers AS VARCHAR), {'payload' if want_payload else 'NULL'},
                   {trustee}, {desc}
            FROM source_record
            WHERE source = ? AND first_seen_snapshot <= ? AND last_seen_snapshot >= ?
              {scope}
            QUALIFY row_number() OVER (
                PARTITION BY record_id
                ORDER BY last_seen_snapshot DESC, load_seq DESC NULLS LAST, content_hash) = 1
            ORDER BY record_id"""
        src_lit = lit(source)
        records = facts = trusteeships = 0
        for row in self._stream(sql, [source, snapshot, snapshot]):
            rid, chash, first_seen, name_raw, name_norm, ptype, abn, acn, lei, ids, payload, trustee_acn = row[:12]
            records += 1
            s = iri(IriFactory.source_record(source, rid))
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
            by_scheme = _ids_by_scheme(ids)
            arsns = by_scheme.get("arsn", set())
            if abn:
                yield f"{s} {P.abn} {lit(abn)}"
            if acn and acn not in arsns:  # an ARSN is never written as an ACN
                yield f"{s} {P.acn} {lit(acn)}"
            if lei:
                yield f"{s} {P.lei} {lit(lei)}"
            for scheme, pred in RECORD_ID_PREDICATES:
                values = by_scheme.get(scheme, set())
                if scheme in _STRIP_ZEROS:
                    values = {v.lstrip("0") for v in values}
                for v in sorted(v for v in values if v and v != "0"):
                    yield f"{s} {pred} {lit(v)}"
            for (name, _), value in zip(_descriptive_sql(source), row[12:]):
                if value not in (None, ""):
                    obj = lit_typed(value, XSD_ANYURI) if name == "source_url" else lit(value)
                    yield f"{s} {_DESC_PRED[name]} {obj}"
            if want_payload:
                for t in self._fact_triples(source, rid, s, _json(payload) or {}):
                    if t is _FACT_MARK:
                        facts += 1
                    else:
                        yield t
            if trustee_acn:
                trusteeships += 1
                yield from self._trusteeship(rid, s, trustee_acn)
        counts["records"] = counts.get("records", 0) + records
        counts["facts"] = counts.get("facts", 0) + facts + trusteeships
        if trusteeships:
            counts["trusteeships"] = counts.get("trusteeships", 0) + trusteeships

    @staticmethod
    def _trusteeship(lei: str, rec: str, acn: str) -> Iterator[str]:
        """GLEIF L1 trust whose registration number is its trustee's ACN: the trustee is named
        only by that ACN (bg:counterpartyAcn); the role is attributed in the links graph."""
        f = iri(IriFactory.trusteeship(lei))
        yield f"{f} {P.type} {C.Trusteeship}"
        yield f"{f} {P.relationshipKind} {C.HAS_TRUSTEE}"
        yield f"{f} {P.aboutRecord} {rec}"
        yield f"{f} {P.counterpartyAcn} {lit(acn)}"
        yield f"{f} {P.derived} {rec}"

    def _licence_end_bounds(self, source: str, snapshot: date) -> dict[str, tuple[date, date]]:
        """licence_no -> (validToNotBefore, validToNotAfter) from snapshot-diff events
        (bizgraph.pipeline.licence_history). Only CANCELLED_OR_LAPSED events whose last sighting
        (observed_after) is on or after this graph's snapshot apply: the licence was still live in
        this snapshot and is gone later. With several such events, the earliest one wins.
        No licence_event table: no bounds."""
        if source not in LICENCE_SOURCES or not {"licence_no", "event_type", "observed_after", "event_date"} <= (
            self._columns("licence_event")
        ):
            return {}
        rows = self.con.execute(
            """SELECT licence_no, min(observed_after), arg_min(event_date, observed_after)
               FROM licence_event
               WHERE source = ? AND event_type = 'CANCELLED_OR_LAPSED'
                 AND observed_after IS NOT NULL AND observed_after >= ?
               GROUP BY licence_no""",
            [source, snapshot],
        ).fetchall()
        out = {}
        for no, after, event_date in rows:
            not_after = event_date - timedelta(days=1)
            if after <= not_after:
                out[str(no).lstrip("0")] = (after, not_after)
        return out

    def _asic_company_scope_sql(self) -> str:
        """ACNs whose ASIC company record is published. The register holds every Australian
        company (4M rows); the graph only needs the ones it can reach:
        * the ACN of a canonical party (party_canonical.acn or identifier scheme 'acn');
        * party_canonical.asic_record_id (the record a canonical party was enriched from);
        * an ACN asserted by any other source (Tier 2 / Tier 3 records, GLEIF trustee ACNs);
        * a record named in the quarantine table (evidence for a conflict).
        Everything else stays in DuckDB as evidence and is one `export --all-asic-company` away."""
        parts = ["SELECT acn FROM source_record WHERE source NOT IN ('abr', 'asic_company') AND acn IS NOT NULL",
                 "SELECT payload->>'trustee_acn' FROM source_record WHERE source = 'gleif_l1' "
                 "AND payload->>'trustee_acn' IS NOT NULL"]
        pc = self._columns("party_canonical")
        if "acn" in pc:
            parts.append("SELECT acn FROM party_canonical WHERE acn IS NOT NULL")
        if "asic_record_id" in pc:
            parts.append("SELECT asic_record_id FROM party_canonical WHERE asic_record_id IS NOT NULL")
        if self._has_table("identifier"):
            parts.append("SELECT value FROM identifier WHERE scheme = 'acn'")
        if {"source", "record_id"} <= self._columns("quarantine"):
            parts.append("SELECT record_id FROM quarantine WHERE source = 'asic_company'")
        return " UNION ".join(parts)

    def _fact_triples(self, source: str, rid: str, rec: str, p: dict[str, Any]) -> Iterator[Any]:
        if source in LICENCE_SOURCES:
            yield from self._licence(source, rid, rec, p)
            if source == "asic_liquidator" and (p.get("firm") or "").strip():
                yield from self._affiliation(source, rid, rec, p["firm"].strip())
        elif source in BAN_SOURCES:
            yield from self._ban(source, rid, rec, p)
        elif source in NOTICE_SOURCES:
            yield from self._notice(source, rid, rec, p)
        elif source == OWNERSHIP_SOURCE:
            yield from self._ownership(source, rid, rec, p)

    def _notice(self, source: str, rid: str, rec: str, p: dict[str, Any]) -> Iterator[Any]:
        """ACCC infringement notice: an event, validFrom = validTo = date paid (else date issued).
        A notice naming several parties gives one fact per party (urn:fact:...:{n}, n from 1 in the
        payload's party order); the record's own name is the first party, so its link attributes
        fact 1 only. Absent values (no penalty stated on the register) emit nothing."""
        parties = p.get("parties") or [None]
        multi = len(parties) > 1
        when = p.get("date_paid") or p.get("date_issued")
        description = p.get("description") or p.get("section")
        numbers = sorted({str(x).strip() for x in (p.get("infringement_numbers") or []) if str(x or "").strip()})
        acts = sorted({str(x).strip() for x in (p.get("legislation") or []) if str(x or "").strip()})
        try:
            count = lit_integer(p["notice_count"]) if int(p.get("notice_count") or 0) >= 1 else None
        except (TypeError, ValueError):
            count = None
        for n in range(1, len(parties) + 1):
            f = iri(IriFactory.fact(source, rid, n if multi else None))
            yield _FACT_MARK
            yield f"{f} {P.type} {C.InfringementNotice}"
            yield f"{f} {P.regulator} {lit(p.get('regulator') or 'ACCC')}"
            amount = lit_decimal(p.get("penalty_total_aud")) if not multi else None
            if amount:
                yield f"{f} {P.amountAud} {amount}"
            if description:
                yield f"{f} {P.description} {lit(description)}"
            for number in numbers:
                yield f"{f} {P.infringementNumber} {lit(number)}"
            if count:
                yield f"{f} {P.noticeCount} {count}"
            for act in acts:
                yield f"{f} {P.legislation} {lit(act)}"
            yield from self._validity(f, when, when)
            yield f"{f} {P.aboutRecord} {rec}"
            yield f"{f} {P.derived} {rec}"

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
        bounds = getattr(self, "_end_bounds", {}).get(number)
        if bounds and lit_date(end) is None:  # a stated end wins; derived ends are bounds, never validTo
            yield f"{f} {P.validToNotBefore} {lit_date(bounds[0])}"
            yield f"{f} {P.validToNotAfter} {lit_date(bounds[1])}"
        yield f"{f} {P.aboutRecord} {rec}"
        yield f"{f} {P.derived} {rec}"

    @staticmethod
    def _affiliation(source: str, rid: str, rec: str, firm: str) -> Iterator[Any]:
        """Liquidator acts for a firm named only by name: an unresolved counterparty
        (bg:counterpartyName). bg:affiliatedWith is never written from a name."""
        f = iri(IriFactory.affiliation(source, rid))
        yield _FACT_MARK
        yield f"{f} {P.type} {C.Affiliation}"
        yield f"{f} {P.relationshipKind} {C.ACTS_FOR}"
        yield f"{f} {P.counterpartyName} {lit(firm)}"
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
            "asic_record_id", "arsn",
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
        parties = schemes = 0
        for row in self._stream(sql):
            (key, ptype, name, name_norm, abn, acn, lei, etype, status, state, postcode, anzsic,
             vfrom, vto, src, rid, asic_rid, arsn_col, id_abn, id_acn, id_arbn, id_lei, id_arsn, id_nzbn,
             id_nzco, aliases) = row
            arsns = {v for v in (id_arsn or []) if v} | ({arsn_col} if arsn_col else set())
            is_scheme = bool(arsns) or (ptype or "").lower() in _SCHEME_TYPES
            if is_scheme:  # a managed investment scheme never carries (or is keyed by) an ACN
                acn, id_acn = None, None
            p_iri = IriFactory.party(abn, acn, lei, key)
            if not p_iri:
                continue
            parties += 1
            s = iri(p_iri)
            if is_scheme:
                schemes += 1
                ptype_iri = C.ManagedInvestmentScheme
            else:
                ptype_iri = PARTY_TYPES.get((ptype or "").lower(), C.Party)
            yield f"{s} {P.type} {ptype_iri}"
            if name:
                yield f"{s} {P.name} {lit(name)}"
            if name_norm:
                yield f"{s} {P.nameNorm} {lit(name_norm)}"
            for pred, col, extra_ids in (
                (P.abn, abn, id_abn), (P.acn, acn, id_acn), (P.arbn, None, id_arbn), (P.lei, lei, id_lei),
                (P.arsn, None, sorted(arsns)), (P.nzbn, None, id_nzbn), (P.nzCompanyNumber, None, id_nzco),
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
        counts["schemes"] = counts.get("schemes", 0) + schemes

    # ------------------------------------------------------------------ links graph

    def _party_join(self, alias: str, col: str) -> tuple[str, str]:
        """(select-list, join) resolving canonical key column `col` to the party's identifier columns,
        so link targets get the same IRI as the canonical graph (urn:abn > urn:acn > urn:lei)."""
        if self._has_table("party_canonical"):
            acn = f"CASE WHEN {self._scheme_predicate(alias)} THEN NULL ELSE {alias}.acn END"
            return (f"{alias}.abn, {acn}, {alias}.lei",
                    f"LEFT JOIN party_canonical {alias} ON {alias}.canonical_key = {col}")
        return "NULL, NULL, NULL", ""

    def _scheme_predicate(self, alias: str) -> str:
        """SQL: the party row `alias` is a managed investment scheme (same rule as the canonical graph)."""
        conds = [f"lower(coalesce({alias}.party_type, '')) IN ({', '.join(repr(t) for t in sorted(_SCHEME_TYPES))})"]
        if "arsn" in self._columns("party_canonical"):
            conds.append(f"coalesce({alias}.arsn, '') <> ''")
        if self._has_table("identifier"):
            conds.append(f"{alias}.canonical_key IN (SELECT canonical_key FROM identifier WHERE scheme = 'arsn')")
        return "(" + " OR ".join(conds) + ")"

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
        role_by_source = {
            **{s: P.licensee for s in LICENCE_SOURCES},
            **{s: P.bannedParty for s in BAN_SOURCES},
            **{s: P.noticeRecipient for s in NOTICE_SOURCES},
        }
        srcs = ", ".join(f"'{s}'" for s in sorted(role_by_source))
        pcols, pjoin = self._party_join("pc", "l.canonical_key")
        sql = f"""WITH recs AS (
                      SELECT source, record_id,
                             bool_or(coalesce(json_array_length(payload->'parties'), 0) > 1) AS multi,
                             bool_or(source = 'asic_liquidator'
                                     AND coalesce(trim(payload->>'firm'), '') <> '') AS has_firm
                      FROM source_record WHERE source IN ({srcs}) GROUP BY source, record_id)
                  SELECT r.source, r.record_id, r.multi, r.has_firm, l.canonical_key, {pcols}
                  FROM recs r
                  JOIN link l ON l.source = r.source AND l.record_id = r.record_id AND l.matcher_version = ?
                  {pjoin}
                  ORDER BY r.source, r.record_id, l.canonical_key"""
        for src, rid, multi, has_firm, key, abn, acn, lei in self._stream(sql, [version]):
            party = iri(IriFactory.party(abn, acn, lei, key))
            # multi-party notice: the record (and so its link) names the first party -> fact 1
            fact = IriFactory.fact(src, rid, 1 if multi and src in NOTICE_SOURCES else None)
            if src != "asic_liquidator" or (rid or "").lstrip("0"):
                yield f"{iri(fact)} {role_by_source[src]} {party}"
            if has_firm:  # the liquidator (subject) of their firm affiliation; the firm stays unresolved
                yield f"{iri(IriFactory.affiliation(src, rid))} {P.member} {party}"

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

        yield from self._trusteeship_roles(version)

    def _trusteeship_roles(self, version: str) -> Iterator[str]:
        """bg:trustee by ACN equality, bg:trust by the trust record's link. Both only when the
        trustee ACN resolves to exactly one canonical party whose ACN is not quarantined (and
        that party is not itself a scheme, which never carries an ACN)."""
        if not self._has_table("party_canonical"):
            return
        pc_cols = self._columns("party_canonical")
        acn_sources = ["SELECT canonical_key, acn FROM party_canonical WHERE acn IS NOT NULL"]
        if self._has_table("identifier"):
            acn_sources.append("SELECT canonical_key, value FROM identifier WHERE scheme = 'acn'")
        bad = [f"SELECT canonical_key FROM party_canonical p WHERE {self._scheme_predicate('p')}"]
        if "quarantined" in pc_cols:
            bad.append("SELECT canonical_key FROM party_canonical WHERE coalesce(quarantined, false)")
        if "canonical_key" in self._columns("quarantine"):
            bad.append(
                "SELECT canonical_key FROM quarantine WHERE canonical_key IS NOT NULL "
                "AND lower(invariant) LIKE '%acn%'"
            )
        tcols, tjoin = self._party_join("pct", "ap.canonical_key")
        scols, sjoin = self._party_join("pcs", "l.canonical_key")
        sql = f"""
            WITH tr AS (
                SELECT DISTINCT record_id AS lei, payload->>'trustee_acn' AS acn FROM source_record
                WHERE source = '{LEI_RECORD_SOURCE}' AND payload->>'trustee_acn' IS NOT NULL),
            acns AS (SELECT DISTINCT * FROM ({' UNION ALL '.join(acn_sources)}) t(canonical_key, acn)),
            bad AS ({' UNION '.join(bad)}),
            ap AS (
                SELECT acn, min(canonical_key) AS canonical_key FROM acns GROUP BY acn
                HAVING count(DISTINCT canonical_key) = 1
                   AND NOT bool_or(canonical_key IN (SELECT canonical_key FROM bad)))
            SELECT tr.lei, ap.canonical_key, {tcols}, l.canonical_key, {scols}
            FROM tr JOIN ap ON ap.acn = tr.acn
            {tjoin}
            LEFT JOIN link l ON l.source = '{LEI_RECORD_SOURCE}' AND l.record_id = tr.lei AND l.matcher_version = ?
            {sjoin}
            ORDER BY tr.lei, ap.canonical_key, l.canonical_key"""
        seen: set[str] = set()
        for lei, tk, tabn, tacn, tlei, sk, sabn, sacn, slei in self._stream(sql, [version]):
            f = iri(IriFactory.trusteeship(lei))
            trustee = iri(IriFactory.party(tabn, tacn, tlei, tk))
            trust = iri(IriFactory.party(sabn, sacn, slei, sk)) if sk else None
            if trust == trustee:  # a trust cannot be its own trustee: attribute neither
                continue
            for t in (f"{f} {P.trustee} {trustee}", f"{f} {P.trust} {trust}" if trust else None):
                if t and t not in seen:
                    seen.add(t)
                    yield t

    # ------------------------------------------------------------------ derived: licence history

    def _licence_history_triples(self, counts: dict[str, int]) -> Iterator[str]:
        """urn:graph:derived:licence_history: one bg:Licence per CANCELLED_OR_LAPSED event in
        licence_event, IRI urn:fact:{source}:{record_id}:ended:{event_date}, with the end
        bracketed by bg:validToNotBefore (last snapshot showing it) and bg:validToNotAfter (the
        day before the first snapshot without it); never bg:validTo.

        bg:aboutRecord points at the record IRI. A licence that ended is normally absent from
        its source's latest snapshot graph, so its record would be untyped in the published
        union (FactShape needs sh:class bg:SourceRecord); for exactly those records this graph
        carries the record's description from its last version seen. Records that are still in
        the latest snapshot (a licence that reappeared) are not repeated here, which would give
        the record two bg:snapshotDate values."""
        if not self.has_licence_events():
            return
        srcs = ", ".join(f"'{s}'" for s in sorted(LICENCE_SOURCES))
        sql = f"""
            WITH ev AS (
                SELECT source, licence_no, event_date, observed_after FROM licence_event
                WHERE event_type = 'CANCELLED_OR_LAPSED' AND source IN ({srcs})
                  AND observed_after IS NOT NULL AND event_date IS NOT NULL),
            latest AS (SELECT source, max(last_seen_snapshot) AS d FROM source_record
                       WHERE source IN ({srcs}) GROUP BY source),
            rec AS (
                SELECT r.source, r.record_id, r.content_hash, r.first_seen_snapshot, r.last_seen_snapshot,
                       r.name_raw, r.name_norm, r.party_type, r.abn, r.acn, r.lei,
                       r.payload->>'licence_start' AS licence_start,
                       r.payload->>'registration_start' AS registration_start,
                       r.last_seen_snapshot >= l.d AS in_latest
                FROM source_record r JOIN latest l ON l.source = r.source
                WHERE r.source IN ({srcs})
                QUALIFY row_number() OVER (PARTITION BY r.source, r.record_id
                    ORDER BY r.last_seen_snapshot DESC, r.load_seq DESC NULLS LAST, r.content_hash) = 1)
            SELECT ev.source, ev.licence_no, ev.event_date, ev.observed_after,
                   rec.record_id, rec.content_hash, rec.last_seen_snapshot, rec.name_raw, rec.name_norm,
                   rec.party_type, rec.abn, rec.acn, rec.lei,
                   coalesce(rec.licence_start, rec.registration_start), coalesce(rec.in_latest, false)
            FROM ev LEFT JOIN rec ON rec.source = ev.source AND rec.record_id = ev.licence_no
            ORDER BY ev.source, ev.licence_no, ev.event_date"""
        facts = records = skipped = 0
        described: set[str] = set()
        for (source, no, event_date, after, rid, chash, last_seen, name_raw, name_norm, ptype,
             abn, acn, lei, start, in_latest) in self._stream(sql):
            not_after = event_date - timedelta(days=1)
            number = str(no).lstrip("0")
            if not number or after > not_after:
                skipped += 1
                continue
            rid = rid or str(no)
            rec = iri(IriFactory.source_record(source, rid))
            if chash and not in_latest and rec not in described:
                described.add(rec)
                records += 1
                yield f"{rec} {P.type} {C.SourceRecord}"
                yield f"{rec} {P.sourceId} {lit(source)}"
                yield f"{rec} {P.recordId} {lit(rid)}"
                # last snapshot that showed it (= observed_after): the record's state when it ended
                yield f"{rec} {P.snapshotDate} {lit_date(last_seen)}"
                yield f"{rec} {P.contentHash} {lit(chash)}"
                yield f"{rec} {_LICENCE_NO_PRED[source]} {lit(number)}"
                for pred, v in ((P.nameRaw, name_raw), (P.nameNorm, name_norm), (P.partyTypeHint, ptype),
                                (P.abn, abn), (P.acn, acn), (P.lei, lei)):
                    if v:
                        yield f"{rec} {pred} {lit(v)}"
            f = iri(IriFactory.ended_licence(source, rid, event_date))
            facts += 1
            yield f"{f} {P.type} {C.Licence}"
            yield f"{f} {P.licenceNumber} {lit(number)}"
            yield f"{f} {P.licenceKind} {LICENCE_SOURCES[source]}"
            start_lit = lit_date(start)
            if start_lit and (as_date(start) or after) <= after:
                yield f"{f} {P.validFrom} {start_lit}"
            yield f"{f} {P.validToNotBefore} {lit_date(after)}"
            yield f"{f} {P.validToNotAfter} {lit_date(not_after)}"
            yield f"{f} {P.aboutRecord} {rec}"
            yield f"{f} {P.derived} {rec}"
        counts.update(ended_licences=facts, records_described=records, events_skipped=skipped)

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
