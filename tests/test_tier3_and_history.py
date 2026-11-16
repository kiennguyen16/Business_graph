"""ACCC infringement notice adapter (tier 3) and AFSL licence history events.

ACCC fixtures are SYNTHETIC (the site's CDN returned 403 to automated clients on
2026-11-17, so no real page could be saved); they exercise the parsing rules.
AFSL fixtures use the real header and the real pre/post August 2026 condition
formats, with invented licences.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from bizgraph.domain.models import IdScheme, PartyType
from bizgraph.pipeline import licence_history as lh
from bizgraph.sources.adapters import tier3
from bizgraph.sources.adapters.tier2 import AfslAdapter
from bizgraph.sources.registry import registry
from bizgraph.store.duckdb_store import DuckDBStore

FIX = Path(__file__).parent / "fixtures"
ACCC = FIX / "tier3" / "accc_notice"
HIST = FIX / "licence_history"
SNAP = date(2026, 11, 17)


# --------------------------------------------------------------------------- ACCC


@pytest.fixture(scope="module")
def notices():
    adapter = registry.get("accc_notice")
    # synthetic HTML pages only (the real extract has its own fixture below); listing/ is a sibling
    rows = adapter.parse(ACCC / "notices")
    return {r.record_id: r for r in (adapter.to_record(row, SNAP) for row in rows)}


def test_registered_and_listing_pages_skipped(notices):
    assert isinstance(registry.get("accc_notice"), tier3.AcccNoticeAdapter)
    assert set(notices) == {
        "example-retail-pty-ltd-pays-penalty",
        "alpha-energy-and-beta-retail",
        "john-citizen",
        "gamma-telco-pty-ltd",
    }


def test_single_company_stated_total_and_abn(notices):
    r = notices["example-retail-pty-ltd-pays-penalty"]
    p = r.payload
    assert r.name_raw == "Example Retail Pty Ltd"  # title noise "pays $26,640 penalty" removed
    assert r.party_type is PartyType.ORGANISATION
    assert p["date_issued"] == "2026-09-03"
    assert p["notice_count"] == 2
    assert p["penalty_total_aud"] == "26640.00"
    assert p["penalty_total_basis"] == "stated_total"
    assert "Australian Consumer Law" in p["legislation"]
    assert "Competition and Consumer Act 2010" in p["legislation"]
    assert p["url"].endswith("/example-retail-pty-ltd-pays-penalty")
    # script / header text ("$999,999 paid", "$1 paid") never counted
    assert "999999.00" not in p["penalty_amounts_aud"] and "1.00" not in p["penalty_amounts_aud"]
    assert r.identifier(IdScheme.ABN) == "11123456780"
    # an ACN is never derived from a stated ABN on this source
    assert r.identifier(IdScheme.ACN) is None


def test_multi_party_per_notice_amount_and_no_identifiers(notices):
    r = notices["alpha-energy-and-beta-retail"]
    p = r.payload
    assert [x["name"] for x in p["parties"]] == ["Alpha Energy Pty Ltd", "Beta Retail Limited"]
    assert p["multi_party"] is True
    assert p["date_issued"] == "2026-10-14"
    assert p["penalty_amounts_aud"] == ["18780.00"]
    assert p["penalty_total_aud"] == "37560.00"
    assert p["penalty_total_basis"] == "per_notice_times_count"
    assert r.identifiers == ()  # stated ACN on a multi-party page is not attached
    assert p["identifiers_stated"][0]["withheld_reason"] == "multi_party_page"
    assert "Electricity Retail Code" in p["legislation"]


def test_person_gets_no_acn(notices):
    r = notices["john-citizen"]
    assert r.party_type is PartyType.PERSON
    assert r.payload["date_issued"] == "2026-08-21"
    assert r.payload["penalty_total_aud"] == "3756.00"
    assert r.payload["notice_count"] == 1
    assert r.identifiers == ()
    assert r.payload["identifiers_stated"][0]["withheld_reason"] == "no_company_legal_form"


def test_ambiguous_amounts_and_invalid_abn(notices):
    r = notices["gamma-telco-pty-ltd"]
    assert r.payload["date_issued"] == "2026-11-02"
    assert r.payload["penalty_total_aud"] is None
    assert r.payload["penalty_total_basis"] == "ambiguous_multiple_amounts"
    assert set(r.payload["penalty_amounts_aud"]) == {"15000.00", "3000.00"}
    assert r.identifiers == ()
    assert r.payload["identifiers_stated"][0]["valid"] is False


@pytest.mark.parametrize(
    "name, expected",
    [
        ("A Pty Ltd and B Pty Ltd", ["A Pty Ltd", "B Pty Ltd"]),
        ("Smith & Jones Pty Ltd", ["Smith & Jones Pty Ltd"]),
        ("Foo Pty Ltd; Jane Citizen", ["Foo Pty Ltd", "Jane Citizen"]),
        ("Harvey Norman Holdings Limited", ["Harvey Norman Holdings Limited"]),
    ],
)
def test_split_parties(name, expected):
    assert tier3.split_parties(name) == expected


def test_adapter_run_into_store():
    with DuckDBStore(":memory:") as store:
        store.init_schema()
        adapter = registry.get("accc_notice")
        stats = adapter.run(ACCC / "notices" / "john-citizen.html", SNAP, store)
        assert stats.records_new == 1 and stats.records_rejected == 0


# --------------------------------------------------------------------------- licence history

FILES = sorted(HIST.glob("afs_lic_*.csv"))
D1, D2, D3 = date(2026, 8, 5), date(2026, 9, 2), date(2026, 10, 7)


def _by(events):
    return {(e.licence_no, str(e.event_type), e.event_date): e for e in events}


def test_snapshot_dates_from_filenames():
    assert [lh.snapshot_date_for(f) for f in FILES] == [D1, D2, D3]


def test_events_from_files():
    ev = _by(lh.events_from_files(FILES))
    assert set(ev) == {
        ("900002", "AUTHORISATION_CHANGED", D2),  # prose -> numbered: flagged as restated
        ("900003", "HOLDER_RENAMED", D2),
        ("900004", "CANCELLED_OR_LAPSED", D2),
        ("900005", "HOLDER_CHANGED", D2),
        ("900006", "GRANTED", D2),
        ("900001", "AUTHORISATION_CHANGED", D3),  # life risk added: substantive
        ("900004", "REAPPEARED", D3),
        ("900005", "CANCELLED_OR_LAPSED", D3),
    }
    # 900001 Aug -> Sep is only the quoted/enumerated format change (with ASIC's "(viii" typo)
    # 900002 'CITIZEN, JANE MARY' -> 'JANE M CITIZEN' is the name reformat, not a rename
    c = ev[("900004", "CANCELLED_OR_LAPSED", D2)]
    assert c.observed_after == D1 and c.event_date == D2  # bounds
    assert c.holder_name_before == "SOON GONE PTY LTD" and c.holder_name_after is None
    assert c.record_iri == "urn:src:asic_afsl:900004"
    assert ev[("900002", "AUTHORISATION_CHANGED", D2)].detail["wording_restated"] is True
    assert ev[("900001", "AUTHORISATION_CHANGED", D3)].detail["wording_restated"] is False
    assert ev[("900005", "HOLDER_CHANGED", D2)].match_basis == "name"
    assert ev[("900003", "HOLDER_RENAMED", D2)].match_basis == "identifier"


def test_same_holder_rules():
    def st(name, abn=None, acn=None):
        return lh.LicenceState("asic_afsl", "1", name, abn, acn, "unknown", "x", 0, None)

    assert lh.same_holder(st("A PTY LTD", acn="123456780"), st("B LIMITED", abn="11123456780")) == (True, "identifier")
    assert lh.same_holder(st("A PTY LTD", acn="123456780"), st("A PTY LTD", acn="004085616"))[0] is False
    assert lh.same_holder(st("GALL, ALLAN JOHN"), st("ALLAN J GALL")) == (True, "person_name")
    assert lh.same_holder(st("ARGONAUT FUNDS PTY LTD"), st("ARGONAUT FUNDS LIMITED")) == (True, "name")


def test_events_from_store_match_files_except_unchanged_gap(tmp_path):
    with DuckDBStore(":memory:") as store:
        store.init_schema()
        for f, d in zip(FILES, (D1, D2, D3)):
            AfslAdapter().run(f, d, store)
        from_store = _by(lh.events_from_store(store.con, ["asic_afsl"]))
        n = lh.write_events(store.con, list(from_store.values()))
        assert store.query("SELECT count(*) AS n FROM licence_event")[0]["n"] == n
        # recompute is idempotent
        lh.write_events(store.con, list(from_store.values()))
        assert store.query("SELECT count(*) AS n FROM licence_event")[0]["n"] == n
        recent = store.query(
            "SELECT licence_no FROM licence_event WHERE event_type = 'CANCELLED_OR_LAPSED' "
            "AND event_date >= DATE '2026-09-15'"
        )
    from_files = _by(lh.events_from_files(FILES))
    # Documented blind spot: 900004's content is identical before and after its absence,
    # so the store keeps one row spanning the gap and sees neither event.
    blind = {("900004", "CANCELLED_OR_LAPSED", D2), ("900004", "REAPPEARED", D3)}
    assert set(from_files) - set(from_store) == blind
    assert set(from_store) <= set(from_files)
    assert recent == [{"licence_no": "900005"}]


def test_authorisation_signature_ignores_format():
    prose = ["This licence authorises:", "(a) provide advice:", "(viii general insurance"]
    quoted = ['"This licence authorises:" | "(a) provide advice:"', '"(viii) general insurance"']
    assert lh.authorisation_signature(prose) == lh.authorisation_signature(quoted)
    assert lh.authorisation_style(["1.1.1 Basic deposit products | Retail"]) == "numbered"
    assert lh.authorisation_style(prose) == "prose"


def test_amount_parsing_helper():
    assert tier3._money(tier3._MONEY.search("$1,234,567.50")) == Decimal("1234567.50")


# --------------------------------------------------------------------------- ACCC real extract

EXTRACT = ACCC / "extract_20261117.txt"  # real, CC BY 4.0 (ACCC), 20 most recent notices


@pytest.fixture(scope="module")
def real():
    adapter = registry.get("accc_notice")
    recs = [adapter.to_record(row, SNAP) for row in adapter.parse(EXTRACT)]
    assert len(recs) == len({r.record_id for r in recs})
    return {r.record_id: r for r in recs}


def test_extract_twenty_records_with_urls_and_dates(real):
    assert len(real) == 20
    for slug, r in real.items():
        assert r.payload["url"] == f"{tier3.REGISTER_URL}/{slug}"
        assert r.payload["date_paid"] and r.payload["date_paid"] == r.payload["date_issued"]
        assert r.party_type is PartyType.ORGANISATION
        # the register states no amount: nothing guessed
        assert r.payload["penalty_total_aud"] is None
        assert r.payload["penalty_amounts_aud"] == []
        assert r.payload["penalty_total_basis"] == "not_stated_on_register"
    assert real["cotton-on-australia-pty-ltd"].payload["date_paid"] == "2026-11-05"


def test_extract_identifier_counts(real):
    abns = [r for r in real.values() if r.identifier(IdScheme.ABN)]
    acns = [r for r in real.values() if r.identifier(IdScheme.ACN)]
    none = [r for r in real.values() if not r.identifiers]
    assert (len(abns), len(acns), len(none)) == (5, 14, 2)
    # every stated identifier passed its checksum
    assert all(s["valid"] for r in real.values() for s in r.payload["identifiers_stated"])
    weflex = real["weflex-pty-ltd"]
    assert weflex.identifier(IdScheme.ABN) == "44644941873"
    assert weflex.identifier(IdScheme.ACN) == "644941873"
    assert weflex.payload["abn_acn_consistent"] is True
    # an ABN-only notice gets no ACN derived from the ABN tail
    assert real["sharetea-australia-pty-ltd"].identifier(IdScheme.ACN) is None


def test_extract_infringement_numbers_and_legislation(real):
    d = real["digital-imaging-express-pty-ltd-0"].payload
    assert d["infringement_numbers"] == ["2627/05", "2627/06", "2627/07", "2627/08", "2627/09"]
    assert d["notice_count"] == 5
    assert d["section"] == "Section 29(1)(i) of the Australian Consumer Law"
    assert d["legislation"] == ["Australian Consumer Law"]
    v = real["venue-smart-pty-ltd-1"].payload
    assert v["legislation"] == ["Competition and Consumer (Industry Codes-Franchising) Regulation 2024"]
    assert real["sharetea-australia-pty-ltd"].payload["legislation"] == ["Franchising Code of Conduct"]


def test_extract_hm_ampersand_name(real):
    r = real["hm-hennes-mauritz-pty-ltd"]
    assert r.name_raw == "H&M Hennes & Mauritz Pty Ltd"
    assert len(r.payload["parties"]) == 1  # '&' inside one company name is not a party split
    assert r.identifier(IdScheme.ACN) == "160056548"
    assert r.payload["notice_count"] == 7


def test_extract_trading_as(real):
    r = real["the-sleeping-giant-pty-ltd-trading-as-james-lane"]
    assert r.name_raw == "The Sleeping Giant Pty Ltd"
    assert r.payload["trading_as"] == "James Lane"
    assert real["systems-operations-pty-ltd-trading-as-vuly-play-group"].payload["trading_as"] == "Vuly Play Group"
    assert real["cotton-on-australia-pty-ltd"].payload["trading_as"] is None


def test_extract_foreign_company_has_no_identifier(real):
    for slug in ("vacaciones-edreams-sl", "vacaciones-edreams-sl-0"):
        r = real[slug]
        assert r.name_raw == "Vacaciones eDreams, S.L."
        assert r.identifiers == ()
        assert r.payload["reference_number"] == "Sociedad unipersonal con CIF B-61965778"
        assert r.payload["reference_kind"] == "foreign_tax_id"


def test_extract_same_company_many_notices_are_distinct_records(real):
    venue = [s for s in real if s.startswith("venue-smart-pty-ltd")]
    assert sorted(venue) == ["venue-smart-pty-ltd", "venue-smart-pty-ltd-0", "venue-smart-pty-ltd-1"]
    assert {real[s].identifier(IdScheme.ABN) for s in venue} == {"52604254766"}
    assert len({tuple(real[s].payload["infringement_numbers"]) for s in venue}) == 3
    by_name: dict[str, int] = {}
    for r in real.values():
        by_name[r.name_raw] = by_name.get(r.name_raw, 0) + 1
    assert {n: c for n, c in by_name.items() if c > 1} == {
        "Dysck Pty Ltd": 2,
        "Venue Smart Pty Ltd": 3,
        "HSK United Pty Ltd": 2,
        "Marshall Freeman Collections Pty Ltd": 2,
        "Vacaciones eDreams, S.L.": 2,
    }


def test_extract_and_html_in_one_directory():
    adapter = registry.get("accc_notice")
    ids = [adapter.to_record(row, SNAP).record_id for row in adapter.parse(ACCC)]
    assert len(ids) == 24 and len(set(ids)) == 24  # 20 real + 4 synthetic pages, listing skipped


def test_extract_run_into_scratch_store():
    with DuckDBStore(":memory:") as store:
        store.init_schema()
        stats = registry.get("accc_notice").run(EXTRACT, SNAP, store)
        assert (stats.records_in, stats.records_new, stats.records_rejected) == (20, 20, 0)
        assert store.records.count("accc_notice") == 20


def test_split_notice_numbers():
    assert tier3.split_notice_numbers("2627/15, 2627/16") == ["2627/15", "2627/16"]
    assert tier3.split_notice_numbers("2627/01") == ["2627/01"]
    assert tier3.split_notice_numbers("") == []
