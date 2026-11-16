"""Tier 1 adapters against small fixtures that mirror the real file layouts."""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from bizgraph.domain.models import IdScheme, PartyType
from bizgraph.sources import RejectRecord, registry
from bizgraph.sources.adapters import AbrAdapter, AsicCompanyAdapter

FIX = Path(__file__).parent / "fixtures"
ABR_ZIP = FIX / "abr" / "public_split_1_2.zip"
ABR_XML_DIR = FIX / "abr" / "xml"
ASIC_ZIP = FIX / "asic_company" / "company_202611.zip"
ASIC_TSV = FIX / "asic_company" / "tsv" / "COMPANY_202611.csv"
SNAP = date(2026, 11, 11)


def _load(adapter, path):
    """Mimic SourceAdapter.run without a store: returns (accepted records, rejection reasons)."""
    accepted, reasons = [], Counter()
    for row in adapter.parse(path):
        try:
            rec = adapter.to_record(row, SNAP)
        except RejectRecord as exc:
            reasons[str(exc)] += 1
            continue
        if not adapter.accept(rec):
            reasons["outside_slice"] += 1
            continue
        accepted.append(rec)
    return accepted, reasons


# --------------------------------------------------------------------------- registry


def test_adapters_registered():
    assert isinstance(registry.get("abr"), AbrAdapter)
    assert isinstance(registry.get("asic_company"), AsicCompanyAdapter)
    assert AbrAdapter.tier == AsicCompanyAdapter.tier == 1


# --------------------------------------------------------------------------- ABR


def test_abr_parses_every_member_of_the_zip():
    rows = list(AbrAdapter().parse(ABR_ZIP))
    assert len(rows) == 6
    assert rows[0]["_source_file"].endswith("20261111_Public01.xml")
    assert rows[-1]["_source_file"].endswith("20261111_Public02.xml")


def test_abr_zip_and_plain_xml_agree():
    a = AbrAdapter()
    from_zip = [r["abn"] for r in a.parse(ABR_ZIP)]
    from_xml = [r["abn"] for r in a.parse(ABR_XML_DIR)]
    assert from_zip == from_xml


def test_abr_invalid_abn_rejected_with_reason():
    a = AbrAdapter()
    bad = next(r for r in a.parse(ABR_ZIP) if r["abn"] == "12345678901")
    with pytest.raises(RejectRecord, match="invalid_abn_checksum"):
        a.to_record(bad, SNAP)


def test_abr_company_record():
    a = AbrAdapter(states="*", statuses="*")
    recs = {r.record_id: r for r in _load(a, ABR_ZIP)[0]}
    co = recs["89000000019"]
    assert co.party_type == PartyType.ORGANISATION
    assert co.name_raw == "MONAKA PTY LTD"
    assert co.name_norm == "MONAKA"
    assert co.identifier(IdScheme.ABN) == "89000000019"
    assert co.identifier(IdScheme.ACN) == "000000019"
    p = co.payload
    assert (p["state"], p["postcode"], p["abn_status"]) == ("WA", "6000", "ACT")
    assert p["abn_status_from"] == "2000-01-01"
    assert p["entity_type_code"] == "PRV"
    assert p["gst_status"] == "ACT" and p["gst_status_from"] == "2000-07-01"
    assert p["other_names"] == [
        {"type": "BN", "name": "MONAKA CATERING"},
        {"type": "TRD", "name": "Monaka Foods"},
    ]
    assert "_source_file" not in p  # payload must not depend on file naming (content hash)


def test_abr_individual_is_person():
    a = AbrAdapter(states="*", statuses="*")
    recs = {r.record_id: r for r in _load(a, ABR_ZIP)[0]}
    ind = recs["55459246582"]
    assert ind.party_type == PartyType.PERSON
    assert ind.name_raw == "A S M KARIM ZOBAYER"
    assert ind.payload["given_names"] == ["A S M", "KARIM"]
    assert ind.payload["family_name"] == "ZOBAYER"
    assert ind.payload["name_title"] == "MR"
    assert ind.identifier(IdScheme.ACN) is None
    assert ind.payload["gst_status_from"] is None  # 19000101 sentinel


def test_abr_invalid_asic_number_not_used_as_acn():
    a = AbrAdapter(states="*", statuses="*")
    recs = {r.record_id: r for r in _load(a, ABR_ZIP)[0]}
    rec = recs["91000000028"]
    assert rec.identifier(IdScheme.ACN) is None
    assert rec.payload["asic_number"] == "123456789"
    assert rec.payload["asic_number_valid"] is False


def test_abr_dgr_captured():
    a = AbrAdapter(states="*", statuses="*")
    recs = {r.record_id: r for r in _load(a, ABR_ZIP)[0]}
    assert recs["33051775556"].payload["dgr"] == [
        {"name": "SYDNEY CHARITY GIFT FUND", "status": None, "status_from": "2012-01-01"}
    ]


