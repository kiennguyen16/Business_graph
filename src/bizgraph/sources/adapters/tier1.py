"""Tier 1 adapters: the identity backbone (ABR bulk extract, ASIC company register).

ABR bulk extract (data.gov.au dataset ``abn-bulk-extract``, CC BY 3.0 AU)
--------------------------------------------------------------------------
Two zips (``public_split_1_10.zip``, ``public_split_11_20.zip``), each holding
ten ~635 MB XML files ``YYYYMMDD_PublicNN.xml`` (about 20 million ABNs in
total). Layout per ``bulkextract.xsd``::

    <Transfer error="none">
      <TransferInfo><FileSequenceNumber/><RecordCount/><ExtractTime/></TransferInfo>
      <ABR recordLastUpdatedDate="YYYYMMDD" replaced="N|Y">
        <ABN status="ACT|CAN" ABNStatusFromDate="YYYYMMDD">11 digits</ABN>
        <EntityType><EntityTypeInd>PRV</EntityTypeInd><EntityTypeText>...</EntityTypeText></EntityType>
        either <MainEntity>                 (non-individuals)
                 <NonIndividualName type="MN"><NonIndividualNameText/></NonIndividualName>
                 <BusinessAddress><AddressDetails><State/><Postcode/></AddressDetails></BusinessAddress>
        or     <LegalEntity>                (EntityTypeInd = IND, individual / sole trader)
                 <IndividualName type="LGL"><NameTitle/>?<GivenName/>{0,2}<FamilyName/></IndividualName>
                 <BusinessAddress>...</BusinessAddress>
        <ASICNumber ASICNumberType="...">ACN or ARBN</ASICNumber>?
        <GST status="ACT|CAN|NON" GSTStatusFromDate="YYYYMMDD"/>?
        <DGR DGRStatusFromDate="..." status="..."><NonIndividualName type="DGR">...</NonIndividualName></DGR>*
        <OtherEntity><NonIndividualName type="BN|TRD|OTN|DGR"><NonIndividualNameText/></NonIndividualName></OtherEntity>*
      </ABR>

There is no ANZSIC code anywhere in the public extract (the XSD has no such
element), so the Tier 1 slice is status + state only.

ASIC company register (data.gov.au dataset ``asic-companies``, CC BY 3.0 AU)
---------------------------------------------------------------------------
``company_YYYYMM.zip`` holding one tab-separated ``COMPANY_YYYYMM.csv`` (UTF-8
with BOM, CRLF). Columns: Company Name, ACN, Type, Class, Sub Class, Status,
Date of Registration, Date of Deregistration, Previous State of Registration,
State Registration number, Modified since last report, Current Name Indicator,
ABN, Current Name, Current Name Start Date. There is ONE ROW PER NAME: the
current name has Current Name Indicator = Y; each former name is its own row
with the indicator blank and Current Name / Current Name Start Date filled in.
Rows for one ACN are contiguous, so `AsicCompanyAdapter.parse` groups them into
one raw row per company and keeps the former names as a list (aliases).
"""

from __future__ import annotations

import csv
import io
import multiprocessing
import os
import re
import time
import zipfile
from collections import Counter
from collections.abc import Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, ClassVar

from lxml import etree

from bizgraph.domain.models import Identifier, IdScheme, PartyType, SourceRecord
from bizgraph.normalise.identifiers import AbnValidator, AcnValidator
from bizgraph.normalise.names import NameNormaliser
from bizgraph.sources.base import CsvSourceAdapter, LoadStats, RawRow, RejectRecord, SourceAdapter
from bizgraph.sources.registry import registry

if TYPE_CHECKING:
    from bizgraph.store.duckdb_store import DuckDBStore

_ABN = AbnValidator()
_ACN = AcnValidator()

ALL = "*"


def _env_set(name: str, default: str) -> frozenset[str] | None:
    """Comma list from the environment, upper-cased. ``*`` (or ``ALL``) means no filter (None)."""
    raw = os.environ.get(name, default)
    values = {v.strip().upper() for v in raw.split(",") if v.strip()}
    if not values or values & {ALL, "ALL"}:
        return None
    return frozenset(values)


