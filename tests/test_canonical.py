"""CanonicalBuilder on small synthetic Tier 1 + Tier 2 records."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from bizgraph.domain.models import Identifier, IdScheme, PartyType, SourceRecord
from bizgraph.normalise.identifiers import AbnValidator, AcnValidator
from bizgraph.normalise.names import NameNormaliser
from bizgraph.pipeline.canonical import INVARIANTS, CanonicalBuilder, tier2_reference_ids
from bizgraph.store.duckdb_store import DuckDBStore

SNAP = date(2026, 11, 11)
_NAMES = NameNormaliser()
_ABN_V, _ACN_V = AbnValidator(), AcnValidator()


def make_acn(base: int) -> str:
    for d in range(10):
        v = f"{base:08d}{d}"
        if _ACN_V.is_valid(v):
            return v
    raise AssertionError(base)


def make_abn(acn: str) -> str:
    for prefix in range(10, 100):
        if _ABN_V.is_valid(f"{prefix}{acn}"):
            return f"{prefix}{acn}"
    raise AssertionError(acn)


def _norm(name: str) -> str:
    return _NAMES.normalise(name).norm


def abr(abn, name, acn=None, state="WA", status="ACT", status_from="2001-02-03",
        other_names=(), person=False) -> SourceRecord:
    ids = [Identifier(IdScheme.ABN, abn)] + ([Identifier(IdScheme.ACN, acn)] if acn else [])
    payload = {
        "abn": abn, "abn_status": status, "abn_status_from": status_from,
        "entity_type_code": "IND" if person else "PRV",
        "entity_type_text": "Individual/Sole Trader" if person else "Australian Private Company",
        "organisation_name": None if person else name, "state": state, "postcode": "6000",
        "asic_number": acn, "other_names": [{"type": t, "name": n} for t, n in other_names], "dgr": [],
    }
    return SourceRecord("abr", abn, SNAP, payload, name, _norm(name),
                        PartyType.PERSON if person else PartyType.ORGANISATION, tuple(ids))


def asic(acn, name, abn=None, status="REGD", former=(), reg="1990-01-08", dereg=None) -> SourceRecord:
    ids = [Identifier(IdScheme.ACN, acn)] + ([Identifier(IdScheme.ABN, abn)] if abn else [])
    payload = {
        "acn": acn, "name": name, "abn": abn, "status": status, "type": "APTY", "class": "LMSH",
        "former_names": list(former), "date_of_registration": reg, "date_of_deregistration": dereg,
    }
    return SourceRecord("asic_company", acn, SNAP, payload, name, _norm(name), PartyType.ORGANISATION, tuple(ids))


def afsl(lic, name, acn=None, abn=None) -> SourceRecord:
    ids = [Identifier(IdScheme.AFSL, lic)]
    ids += [Identifier(IdScheme.ACN, acn)] if acn else []
    ids += [Identifier(IdScheme.ABN, abn)] if abn else []
    return SourceRecord("asic_afsl", lic, SNAP, {"licence": lic, "name": name}, name, _norm(name),
                        PartyType.ORGANISATION, tuple(ids))


# Numbers
ACN_OK, ACN_T2, ACN_MULTI, ACN_DIS, ACN_NAME, ACN_C4A, ACN_C4B, ACN_FORMER, ACN_REV = (
    make_acn(b) for b in (1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008, 1009)
)
ABN_OK = make_abn(ACN_OK)
ABN_NSW = make_abn(make_acn(2001))
ABN_PERSON = make_abn(make_acn(2002))
ABN_M1, ABN_M2 = make_abn(ACN_MULTI), make_abn(make_acn(2003))
ABN_DIS_X, ABN_DIS_Z = make_abn(ACN_DIS), make_abn(make_acn(2004))
ABN_NAME = make_abn(ACN_NAME)
ABN_C4 = make_abn(make_acn(2005))
ABN_FORMER = make_abn(ACN_FORMER)
ABN_OUT = make_abn(make_acn(2006))


@pytest.fixture
def store(tmp_path: Path) -> DuckDBStore:
    s = DuckDBStore(tmp_path / "c.duckdb")
    s.records.upsert([
        # clean ABR + ASIC join on ACN, with aliases on both sides
        abr(ABN_OK, "Monaka Pty Ltd", ACN_OK, other_names=[("BN", "Monaka Catering"), ("TRD", "Monaka Foods")]),
        asic(ACN_OK, "MONAKA PTY LTD", ABN_OK, former=["LOVINI HOLDINGS PTY LTD"]),
        # Tier 2 referenced, cancelled, outside the state slice
        abr(ABN_NSW, "Harbour Advisers Pty Ltd", state="NSW", status="CAN", status_from="2019-05-06"),
        abr(ABN_PERSON, "JANE CITIZEN", person=True),
        # ASIC-only party via Tier 2 reference
        asic(ACN_T2, "OFFSHORE CUSTODY PTY LTD", None, status="DRGD", reg="2005-01-01", dereg="2020-01-01"),
        # ACN under two ABNs
        abr(ABN_M1, "Twin One Pty Ltd", ACN_MULTI),
        abr(ABN_M2, "Twin Two Pty Ltd", ACN_MULTI, status="ACT"),
        asic(ACN_MULTI, "TWIN ONE PTY LTD", ABN_M1),
        # ABR ACN vs ASIC ABN disagree (Z is an ABR party too)
        abr(ABN_DIS_X, "Disputed Holdings Pty Ltd", ACN_DIS),
        abr(ABN_DIS_Z, "Disputed Holdings Pty Ltd"),
        asic(ACN_DIS, "DISPUTED HOLDINGS PTY LTD", ABN_DIS_Z),
        # identifiers agree, names clearly different
        abr(ABN_NAME, "Zebra Farms Pty Ltd", ACN_NAME),
        asic(ACN_NAME, "QUANTUM ROBOTICS PTY LTD", ABN_NAME),
        # ABR has no ACN; two ASIC companies claim the ABN
        abr(ABN_C4, "Claimed Twice Pty Ltd"),
        asic(ACN_C4A, "CLAIMED TWICE PTY LTD", ABN_C4),
        asic(ACN_C4B, "CLAIMED TWICE AGAIN PTY LTD", ABN_C4),
        # names differ, but ABR's name is an ASIC former name: not a mismatch
        abr(ABN_FORMER, "Old Name Traders Pty Ltd", ACN_FORMER),
        asic(ACN_FORMER, "NEW BRAND VENTURES PTY LTD", ABN_FORMER, former=["OLD NAME TRADERS PTY LTD"]),
        # ASIC company outside every slice: evidence only, never a party
        asic(make_acn(3001), "UNRELATED PTY LTD", ABN_OUT),
        # Tier 2 references
        afsl("000111", "OFFSHORE CUSTODY PTY LTD", acn=ACN_T2),
        afsl("000222", "HARBOUR ADVISERS PTY LTD", abn=ABN_NSW),
    ])
    yield s
    s.close()


def build(store: DuckDBStore):
    return CanonicalBuilder(store, states="WA,TAS", statuses="ACT", tier2_sources=["asic_afsl"]).build()


def _q(store, key):
    return {r["invariant"] for r in store.quarantine.list() if r["canonical_key"] == key}


def test_tier2_reference_ids(store):
    abns, acns = tier2_reference_ids(store.con, ["asic_afsl"])
    assert abns == {ABN_NSW}
    assert acns == {ACN_T2}


def test_abr_asic_join_on_acn(store):
    build(store)
    p = store.parties.get(f"urn:abn:{ABN_OK}")
    assert p["acn"] == ACN_OK and p["asic_record_id"] == ACN_OK
    assert p["asic_status"] == "REGD" and p["asic_type"] == "APTY" and p["asic_class"] == "LMSH"
    assert p["status"] == "ACTIVE" and p["abn_status"] == "ACT"
    assert p["valid_from"] == date(1990, 1, 8) and p["valid_to"] is None
    assert p["name_norm"] == "MONAKA" and p["state"] == "WA" and p["postcode"] == "6000"
    assert p["slice_reason"] == "state_slice" and p["quarantined"] is False
    assert store.parties.by_identifier(IdScheme.ACN, ACN_OK)["canonical_key"] == f"urn:abn:{ABN_OK}"
    assert store.parties.by_identifier("abn", ABN_OK)["canonical_key"] == f"urn:abn:{ABN_OK}"
    assert store.parties.get(f"urn:acn:{ACN_OK}") is None  # merged, not duplicated


def test_asic_only_party_via_tier2_reference(store):
    build(store)
    p = store.parties.get(f"urn:acn:{ACN_T2}")
    assert p is not None and p["source"] == "asic_company"
    assert p["slice_reason"] == "tier2_reference" and p["quarantined"] is False
    assert p["status"] == "DEREGISTERED"
    assert (p["valid_from"], p["valid_to"]) == (date(2005, 1, 1), date(2020, 1, 1))
    assert store.parties.by_identifier("acn", ACN_T2)["canonical_key"] == f"urn:acn:{ACN_T2}"
    # an unreferenced, unjoined ASIC company is evidence only
    assert store.parties.by_identifier("acn", make_acn(3001)) is None


def test_slice_reason_and_party_type(store):
    build(store)
    nsw = store.parties.get(f"urn:abn:{ABN_NSW}")
    assert nsw["slice_reason"] == "tier2_reference"
    assert nsw["status"] == "CANCELLED" and nsw["valid_to"] == date(2019, 5, 6) and nsw["valid_from"] is None
    person = store.parties.get(f"urn:abn:{ABN_PERSON}")
    assert person["party_type"] == "person" and person["slice_reason"] == "state_slice"


def test_aliases(store):
    build(store)
    rows = store.parties.aliases(f"urn:abn:{ABN_OK}")
    got = {(r["alias"], r["alias_type"], r["source"]) for r in rows}
    assert ("Monaka Catering", "business_name", "abr") in got
    assert ("Monaka Foods", "trading_name", "abr") in got
    assert ("LOVINI HOLDINGS PTY LTD", "former_name", "asic_company") in got
    lovini = next(r for r in rows if r["alias"] == "LOVINI HOLDINGS PTY LTD")
    assert lovini["alias_norm"] == "LOVINI HOLDINGS" and lovini["record_id"] == ACN_OK
    # merged ASIC register name differing from ABR's name becomes a register_name alias
    fr = {(r["alias"], r["alias_type"]) for r in store.parties.aliases(f"urn:abn:{ABN_FORMER}")}
    assert ("NEW BRAND VENTURES PTY LTD", "register_name") in fr


def test_acn_under_two_abns_quarantined_not_merged(store):
    build(store)
    for abn in (ABN_M1, ABN_M2):
        p = store.parties.get(f"urn:abn:{abn}")
        assert p is not None and p["quarantined"] is True and p["acn"] is None
        assert "ACN_MULTIPLE_ABN" in _q(store, f"urn:abn:{abn}")
    side = store.parties.get(f"urn:acn:{ACN_MULTI}")
    assert side is not None and side["quarantined"] is True
    # the ACN is held only by the party keyed by it, never given to either ABN
    assert store.parties.by_identifier("acn", ACN_MULTI)["canonical_key"] == f"urn:acn:{ACN_MULTI}"
    detail = json.loads(next(r["detail"] for r in store.quarantine.list()
                             if r["invariant"] == "ACN_MULTIPLE_ABN" and r["record_id"] == ABN_M1))
    assert detail["acn"] == ACN_MULTI and len(detail["abr_abns"]) == 2


def test_abr_acn_vs_asic_abn_disagree(store):
    build(store)
    for abn in (ABN_DIS_X, ABN_DIS_Z):
        p = store.parties.get(f"urn:abn:{abn}")
        assert p["quarantined"] is True and p["acn"] is None and p["asic_record_id"] is None
        assert "ABN_ACN_DISAGREE" in _q(store, f"urn:abn:{abn}")
    assert store.parties.get(f"urn:acn:{ACN_DIS}")["quarantined"] is True
    # both ABNs still resolve to their own party
    assert store.parties.by_identifier("abn", ABN_DIS_Z)["canonical_key"] == f"urn:abn:{ABN_DIS_Z}"


def test_name_mismatch_quarantined(store):
    build(store)
    p = store.parties.get(f"urn:abn:{ABN_NAME}")
    assert p["quarantined"] is True and p["asic_record_id"] is None and p["acn"] is None
    assert _q(store, f"urn:abn:{ABN_NAME}") == {"NAME_MISMATCH"}
    side = store.parties.get(f"urn:acn:{ACN_NAME}")
    assert side["quarantined"] is True and side["name"] == "QUANTUM ROBOTICS PTY LTD"
    assert side["abn"] is None  # ABN belongs to the ABR party; never duplicated


def test_former_name_is_not_a_mismatch(store):
    build(store)
    p = store.parties.get(f"urn:abn:{ABN_FORMER}")
    assert p["quarantined"] is False and p["acn"] == ACN_FORMER


def test_abn_claimed_by_two_acns(store):
    build(store)
    p = store.parties.get(f"urn:abn:{ABN_C4}")
    assert p["quarantined"] is True and p["acn"] is None
    assert _q(store, f"urn:abn:{ABN_C4}") == {"ABN_MULTIPLE_ACN"}
    for acn in (ACN_C4A, ACN_C4B):
        side = store.parties.get(f"urn:acn:{acn}")
        assert side["quarantined"] is True and side["abn"] is None


def test_identifier_values_unique_and_quarantine_only_known_invariants(store):
    build(store)
    dup = store.query("SELECT scheme, value FROM identifier GROUP BY 1, 2 HAVING count(*) > 1")
    assert dup == []
    assert {r["invariant"] for r in store.quarantine.list()} <= set(INVARIANTS)
    q_keys = {r["canonical_key"] for r in store.quarantine.list()}
    assert None not in q_keys
    flagged = {r["canonical_key"] for r in store.query("SELECT canonical_key FROM party_canonical WHERE quarantined")}
    assert flagged == q_keys


def _snapshot(store):
    return {
        t: store.con.execute(f"SELECT * FROM {t} ORDER BY ALL").fetchall()
        for t in ("party_canonical", "identifier", "alias", "quarantine")
    }


def test_rebuild_is_idempotent(store):
    s1 = build(store)
    before = _snapshot(store)
    store.quarantine.add("shacl", "x", "SHACL_OTHER", "kept")  # other producers' rows survive
    s2 = build(store)
    after = _snapshot(store)
    after["quarantine"] = [r for r in after["quarantine"] if r[2] != "SHACL_OTHER"]
    assert before == after
    assert s1.parties == s2.parties and s1.quarantine == s2.quarantine
    assert any(r["invariant"] == "SHACL_OTHER" for r in store.quarantine.list())


def test_counts(store):
    stats = build(store)
    # 10 ABR parties + ASIC: tier2-only (1) + conflict sides (multi, dis, name, c4a, c4b)
    assert stats.by_origin == {"abr": 10, "asic_conflict_side": 5, "asic_tier2_only": 1}
    assert store.parties.count() == 16
    assert store.parties.by_name_norm("MONAKA")[0]["canonical_key"] == f"urn:abn:{ABN_OK}"


def test_trust_acn_on_abr_record_is_not_the_trusts_own(tmp_path):
    s = DuckDBStore(tmp_path / "t.duckdb")
    acn = make_acn(4001)
    company, trust = make_abn(acn), make_abn(make_acn(4002))
    t = abr(trust, "The Trustee for Smith Family Trust", acn)
    t.payload["entity_type_code"], t.payload["entity_type_text"] = "TRT", "Discretionary Trading Trust"
    s.records.upsert([abr(company, "Smith Nominees Pty Ltd", acn), t,
                      asic(acn, "SMITH NOMINEES PTY LTD", company)])
    CanonicalBuilder(s, states="WA", statuses="ACT", tier2_sources=[]).build()
    assert s.quarantine.list() == []  # the trustee's ACN on the trust is not a second claimant
    assert s.parties.by_identifier("acn", acn)["canonical_key"] == f"urn:abn:{company}"
    assert s.parties.get(f"urn:abn:{trust}")["acn"] is None
    s.close()


def test_other_side_of_shared_acn_is_labelled_conflict_evidence(tmp_path):
    s = DuckDBStore(tmp_path / "e.duckdb")
    acn = make_acn(5001)
    wa, nsw = make_abn(acn), make_abn(make_acn(5002))
    s.records.upsert([abr(wa, "Carewest Ltd", acn), abr(nsw, "Livebetter Services Limited", acn, state="NSW")])
    CanonicalBuilder(s, states="WA", statuses="ACT", tier2_sources=[]).build()
    assert s.parties.get(f"urn:abn:{wa}")["slice_reason"] == "state_slice"
    other = s.parties.get(f"urn:abn:{nsw}")
    assert other["slice_reason"] == "acn_conflict_evidence" and other["quarantined"] is True
    assert {r["invariant"] for r in s.quarantine.list()} == {"ACN_MULTIPLE_ABN"}
    assert s.parties.by_identifier("acn", acn) is None  # no ASIC record: the ACN goes to nobody
    s.close()


def test_quarantine_rows_written_once_per_record_and_conflict(tmp_path):
    """Two ABR claimants of one ACN + the ASIC record naming one of them: both invariants
    fire, each involved record gets exactly one row per invariant, and rebuilding does not
    add rows."""
    s = DuckDBStore(tmp_path / "d.duckdb")
    acn = make_acn(6001)
    care, live = make_abn(make_acn(6002)), make_abn(acn)
    s.records.upsert([abr(care, "Carewest Ltd", acn), abr(live, "Livebetter Services Limited", acn),
                      asic(acn, "LIVEBETTER SERVICES LIMITED", live)])
    b = CanonicalBuilder(s, states="WA", statuses="ACT", tier2_sources=[])
    for _ in range(2):
        b.build()
        rows = s.con.execute("SELECT invariant, source, record_id, detail FROM quarantine").fetchall()
        assert len(rows) == len(set(rows)) == 6
        assert len({(i, d) for i, _, _, d in rows}) == 6  # detail names its record
        assert {(i, src, rid) for i, src, rid, _ in rows} == {
            (inv, src, rid)
            for inv in ("ACN_MULTIPLE_ABN", "ABN_ACN_DISAGREE")
            for src, rid in (("abr", care), ("abr", live), ("asic_company", acn))
        }
    for _, src, rid, d in rows:
        assert json.loads(d)["record"] == f"{src}:{rid}"
    s.close()
