"""Licence events derived by diffing consecutive register snapshots.

Why this exists
---------------
The ASIC AFS licensee dataset lists CURRENT licences only: no end date, no
cancelled status. The credit licensee dataset lists approved and suspended
licences only. So "financial services licence cancelled in the last 3 months"
cannot be read from any one file; it has to be inferred from a licence that is
present in one snapshot and absent in the next.

Event types (`EventType`)
-------------------------
* GRANTED              licence number appears that was absent in the previous snapshot.
                       Never emitted against the first snapshot (no baseline).
* CANCELLED_OR_LAPSED  licence number disappears. The dataset cannot tell a
                       cancellation by ASIC from a voluntary surrender, a lapse, a
                       suspension (AFSL) or a data error, so the name says exactly that.
* REAPPEARED           a licence number that had disappeared is back (a data glitch
                       or a revoked cancellation; never a fresh GRANTED).
* HOLDER_CHANGED       same licence number, a different holder: identifiers disagree,
                       or (no identifiers on one side) the names do not match. A
                       transfer, or a re-registration under a new entity.
* HOLDER_RENAMED       same licence number, same holder identifier, different name.
* AUTHORISATION_CHANGED  the authorisation (licence condition) text changed after
                       normalising away the August 2026 format change (quoted,
                       enumerated "(a)", "(i)" segments).
* STATUS_CHANGED       credit only: APPR <-> SUSP.

Dates
-----
`event_date` is the FIRST snapshot in which the change is visible. It is an
UPPER bound: the change happened on or before it. `observed_after` is the last
snapshot showing the previous state, the LOWER (exclusive) bound. With weekly
snapshots the window is a week; with the gaps in the archived history
(see outputs/sources.md) it can be months, and a query for "in the last 3
months" should test `event_date` and report `observed_after` alongside it.

Two entry points
----------------
* `events_from_store(con)`  reads every version of `asic_afsl` / `asic_credit` in
  `source_record` (first_seen_snapshot / last_seen_snapshot per content hash)
  and the snapshot dates in `source_snapshot`.
* `events_from_files(paths)` parses raw snapshot files with the same adapters
  (used by tests and for offline recomputation).

`write_events(con, events)` writes the `licence_event` table (DDL below).

Known limitation of the store path: a record whose content is identical before
and after a gap (present, absent, present again) is stored as one row whose
first_seen..last_seen interval spans the gap, so that disappearance is not
visible. The file path does not have this blind spot.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from bizgraph.domain.models import PartyType, SourceRecord
from bizgraph.normalise.names import NameNormaliser
from bizgraph.sources.adapters.tier2 import AfslAdapter, CreditLicenceAdapter, classify_party
from bizgraph.sources.base import RejectRecord

LICENCE_SOURCES = {"asic_afsl": "AFSL", "asic_credit": "ACL"}


class EventType(StrEnum):
    GRANTED = "GRANTED"
    CANCELLED_OR_LAPSED = "CANCELLED_OR_LAPSED"
    REAPPEARED = "REAPPEARED"
    HOLDER_CHANGED = "HOLDER_CHANGED"
    HOLDER_RENAMED = "HOLDER_RENAMED"
    AUTHORISATION_CHANGED = "AUTHORISATION_CHANGED"
    STATUS_CHANGED = "STATUS_CHANGED"


LICENCE_EVENT_DDL = """
CREATE TABLE IF NOT EXISTS licence_event (
    licence_kind        VARCHAR NOT NULL,   -- AFSL | ACL
    source              VARCHAR NOT NULL,   -- asic_afsl | asic_credit
    licence_no          VARCHAR NOT NULL,
    event_type          VARCHAR NOT NULL,   -- EventType
    event_date          DATE NOT NULL,      -- first snapshot showing the change (upper bound)
    observed_after      DATE,               -- last snapshot showing the old state (lower bound, exclusive)
    holder_name_before  VARCHAR,
    holder_name_after   VARCHAR,
    holder_abn_before   VARCHAR,
    holder_acn_before   VARCHAR,
    holder_abn_after    VARCHAR,
    holder_acn_after    VARCHAR,
    party_type          VARCHAR,
    record_iri          VARCHAR NOT NULL,   -- urn:src:{source}:{licence_no}
    content_hash_before VARCHAR,
    content_hash_after  VARCHAR,
    match_basis         VARCHAR,            -- how HOLDER_* was decided (identifier | name | person_name)
    detail              JSON,
    computed_at         TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (source, licence_no, event_type, event_date)
);
"""

_COLUMNS = (
    "licence_kind", "source", "licence_no", "event_type", "event_date", "observed_after",
    "holder_name_before", "holder_name_after", "holder_abn_before", "holder_acn_before",
    "holder_abn_after", "holder_acn_after", "party_type", "record_iri",
    "content_hash_before", "content_hash_after", "match_basis", "detail",
)

_NAMES = NameNormaliser()
# "(a) ", "(viii) ", "b) " and ASIC's own typo "(viii " (no closing parenthesis).
_ENUM = re.compile(r"^(?:\([a-z0-9]{1,5}\)?|[a-z0-9]{1,5}\))\s*", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


_NUMBERED = re.compile(r"^\d+(?:\.\d+)*\.?\s")


def authorisation_style(authorisations: Sequence[str]) -> str | None:
    """'numbered' ("1.1.1 Basic deposit products | Retail ...") or 'prose' ("This licence
    authorises ..."). From August 2026 ASIC restated several hundred licences from prose to
    the numbered schedule; a style change means the text was reworded, not necessarily
    that the authorisation changed."""
    if not authorisations:
        return None
    first = str(authorisations[0]).strip().strip('"')
    return "numbered" if _NUMBERED.match(first) else "prose"


def authorisation_signature(authorisations: Sequence[str]) -> str:
    """Format-insensitive hash of the authorisation text.

    Pre-August-2026 files write ``text~text``; later files write
    ``"(a) text"~"(i) text"`` (the adapter joins multi-field segments with ' | ').
    Quotes, enumerators, separators, punctuation and case are dropped.
    """
    parts = []
    for seg in authorisations:
        for piece in str(seg).split(" | "):
            p = piece.strip().strip('"').strip()
            p = _ENUM.sub("", p)
            parts.append(_NON_ALNUM.sub(" ", p.lower()).strip())
    text = " ".join(p for p in parts if p)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class LicenceState:
    """One licence as one snapshot shows it."""

    source: str
    licence_no: str
    name: str
    abn: str | None
    acn: str | None
    party_type: str
    auth_sig: str
    auth_count: int
    status: str | None
    content_hash: str | None = None
    auth_style: str | None = None

    @property
    def kind(self) -> str:
        return LICENCE_SOURCES[self.source]

    @classmethod
    def from_record(cls, rec: SourceRecord, content_hash: str | None = None) -> LicenceState:
        p = rec.payload
        auths = p.get("authorisations") or []
        return cls(
            source=rec.source,
            licence_no=rec.record_id,
            name=rec.name_raw or p.get("name") or "",
            abn=_ident(rec, "abn"),
            acn=_ident(rec, "acn"),
            party_type=str(rec.party_type),
            auth_sig=authorisation_signature(auths),
            auth_count=len(auths),
            auth_style=authorisation_style(auths),
            status=p.get("status_code") or p.get("status"),
            content_hash=content_hash or rec.content_hash,
        )


def _ident(rec: SourceRecord, scheme: str) -> str | None:
    for i in rec.identifiers:
        if i.scheme.value == scheme:
            return i.value
    return None


@dataclass
class LicenceEvent:
    licence_kind: str
    source: str
    licence_no: str
    event_type: EventType
    event_date: date
    observed_after: date | None
    holder_name_before: str | None = None
    holder_name_after: str | None = None
    holder_abn_before: str | None = None
    holder_acn_before: str | None = None
    holder_abn_after: str | None = None
    holder_acn_after: str | None = None
    party_type: str | None = None
    record_iri: str = ""
    content_hash_before: str | None = None
    content_hash_after: str | None = None
    match_basis: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def row(self) -> tuple[Any, ...]:
        d = asdict(self)
        d["event_type"] = str(self.event_type)
        d["detail"] = json.dumps(self.detail, sort_keys=True, default=str)
        return tuple(d[c] for c in _COLUMNS)


# --------------------------------------------------------------------------- holder comparison


def _is_person(name: str, party_type: str) -> bool:
    """Person test that survives the AFSL switch from 'LAST, GIVEN' to 'GIVEN LAST'."""
    if party_type == PartyType.PERSON.value:
        return True
    pt, _ = classify_party(name, comma_person_format=name.count(",") == 1)
    return pt is PartyType.PERSON


def _person_signature(name: str) -> tuple[str, str] | None:
    """(family name, first given initial). 'GALL, ALLAN JOHN' and 'ALLAN J GALL' agree."""
    n = _NAMES.normalise_person(name)
    if not n or len(n.tokens) < 2:
        return None
    return n.tokens[-1], n.tokens[0][0]


def _org_norm(name: str) -> str:
    n = _NAMES.normalise(name)
    return n.norm if n else name.upper().strip()


def same_holder(a: LicenceState, b: LicenceState) -> tuple[bool | None, str]:
    """(same?, basis). Identifiers decide when both sides have one; else names do."""
    ids_a = {x for x in (a.abn, a.acn) if x}
    ids_b = {x for x in (b.abn, b.acn) if x}
    # An ABN's last 9 digits are the ACN: compare on ACN-or-ABN-tail too.
    tails_a = ids_a | {x[2:] for x in ids_a if len(x) == 11}
    tails_b = ids_b | {x[2:] for x in ids_b if len(x) == 11}
    if ids_a and ids_b:
        return bool(tails_a & tails_b), "identifier"
    if _is_person(a.name, a.party_type) and _is_person(b.name, b.party_type):
        sa, sb = _person_signature(a.name), _person_signature(b.name)
        if sa and sb:
            return sa == sb, "person_name"
    return _org_norm(a.name) == _org_norm(b.name), "name"


def _renamed(a: LicenceState, b: LicenceState) -> bool:
    """A real name change, not the AFSL 'LAST, GIVEN' -> 'GIVEN LAST' reformat or a
    PTY LTD -> LIMITED style change that the normaliser already folds."""
    if _is_person(a.name, a.party_type) and _is_person(b.name, b.party_type):
        sa, sb = _person_signature(a.name), _person_signature(b.name)
        if sa and sb:
            return sa != sb
    return _org_norm(a.name) != _org_norm(b.name)


# --------------------------------------------------------------------------- diff


def diff_snapshots(
    snapshots: Sequence[tuple[date, dict[str, LicenceState]]],
) -> list[LicenceEvent]:
    """Diff consecutive snapshots (sorted by date). Each value maps licence_no -> state."""
    snaps = sorted(snapshots, key=lambda s: s[0])
    events: list[LicenceEvent] = []
    ever_seen: dict[str, date] = {}
    for _, states in snaps[:1]:
        ever_seen.update({k: snaps[0][0] for k in states})
    for (prev_d, prev), (cur_d, cur) in zip(snaps, snaps[1:]):
        for no in sorted(set(prev) | set(cur)):
            a, b = prev.get(no), cur.get(no)
            if a is None and b is not None:
                etype = EventType.REAPPEARED if no in ever_seen else EventType.GRANTED
                events.append(_event(etype, None, b, prev_d, cur_d))
            elif a is not None and b is None:
                events.append(_event(EventType.CANCELLED_OR_LAPSED, a, None, prev_d, cur_d))
            elif a is not None and b is not None:
                events.extend(_changes(a, b, prev_d, cur_d))
            if b is not None:
                ever_seen.setdefault(no, cur_d)
    return events


def _event(
    etype: EventType, a: LicenceState | None, b: LicenceState | None, prev_d: date, cur_d: date, **kw: Any
) -> LicenceEvent:
    s = b or a
    assert s is not None
    return LicenceEvent(
        licence_kind=s.kind,
        source=s.source,
        licence_no=s.licence_no,
        event_type=etype,
        event_date=cur_d,
        observed_after=prev_d,
        holder_name_before=a.name if a else None,
        holder_name_after=b.name if b else None,
        holder_abn_before=a.abn if a else None,
        holder_acn_before=a.acn if a else None,
        holder_abn_after=b.abn if b else None,
        holder_acn_after=b.acn if b else None,
        party_type=s.party_type,
        record_iri=f"urn:src:{s.source}:{s.licence_no}",
        content_hash_before=a.content_hash if a else None,
        content_hash_after=b.content_hash if b else None,
        **kw,
    )


def _changes(a: LicenceState, b: LicenceState, prev_d: date, cur_d: date) -> Iterator[LicenceEvent]:
    if a.name != b.name or {a.abn, a.acn} != {b.abn, b.acn}:
        same, basis = same_holder(a, b)
        if not same:
            yield _event(EventType.HOLDER_CHANGED, a, b, prev_d, cur_d, match_basis=basis)
        elif basis == "identifier" and _renamed(a, b):
            yield _event(EventType.HOLDER_RENAMED, a, b, prev_d, cur_d, match_basis=basis)
    if a.auth_sig != b.auth_sig:
        yield _event(
            EventType.AUTHORISATION_CHANGED, a, b, prev_d, cur_d,
            detail={
                "auth_count_before": a.auth_count,
                "auth_count_after": b.auth_count,
                "style_before": a.auth_style,
                "style_after": b.auth_style,
                # True: ASIC reworded the schedule (prose <-> numbered); likely not a
                # substantive change. Filter on this before treating it as one.
                "wording_restated": a.auth_style != b.auth_style,
            },
        )
    if a.status != b.status and a.source == "asic_credit":
        yield _event(
            EventType.STATUS_CHANGED, a, b, prev_d, cur_d,
            detail={"status_before": a.status, "status_after": b.status},
        )


# --------------------------------------------------------------------------- from raw files

_WB = re.compile(r"__(?:wb|asof)(\d{8})")
_ADAPTERS = {"afs_lic_": AfslAdapter, "credit_lic_": CreditLicenceAdapter}


def snapshot_date_for(path: Path) -> date:
    """`__wbYYYYMMDD` / `__asofYYYYMMDD` in the filename (archive capture date), else the
    latest licence start date in the file (a lower bound for the extract date)."""
    m = _WB.search(path.name)
    if m:
        return datetime.strptime(m.group(1), "%Y%m%d").date()
    adapter = _adapter_for(path)
    latest = None
    for rec in _records(adapter, path, date.today()):
        d = rec.payload.get("licence_start")
        if d and (latest is None or d > latest):
            latest = d
    if latest is None:
        raise ValueError(f"cannot date snapshot {path}; pass snapshot_dates")
    return date.fromisoformat(latest)


def _adapter_for(path: Path) -> AfslAdapter | CreditLicenceAdapter:
    for prefix, cls in _ADAPTERS.items():
        if path.name.startswith(prefix):
            return cls()
    raise ValueError(f"not an AFSL / credit snapshot file: {path.name}")


def _records(adapter: Any, path: Path, snap: date) -> Iterator[SourceRecord]:
    for row in adapter.parse(path):
        try:
            yield adapter.to_record(row, snap)
        except RejectRecord:
            continue


def states_from_file(path: Path, snap: date) -> dict[str, LicenceState]:
    adapter = _adapter_for(path)
    return {r.record_id: LicenceState.from_record(r) for r in _records(adapter, path, snap)}


def events_from_files(
    paths: Iterable[Path | str], snapshot_dates: dict[str, date] | None = None
) -> list[LicenceEvent]:
    """Events per source from raw snapshot files (AFSL and credit may be mixed)."""
    by_source: dict[str, list[tuple[date, dict[str, LicenceState]]]] = {}
    for p in map(Path, paths):
        snap = (snapshot_dates or {}).get(p.name) or snapshot_date_for(p)
        source = _adapter_for(p).source_id
        by_source.setdefault(source, []).append((snap, states_from_file(p, snap)))
    out: list[LicenceEvent] = []
    for source, snaps in sorted(by_source.items()):
        dates = [d for d, _ in snaps]
        if len(dates) != len(set(dates)):
            raise ValueError(f"{source}: two files share a snapshot date")
        out.extend(diff_snapshots(snaps))
    return out


# --------------------------------------------------------------------------- from the store

_STATE_SQL = """
WITH snaps AS (
    SELECT DISTINCT snapshot_date AS snap FROM source_snapshot WHERE source = $source
    UNION
    SELECT DISTINCT first_seen_snapshot FROM source_record WHERE source = $source
    UNION
    SELECT DISTINCT last_seen_snapshot FROM source_record WHERE source = $source
),
cand AS (
    SELECT s.snap, r.record_id, r.content_hash, r.name_raw, r.party_type, r.abn, r.acn,
           r.payload,
           row_number() OVER (
               PARTITION BY s.snap, r.record_id
               ORDER BY r.first_seen_snapshot DESC, r.load_seq DESC NULLS LAST
           ) AS rn
    FROM snaps s
    JOIN source_record r
      ON r.source = $source
     AND r.first_seen_snapshot <= s.snap
     AND r.last_seen_snapshot >= s.snap
)
SELECT snap, record_id, content_hash, name_raw, party_type, abn, acn, payload
FROM cand WHERE rn = 1
ORDER BY snap, record_id
"""


def states_from_store(con: Any, source: str) -> list[tuple[date, dict[str, LicenceState]]]:
    """Per snapshot date, the version of each licence live on that date.

    A version is live on S when first_seen_snapshot <= S <= last_seen_snapshot; if two
    versions overlap (content changed then changed back) the one first seen latest wins.
    """
    rows = con.execute(_STATE_SQL, {"source": source}).fetchall()
    out: dict[date, dict[str, LicenceState]] = {}
    for snap, rid, chash, name, ptype, abn, acn, payload in rows:
        p = json.loads(payload) if isinstance(payload, str) else (payload or {})
        auths = p.get("authorisations") or []
        out.setdefault(snap, {})[rid] = LicenceState(
            source=source,
            licence_no=rid,
            name=name or p.get("name") or "",
            abn=abn,
            acn=acn,
            party_type=ptype or PartyType.UNKNOWN.value,
            auth_sig=authorisation_signature(auths),
            auth_count=len(auths),
            auth_style=authorisation_style(auths),
            status=p.get("status_code") or p.get("status"),
            content_hash=chash,
        )
    return sorted(out.items())


def events_from_store(con: Any, sources: Iterable[str] = tuple(LICENCE_SOURCES)) -> list[LicenceEvent]:
    events: list[LicenceEvent] = []
    for source in sources:
        events.extend(diff_snapshots(states_from_store(con, source)))
    return events


def write_events(con: Any, events: Sequence[LicenceEvent], replace: bool = True) -> int:
    """Create `licence_event` if needed and write `events`. `replace` clears the sources
    present in `events` first, so a recompute is idempotent."""
    con.execute(LICENCE_EVENT_DDL)
    if replace:
        for source in sorted({e.source for e in events}):
            con.execute("DELETE FROM licence_event WHERE source = ?", [source])
    if events:
        placeholders = ", ".join("?" for _ in _COLUMNS)
        con.executemany(
            f"INSERT OR REPLACE INTO licence_event ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
            [e.row() for e in events],
        )
    return len(events)


def summarise(events: Iterable[LicenceEvent]) -> dict[tuple[str, str, date], int]:
    """Counts by (source, event_type, event_date)."""
    out: dict[tuple[str, str, date], int] = {}
    for e in events:
        k = (e.source, str(e.event_type), e.event_date)
        out[k] = out.get(k, 0) + 1
    return out