def test_abr_slice_filter_default_active_and_states():
    a = AbrAdapter(states="WA,SA", statuses="ACT")
    accepted, reasons = _load(a, ABR_ZIP)
    # ACT+WA company, ACT+SA individual, ACT+SA company kept; CAN WA and ACT NSW dropped.
    assert sorted(r.record_id for r in accepted) == ["55459246582", "89000000019", "91000000028"]
    assert reasons == Counter({"invalid_abn_checksum": 1, "outside_slice": 2})


def test_abr_slice_from_env(monkeypatch):
    monkeypatch.setenv("BIZGRAPH_ABR_STATES", "nsw")
    a = AbrAdapter()
    assert a.states == frozenset({"NSW"}) and a.statuses == frozenset({"ACT"})
    accepted, _ = _load(a, ABR_ZIP)
    assert [r.record_id for r in accepted] == ["33051775556"]

    monkeypatch.setenv("BIZGRAPH_ABR_STATES", "*")
    monkeypatch.setenv("BIZGRAPH_ABR_STATUSES", "*")
    a = AbrAdapter()
    assert a.states is None and a.statuses is None
    assert len(_load(a, ABR_ZIP)[0]) == 5


def test_abr_content_hash_stable_across_runs():
    a = AbrAdapter(states="*", statuses="*")
    h1 = {r.record_id: r.content_hash for r in _load(a, ABR_ZIP)[0]}
    h2 = {r.record_id: r.content_hash for r in _load(a, ABR_XML_DIR)[0]}
    assert h1 == h2


# --------------------------------------------------------------------------- ASIC


def test_asic_groups_name_rows_per_acn():
    rows = list(AsicCompanyAdapter().parse(ASIC_ZIP))
    assert [r["acn"] for r in rows] == [
        "000000019", "000000028", "000000117", "000000260", "000000331", "123456789", "004085616",
    ]


def test_asic_zip_and_tsv_agree():
    a = AsicCompanyAdapter()
    assert list(a.parse(ASIC_ZIP)) == list(a.parse(ASIC_TSV))


def test_asic_former_names_and_identifiers():
    accepted, reasons = _load(AsicCompanyAdapter(statuses="*"), ASIC_ZIP)
    recs = {r.record_id: r for r in accepted}
    assert reasons == Counter({"invalid_acn_checksum": 1})

    m = recs["000000019"]
    assert m.name_raw == "MONAKA PTY LTD"
    assert m.party_type == PartyType.ORGANISATION
    assert m.identifier(IdScheme.ACN) == "000000019"
    assert m.identifier(IdScheme.ABN) == "89000000019"
    assert m.payload["former_names"] == ["LOVINI HOLDINGS PTY LTD"]
    assert m.payload["current_name_start_date"] == "2016-01-28"
    assert m.payload["date_of_registration"] == "1990-01-08"
    assert (m.payload["type"], m.payload["class"], m.payload["sub_class"]) == ("APTY", "LMSH", "PROP")

    o = recs["000000331"]
    assert o.name_raw == "ORIGIN (LGC) (AUST) PTY LIMITED"
    assert o.payload["former_names"] == ["BORAL (L G C) (AUST) LTD", "BROKEN HILL & SUBURBAN GAS CO LTD"]

    bnp = recs["000000117"]
    assert bnp.name_raw == "BNP PARIBAS"  # fixed-width padding stripped
    assert bnp.payload["former_names"] == ["BANQUE NATIONALE DE PARIS"]
    assert bnp.payload["state_registration_number"] == "00002239"


def test_asic_deregistered_and_missing_abn():
    recs = {r.record_id: r for r in _load(AsicCompanyAdapter(statuses="*"), ASIC_ZIP)[0]}
    d = recs["000000260"]
    assert d.payload["status"] == "DRGD"
    assert d.payload["date_of_deregistration"] == "2026-03-13"
    assert d.identifier(IdScheme.ABN) is None  # "0" means no ABN
    assert d.payload["abn_raw_invalid"] is None


def test_asic_no_current_row_uses_current_name_column():
    recs = {r.record_id: r for r in _load(AsicCompanyAdapter(statuses="*"), ASIC_ZIP)[0]}
    r = recs["004085616"]
    assert r.name_raw == "RENAMED HOLDINGS PTY LTD"
    assert r.payload["former_names"] == ["NO CURRENT ROW PTY LTD"]
    assert r.payload["no_current_name_row"] is True
    assert r.identifier(IdScheme.ABN) is None
    assert r.payload["abn_raw_invalid"] == "12345678901"


def test_asic_slice_status_and_allowlist(monkeypatch):
    monkeypatch.setenv("BIZGRAPH_ASIC_STATUSES", "REGD")
    accepted, reasons = _load(AsicCompanyAdapter(), ASIC_ZIP)
    assert "000000260" not in {r.record_id for r in accepted}
    assert reasons["outside_slice"] == 1

    a = AsicCompanyAdapter(statuses="*", acn_allowlist={"000000019", "000000331"})
    assert sorted(r.record_id for r in _load(a, ASIC_ZIP)[0]) == ["000000019", "000000331"]