def _as_filter(values: Iterable[str] | str | None, env: str, default: str) -> frozenset[str] | None:
    if values is None:
        return _env_set(env, default)
    if isinstance(values, str):
        values = values.split(",")
    cleaned = {v.strip().upper() for v in values if v and v.strip()}
    return None if not cleaned or cleaned & {ALL, "ALL"} else frozenset(cleaned)


def _yyyymmdd(value: str | None) -> str | None:
    """ABR dates are YYYYMMDD; 19000101 is the ABR's 'no date' sentinel."""
    if not value or value == "19000101" or len(value) != 8 or not value.isdigit():
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def _ddmmyyyy(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def _natural_key(name: str) -> list[Any]:
    """Sort 'public_split_1_10' before 'public_split_11_20'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _iter_members(path: Path, suffixes: tuple[str, ...]) -> Iterator[tuple[str, IO[bytes]]]:
    """Yield (name, binary stream) for every data file under `path`.

    `path` may be a directory (all zips and data files in it, sorted), a zip
    (every member with a matching suffix, read in place, never extracted), or a
    plain data file.
    """
    if path.is_dir():
        for child in sorted(path.iterdir(), key=lambda c: _natural_key(c.name)):
            if child.suffix.lower() == ".zip" or child.suffix.lower() in suffixes:
                yield from _iter_members(child, suffixes)
        return
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            for info in sorted(zf.infolist(), key=lambda i: _natural_key(i.filename)):
                if info.is_dir() or not info.filename.lower().endswith(suffixes):
                    continue
                with zf.open(info) as fh:
                    yield f"{path.name}!{info.filename}", fh
        return
    with path.open("rb") as fh:
        yield path.name, fh


def _list_members(path: Path, suffixes: tuple[str, ...]) -> list[tuple[Path, str | None]]:
    """(container, member) pairs in the same order `_iter_members` reads them.

    member is None for a plain data file. Used to fan members out to worker processes.
    """
    if path.is_dir():
        out: list[tuple[Path, str | None]] = []
        for child in sorted(path.iterdir(), key=lambda c: _natural_key(c.name)):
            if child.suffix.lower() == ".zip" or child.suffix.lower() in suffixes:
                out.extend(_list_members(child, suffixes))
        return out
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            infos = sorted(zf.infolist(), key=lambda i: _natural_key(i.filename))
            return [(path, i.filename) for i in infos if not i.is_dir() and i.filename.lower().endswith(suffixes)]
    return [(path, None)]


def _open_member(container: Path, member: str | None) -> Iterator[tuple[str, IO[bytes]]]:
    if member is None:
        with container.open("rb") as fh:
            yield container.name, fh
        return
    with zipfile.ZipFile(container) as zf, zf.open(member) as fh:
        yield f"{container.name}!{member}", fh


# --------------------------------------------------------------------------- ABR


def _text(el: etree._Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    t = el.text.strip()
    return t or None


def _abr_element_to_row(el: etree._Element) -> RawRow:
    abn_el = el.find("ABN")
    et = el.find("EntityType")
    row: RawRow = {
        "abn": _text(abn_el),
        "abn_status": abn_el.get("status") if abn_el is not None else None,
        "abn_status_from": abn_el.get("ABNStatusFromDate") if abn_el is not None else None,
        "record_last_updated": el.get("recordLastUpdatedDate"),
        "replaced": el.get("replaced"),
        "entity_type_code": _text(et.find("EntityTypeInd")) if et is not None else None,
        "entity_type_text": _text(et.find("EntityTypeText")) if et is not None else None,
        "organisation_name": None,
        "name_type": None,
        "name_title": None,
        "given_names": [],
        "family_name": None,
        "state": None,
        "postcode": None,
    }
    main = el.find("MainEntity")
    legal = el.find("LegalEntity")
    holder = main if main is not None else legal
    if main is not None:
        nin = main.find("NonIndividualName")
        if nin is not None:
            row["name_type"] = nin.get("type")
            row["organisation_name"] = _text(nin.find("NonIndividualNameText"))
    elif legal is not None:
        ind = legal.find("IndividualName")
        if ind is not None:
            row["name_type"] = ind.get("type")
            row["name_title"] = _text(ind.find("NameTitle"))
            row["given_names"] = [g for g in (_text(x) for x in ind.findall("GivenName")) if g]
            row["family_name"] = _text(ind.find("FamilyName"))
    if holder is not None:
        addr = holder.find("BusinessAddress/AddressDetails")
        if addr is not None:
            row["state"] = _text(addr.find("State"))
            row["postcode"] = _text(addr.find("Postcode"))

    asic = el.find("ASICNumber")
    row["asic_number"] = _text(asic)
    row["asic_number_type"] = asic.get("ASICNumberType") if asic is not None else None

    gst = el.find("GST")
    row["gst_status"] = gst.get("status") if gst is not None else None
    row["gst_status_from"] = gst.get("GSTStatusFromDate") if gst is not None else None

    row["dgr"] = [
        {
            "name": _text(d.find("NonIndividualName/NonIndividualNameText")),
            "status": d.get("status"),
            "status_from": d.get("DGRStatusFromDate"),
        }
        for d in el.findall("DGR")
    ]
    row["other_names"] = [
        {"type": n.get("type"), "name": _text(n.find("NonIndividualNameText"))}
        for n in el.findall("OtherEntity/NonIndividualName")
        if _text(n.find("NonIndividualNameText"))
    ]
    return row


@registry.register
class AbrAdapter(SourceAdapter):
    """ABR bulk extract. One SourceRecord per ABN, record_id = ABN.

    Slice (`accept`): ABN status in `statuses` and business-address state in
    `states`. Defaults come from env vars ``BIZGRAPH_ABR_STATUSES`` (default
    ``ACT``) and ``BIZGRAPH_ABR_STATES`` (default ``WA,TAS``). ``*`` disables
    either filter.

    Active ABNs per business-address state, extract of 2026-11-11 (20,658,780
    ABNs in total, 8,938,907 active): NSW 2,924,097; VIC 2,461,919;
    QLD 1,750,162; WA 888,197; SA 569,043; TAS 135,068; ACT 127,667;
    NT 55,625; blank 27,129. WA + TAS active = 1,023,265.
    """

    source_id: ClassVar[str] = "abr"
    tier: ClassVar[int] = 1
    licence: ClassVar[str] = "CC BY 3.0 AU"
    description: ClassVar[str] = "ABN Lookup bulk extract (data.gov.au abn-bulk-extract), weekly XML"

    DEFAULT_STATES: ClassVar[str] = "WA,TAS"
    DEFAULT_STATUSES: ClassVar[str] = "ACT"
    PERSON_ENTITY_TYPES: ClassVar[frozenset[str]] = frozenset({"IND"})

    OUTSIDE_SLICE: ClassVar[str] = "_outside_slice"

    def __init__(
        self,
        normaliser: NameNormaliser | None = None,
        states: Iterable[str] | str | None = None,
        statuses: Iterable[str] | str | None = None,
        abn_allowlist: Iterable[str] | None = None,
        acn_allowlist: Iterable[str] | None = None,
    ) -> None:
        super().__init__(normaliser)
        self.states = _as_filter(states, "BIZGRAPH_ABR_STATES", self.DEFAULT_STATES)
        self.statuses = _as_filter(statuses, "BIZGRAPH_ABR_STATUSES", self.DEFAULT_STATUSES)
        # Slice extension: ABNs / ACNs referenced elsewhere (the Tier 2 registers) are
        # kept whatever their state or status.
        self.abn_allowlist = frozenset(abn_allowlist or ())
        self.acn_allowlist = frozenset(acn_allowlist or ())

    def in_state_slice(self, status: str | None, state: str | None) -> bool:
        if self.statuses is not None and (status or "").upper() not in self.statuses:
            return False
        if self.states is not None and (state or "").strip().upper() not in self.states:
            return False
        return True

    def _allowlisted(self, abn: str | None, acn: str | None) -> bool:
        return bool((abn and abn in self.abn_allowlist) or (acn and acn in self.acn_allowlist))

    def _prefilter_outside(self, el: etree._Element) -> str | None:
        """Cheap slice check on the raw element, before building the full row.

        Returns the ABN text when the element is certainly outside the slice (valid
        ABN, wrong status or state, not allowlisted), else None (build the full row).
        An invalid or missing ABN is never pre-filtered, so `to_record` still counts
        it under its own rejection reason.
        """
        if self.statuses is None and self.states is None:
            return None
        abn_el = el.find("ABN")
        if abn_el is None:
            return None
        state = el.findtext("MainEntity/BusinessAddress/AddressDetails/State")
        if state is None:
            state = el.findtext("LegalEntity/BusinessAddress/AddressDetails/State")
        if self.in_state_slice(abn_el.get("status"), state):
            return None
        abn_text = (abn_el.text or "").strip()
        abn = _ABN.parse(abn_text) if abn_text else None
        if abn is None:
            return None
        if abn.value in self.abn_allowlist:
            return None
        if self.acn_allowlist:
            asic = (el.findtext("ASICNumber") or "").strip()
            acn = _ACN.parse(asic) if asic else None
            if acn is not None and acn.value in self.acn_allowlist:
                return None
        return abn_text

    def _parse_stream(self, member: str, fh: IO[bytes]) -> Iterator[RawRow]:
        context = etree.iterparse(fh, events=("end",), tag="ABR", huge_tree=True)
        for _, el in context:
            outside = self._prefilter_outside(el)
            if outside is not None:
                # Lightweight sentinel: counted in records_in, rejected as outside_slice.
                row: RawRow = {"abn": outside, self.OUTSIDE_SLICE: True}
            else:
                row = _abr_element_to_row(el)
            row["_source_file"] = member
            # Free memory: clear this element and drop already-processed siblings.
            el.clear(keep_tail=False)
            parent = el.getparent()
            if parent is not None:
                while el.getprevious() is not None:
                    del parent[0]
            yield row
        del context

    def parse(self, path: Path) -> Iterator[RawRow]:
        for member, fh in _iter_members(Path(path), (".xml",)):
            yield from self._parse_stream(member, fh)

    def _config(self) -> dict[str, Any]:
        return {
            "states": sorted(self.states) if self.states is not None else ALL,
            "statuses": sorted(self.statuses) if self.statuses is not None else ALL,
            "abn_allowlist": sorted(self.abn_allowlist),
            "acn_allowlist": sorted(self.acn_allowlist),
        }

    def run_parallel(
        self, path: Path, snapshot_date: date, store: DuckDBStore, workers: int | None = None,
        force: bool = False,
    ) -> LoadStats:
        """Same contract as `run()` (snapshot-hash skip, stats, snapshot row), but each XML
        member is parsed and mapped in its own worker process. This process stays the only
        DuckDB writer: it upserts each member's accepted records, in member order.
        """
        workers = workers if workers is not None else max(1, (os.cpu_count() or 2) - 2)
        if workers <= 1:
            return self.run(path, snapshot_date, store, force=force)
        started = time.perf_counter()
        stats = LoadStats(self.source_id, snapshot_date)
        path = Path(path)
        file_hash = store.snapshots.file_hash(path)
        if not force and store.snapshots.exists(self.source_id, file_hash):
            stats.skipped_snapshot = True
            stats.wall_clock_s = time.perf_counter() - started
            return stats

        members = _list_members(path, (".xml",))
        with ProcessPoolExecutor(
            max_workers=min(workers, max(1, len(members))),
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_abr_worker_init,
            initargs=(self._config(),),
        ) as pool:
            tasks = [(str(c), m, snapshot_date) for c, m in members]
            for records_in, reasons, records in pool.map(_abr_worker_parse, tasks):
                stats.records_in += records_in
                stats.records_rejected += sum(reasons.values())
                stats.rejection_reasons.update(reasons)
                for i in range(0, len(records), self.batch_size):
                    self._flush(records[i : i + self.batch_size], store, stats)

        stats.wall_clock_s = time.perf_counter() - started
        store.snapshots.record(self.source_id, snapshot_date, file_hash, path, stats)
        return stats

    @classmethod
    def shared_acn_abns(cls, path: Path, workers: int | None = None) -> dict[str, list[str]]:
        """Full-extract scan: every ACN that ABR gives as the OWN ACN (`_owns_acn`) of two or
        more ABNs, mapped to those ABNs. Adding them to the allowlist puts both sides of each
        "one ACN on two ABNs" case into the store, so the canonical build can quarantine it
        even when only one side falls in the state slice."""
        members = _list_members(Path(path), (".xml",))
        workers = workers if workers is not None else max(1, (os.cpu_count() or 2) - 2)
        tasks = [(str(c), m) for c, m in members]
        first: dict[str, str] = {}
        shared: dict[str, set[str]] = {}
        if workers <= 1:
            results = map(_abr_worker_acn_scan, tasks)
            for pairs in results:
                cls._merge_acn_pairs(pairs, first, shared)
        else:
            with ProcessPoolExecutor(
                max_workers=min(workers, max(1, len(members))),
                mp_context=multiprocessing.get_context("spawn"),
            ) as pool:
                for pairs in pool.map(_abr_worker_acn_scan, tasks):
                    cls._merge_acn_pairs(pairs, first, shared)
        return {acn: sorted(abns) for acn, abns in sorted(shared.items())}

    @staticmethod
    def _merge_acn_pairs(pairs: list[tuple[str, str]], first: dict[str, str], shared: dict[str, set[str]]) -> None:
        for acn, abn in pairs:
            prev = first.setdefault(acn, abn)
            if prev != abn:
                shared.setdefault(acn, {prev}).add(abn)

    def to_record(self, row: RawRow, snapshot_date: date) -> SourceRecord:
        if row.get(self.OUTSIDE_SLICE):
            raise RejectRecord("outside_slice")
        abn_raw = row.get("abn")
        if not abn_raw:
            raise RejectRecord("missing_abn")
        abn = _ABN.parse(abn_raw)
        if abn is None:
            raise RejectRecord("invalid_abn_checksum")

        entity_type = row.get("entity_type_code")
        is_person = entity_type in self.PERSON_ENTITY_TYPES
        if is_person:
            parts = [*row.get("given_names", []), row.get("family_name") or ""]
            name_raw = " ".join(p for p in parts if p).strip() or None
        else:
            name_raw = row.get("organisation_name")
        if not name_raw:
            raise RejectRecord("missing_name")

        identifiers: list[Identifier] = [abn]
        acn = None
        unverified = None
        if row.get("asic_number"):
            acn = _ACN.parse(row["asic_number"])
            if acn is not None and not self._owns_acn(entity_type, row.get("entity_type_text"), abn.value, acn.value):
                # A trust / partnership / individual carrying another body's ACN (e.g. the
                # corporate trustee's): evidence only, never this party's identifier.
                unverified, acn = acn.value, None
            if acn is not None:
                identifiers.append(acn)

        norm = self.names.normalise_person(name_raw) if is_person else self.names.normalise(name_raw)
        payload: dict[str, Any] = {
            "abn": abn.value,
            "abn_status": row.get("abn_status"),
            "abn_status_from": _yyyymmdd(row.get("abn_status_from")),
            "record_last_updated": _yyyymmdd(row.get("record_last_updated")),
            "replaced": row.get("replaced"),
            "entity_type_code": entity_type,
            "entity_type_text": row.get("entity_type_text"),
            "name_type": row.get("name_type"),
            "organisation_name": row.get("organisation_name"),
            "name_title": row.get("name_title"),
            "given_names": list(row.get("given_names") or []),
            "family_name": row.get("family_name"),
            "state": row.get("state"),
            "postcode": row.get("postcode"),
            "asic_number": row.get("asic_number"),
            "asic_number_type": row.get("asic_number_type"),
            "asic_number_valid": acn is not None or unverified is not None,
            "gst_status": row.get("gst_status"),
            "gst_status_from": _yyyymmdd(row.get("gst_status_from")),
            "dgr": [
                {**d, "status_from": _yyyymmdd(d.get("status_from"))} for d in row.get("dgr") or []
            ],
            # Business names (BN), trading names (TRD), other names (OTN), DGR names: alias candidates.
            "other_names": list(row.get("other_names") or []),
        }
        if unverified is not None:  # only when present, so other records' content hashes are unchanged
            payload["asic_number_unverified"] = unverified
        return SourceRecord(
            source=self.source_id,
            record_id=abn.value,
            snapshot_date=snapshot_date,
            payload=payload,
            name_raw=name_raw,
            name_norm=norm.norm if norm else None,
            party_type=PartyType.PERSON if is_person else PartyType.ORGANISATION,
            identifiers=tuple(identifiers),
        )

    COMPANY_ENTITY_TYPES: ClassVar[frozenset[str]] = frozenset({"PRV", "PUB"})

    @classmethod
    def _owns_acn(cls, entity_type: str | None, entity_text: str | None, abn: str, acn: str) -> bool:
        """An ABR ASICNumber is this party's own ACN only for a company (PRV, PUB, or a
        government company: [C|S|L|T]C? codes such as SCR State Government Private Company),
        or when the ABN is built on it (ABN[2:] == ACN). Never for an individual. Decided on
        the entity type code; the text is not trusted."""
        if entity_type in cls.PERSON_ENTITY_TYPES:
            return False
        if entity_type in cls.COMPANY_ENTITY_TYPES or re.fullmatch(r"[CSLT]C[A-Z]", entity_type or ""):
            return True
        return abn[2:] == acn

    def accept(self, record: SourceRecord) -> bool:
        p = record.payload
        if self.in_state_slice(p.get("abn_status"), p.get("state")):
            return True
        return self._allowlisted(record.record_id, record.identifier(IdScheme.ACN))


# Worker side of AbrAdapter.run_parallel (module level so a spawned process can import it).
_WORKER_ADAPTER: AbrAdapter | None = None


def _abr_worker_acn_scan(task: tuple[str, str | None]) -> list[tuple[str, str]]:
    """(own ACN, ABN) for every ABR element of one member; no row dicts are built."""
    container, member = task
    out: list[tuple[str, str]] = []
    for _name, fh in _open_member(Path(container), member):
        context = etree.iterparse(fh, events=("end",), tag="ABR", huge_tree=True)
        for _, el in context:
            asic = el.findtext("ASICNumber")
            if asic and asic.strip():
                abn = _ABN.parse((el.findtext("ABN") or "").strip())
                acn = _ACN.parse(asic.strip())
                if abn is not None and acn is not None and AbrAdapter._owns_acn(
                    (el.findtext("EntityType/EntityTypeInd") or "").strip(), None, abn.value, acn.value
                ):
                    out.append((acn.value, abn.value))
            el.clear(keep_tail=False)
            parent = el.getparent()
            if parent is not None:
                while el.getprevious() is not None:
                    del parent[0]
        del context
    return out


def _abr_worker_init(config: dict[str, Any]) -> None:
    global _WORKER_ADAPTER
    _WORKER_ADAPTER = AbrAdapter(**config)


def _abr_worker_parse(task: tuple[str, str | None, date]) -> tuple[int, Counter, list[SourceRecord]]:
    container, member, snapshot_date = task
    adapter = _WORKER_ADAPTER
    if adapter is None:
        raise RuntimeError("ABR worker not initialised")
    records_in, reasons, records = 0, Counter(), []
    for name, fh in _open_member(Path(container), member):
        for row in adapter._parse_stream(name, fh):
            records_in += 1
            try:
                record = adapter.to_record(row, snapshot_date)
            except RejectRecord as exc:
                reasons[str(exc)] += 1
                continue
            if not adapter.accept(record):
                reasons["outside_slice"] += 1
                continue
            records.append(record)
    return records_in, reasons, records


# --------------------------------------------------------------------------- ASIC


@registry.register
class AsicCompanyAdapter(CsvSourceAdapter):
    """ASIC company register. One SourceRecord per ACN (name rows grouped), record_id = ACN.

    Slice (`accept`): company status in `statuses` (env ``BIZGRAPH_ASIC_STATUSES``,
    default ``*`` = all; ``REGD`` keeps registered companies only) and, when given,
    ACN in `acn_allowlist` (e.g. the ACNs of the ABR slice). The file has no
    usable state column (Previous State of Registration is blank for ~93% of
    rows), so a state slice has to come through the ABR join.
    """

    source_id: ClassVar[str] = "asic_company"
    tier: ClassVar[int] = 1
    licence: ClassVar[str] = "CC BY 3.0 AU"
    description: ClassVar[str] = "ASIC company dataset (data.gov.au asic-companies), weekly TSV"
    delimiter: ClassVar[str] = "\t"

    DEFAULT_STATUSES: ClassVar[str] = ALL
    ARBN_TYPES: ClassVar[frozenset[str]] = frozenset({"FNOS", "RACN"})

    def __init__(
        self,
        normaliser: NameNormaliser | None = None,
        statuses: Iterable[str] | str | None = None,
        acn_allowlist: Iterable[str] | None = None,
    ) -> None:
        super().__init__(normaliser)
        self.statuses = _as_filter(statuses, "BIZGRAPH_ASIC_STATUSES", self.DEFAULT_STATUSES)
        self.acn_allowlist = frozenset(acn_allowlist) if acn_allowlist is not None else None

    def _rows(self, path: Path) -> Iterator[dict[str, str]]:
        for _member, fh in _iter_members(Path(path), (".csv", ".tsv", ".txt")):
            text = io.TextIOWrapper(fh, encoding=self.encoding, errors="replace", newline="")
            reader = csv.DictReader(text, delimiter=self.delimiter)
            for row in reader:
                yield {(k or "").strip(): (v.strip() if isinstance(v, str) else "") for k, v in row.items()}

    def _split_acns(self, path: Path) -> set[str]:
        """ACNs whose rows are not contiguous (a cheap first pass over the ACN column only)."""
        seen: set[str] = set()
        split: set[str] = set()
        prev = None
        for _member, fh in _iter_members(Path(path), (".csv", ".tsv", ".txt")):
            text = io.TextIOWrapper(fh, encoding=self.encoding, errors="replace", newline="")
            reader = csv.reader(text, delimiter=self.delimiter)
            header = [(h or "").strip().lstrip("﻿") for h in next(reader, [])]
            if "ACN" not in header:
                continue
            i = header.index("ACN")
            for rec in reader:
                acn = rec[i].strip() if i < len(rec) else ""
                if acn != prev:
                    if acn in seen:
                        split.add(acn)
                    seen.add(acn)
                    prev = acn
        return split

    def parse(self, path: Path) -> Iterator[RawRow]:
        """Group the per-name rows of one ACN into a single raw row.

        The register is ACN-contiguous in practice, so groups stream. Grouping does not
        depend on it: ACNs whose rows are split (found by a first pass) are buffered and
        emitted, fully grouped, at the end.
        """
        split = self._split_acns(path)
        buffered: dict[str, list[dict[str, str]]] = {}
        group: list[dict[str, str]] = []
        for row in self._rows(path):
            acn = row.get("ACN") or ""
            if acn in split:
                buffered.setdefault(acn, []).append(row)
                continue
            if group and acn != group[0].get("ACN"):
                yield self._group(group)
                group = []
            group.append(row)
        if group:
            yield self._group(group)
        for rows in buffered.values():
            yield self._group(rows)

    @staticmethod
    def _group(rows: list[dict[str, str]]) -> RawRow:
        current = [r for r in rows if r.get("Current Name Indicator", "").upper() == "Y"]
        former = [r for r in rows if r.get("Current Name Indicator", "").upper() != "Y"]
        base = current[0] if current else rows[0]
        if current:
            current_name = current[0].get("Company Name")
        else:
            # No Y row: former rows still carry the current name in "Current Name".
            current_name = next((r["Current Name"] for r in former if r.get("Current Name")), None)
            current_name = current_name or base.get("Company Name")
        return {
            "acn": base.get("ACN"),
            "current_name": current_name,
            "current_name_rows": len(current),
            "type": base.get("Type"),
            "class": base.get("Class"),
            "sub_class": base.get("Sub Class"),
            "status": base.get("Status"),
            "date_of_registration": base.get("Date of Registration"),
            "date_of_deregistration": base.get("Date of Deregistration"),
            "previous_state_of_registration": base.get("Previous State of Registration"),
            "state_registration_number": base.get("State Registration number"),
            "modified_since_last_report": base.get("Modified since last report"),
            "abn": base.get("ABN"),
            "current_name_start_date": next(
                (r["Current Name Start Date"] for r in former if r.get("Current Name Start Date")), None
            ),
            "former_names": [r.get("Company Name") for r in former if r.get("Company Name")],
        }

    def to_record(self, row: RawRow, snapshot_date: date) -> SourceRecord:
        acn_raw = row.get("acn")
        if not acn_raw:
            raise RejectRecord("missing_acn")
        acn = _ACN.parse(acn_raw)
        if acn is None:
            raise RejectRecord("invalid_acn_checksum")
        name_raw = row.get("current_name")
        if not name_raw:
            raise RejectRecord("missing_name")

        # Registered foreign companies (FNOS) and registered Australian bodies (RACN) carry an
        # ARBN in the ACN column: same check digit, different identifier kind.
        if (row.get("type") or "").upper() in self.ARBN_TYPES:
            acn = Identifier(IdScheme.ARBN, acn.value)
        identifiers: list[Identifier] = [acn]
        abn_field = (row.get("abn") or "").strip()
        abn = _ABN.parse(abn_field) if abn_field not in ("", "0") else None
        if abn is not None:
            identifiers.append(abn)

        current_start = _ddmmyyyy(row.get("current_name_start_date"))
        former = []
        seen = {name_raw.upper()}
        for name in row.get("former_names") or []:
            if name.upper() in seen:
                continue
            seen.add(name.upper())
            former.append(name)

        norm = self.names.normalise(name_raw)
        payload: dict[str, Any] = {
            "acn": acn.value,
            "name": name_raw,
            "current_name_start_date": current_start,
            # Former names: the file gives no per-name dates, only that they were all
            # replaced on or before current_name_start_date. Alias candidates.
            "former_names": former,
            "type": row.get("type") or None,
            "class": row.get("class") or None,
            "sub_class": row.get("sub_class") or None,
            "status": row.get("status") or None,
            "date_of_registration": _ddmmyyyy(row.get("date_of_registration")),
            "date_of_deregistration": _ddmmyyyy(row.get("date_of_deregistration")),
            "previous_state_of_registration": row.get("previous_state_of_registration") or None,
            "state_registration_number": row.get("state_registration_number") or None,
            "abn": abn.value if abn else None,
            "abn_raw_invalid": abn_field if (abn is None and abn_field not in ("", "0")) else None,
            "no_current_name_row": row.get("current_name_rows", 1) == 0,
        }
        return SourceRecord(
            source=self.source_id,
            record_id=acn.value,
            snapshot_date=snapshot_date,
            payload=payload,
            name_raw=name_raw,
            name_norm=norm.norm if norm else None,
            party_type=PartyType.ORGANISATION,
            identifiers=tuple(identifiers),
        )

    def accept(self, record: SourceRecord) -> bool:
        if self.statuses is not None and (record.payload.get("status") or "").upper() not in self.statuses:
            return False
        if self.acn_allowlist is not None and record.record_id not in self.acn_allowlist:
            return False
        return True
