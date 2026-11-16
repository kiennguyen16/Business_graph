"""Tier 2 adapters over small fixtures that use the real source headers.

Fixture identifiers are synthetic but checksum-valid (see tests/fixtures/tier2).
"""

from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

import pytest

from bizgraph.domain.models import Identifier, IdScheme, PartyType
from bizgraph.sources.adapters import tier2
from bizgraph.sources.base import RejectRecord
from bizgraph.sources.registry import registry

FIX = Path(__file__).parent / "fixtures" / "tier2"
SNAP = date(2026, 11, 16)


def run(adapter, filename):
    """Return (records by record_id, rejection reasons in row order)."""
    records, rejects = {}, []
    for row in adapter.parse(FIX / filename):
        try:
            r = adapter.to_record(row, SNAP)
        except RejectRecord as exc:
            rejects.append(str(exc))
            continue
        assert r.record_id not in records, f"duplicate record_id {r.record_id}"
        records[r.record_id] = r
    return records, rejects


def ids(record):
    return {i.scheme: i.value for i in record.identifiers}


# --------------------------------------------------------------------------- registry


@pytest.mark.parametrize(
    "source_id,licence",
    [
        ("asic_afsl", "CC BY 3.0 AU"),
        ("asic_credit", "CC BY 3.0 AU"),
        ("asic_banned_org", "CC BY 3.0 AU"),
        ("asic_liquidator", "CC BY 3.0 AU"),
        ("gleif_l1", "CC0 1.0"),
        ("gleif_l2", "CC0 1.0"),
    ],
)
def test_registered_with_tier_and_licence(source_id, licence):
    adapter = registry.get(source_id)
    assert adapter.tier == 2
    assert adapter.licence == licence


# --------------------------------------------------------------------------- AFSL


@pytest.fixture(scope="module")
def afsl():
    return run(tier2.AfslAdapter(), "afs_lic_fixture.csv")


def test_afsl_rejections(afsl):
    _, rejects = afsl
    assert rejects == ["missing_licence_number", "missing_name"]


def test_afsl_company_abn_and_derived_acn(afsl):
    r = afsl[0]["900001"]
    assert r.party_type is PartyType.ORGANISATION
    assert ids(r) == {IdScheme.AFSL: "900001", IdScheme.ABN: "11123456780", IdScheme.ACN: "123456780"}
    assert r.payload["identifier_provenance"] == {"abn": "source", "acn": "derived_from_abn"}
    assert r.payload["licence_start"] == "2002-05-02"
    assert r.payload["licence_end"] is None
    assert r.payload["status"] == "current"
    assert r.payload["state"] == "VIC"
    assert r.payload["pre_fsr_licences"] == [
        {"type": "General insurance broker", "number": "000030366"},
        {"type": "Securities dealer", "number": "000011162"},
    ]
    assert r.payload["authorisation_format"] == 1
    assert len(r.payload["authorisations"]) == 3
    assert r.name_norm == "EXAMPLE BROKING"


def test_afsl_person_never_gets_acn_from_abn(afsl):
    # The ABN's last 9 digits pass the ACN checksum, but a person has no ACN.
    r = afsl[0]["900002"]
    assert r.party_type is PartyType.PERSON
    assert r.payload["party_type_basis"] == "given_last_format"
    assert ids(r) == {IdScheme.AFSL: "900002", IdScheme.ABN: "63904805705"}
    assert r.payload["authorisation_format"] == 2
    assert r.payload["authorisations"][0].startswith("1. Provide financial product advice | ")


def test_afsl_foreign_bank_number_is_arbn_and_empty_date(afsl):
    # 'EXAMPLE BANK, LTD.' with an International address: a registered foreign body.
    r = afsl[0]["900003"]
    assert r.party_type is PartyType.ORGANISATION
    assert ids(r) == {IdScheme.AFSL: "900003", IdScheme.ARBN: "098765434"}
    assert r.payload["identifier_provenance"] == {"arbn": "source"}
    assert r.payload["licence_start"] is None
    assert "date_errors" not in r.payload


def test_afsl_acn_only_company(afsl):
    r = afsl[0]["900011"]
    assert ids(r) == {IdScheme.AFSL: "900011", IdScheme.ACN: "555555550"}
    assert r.payload["identifier_provenance"] == {"acn": "source"}


def test_afsl_trustee_name_gets_no_acn_from_abn(afsl):
    # The ABN's tail passes the ACN check, but the licensee is a trust ('... ATF ...').
    r = afsl[0]["900008"]
    assert IdScheme.ACN not in ids(r) and IdScheme.ABN in ids(r)
    assert r.payload["acn_withheld_reason"] == "trustee_marker"


def test_afsl_two_companies_get_no_acn_from_abn(afsl):
    r = afsl[0]["900009"]
    assert IdScheme.ACN not in ids(r)
    assert r.payload["acn_withheld_reason"] == "multi_party_name"


def test_afsl_llp_nine_digits_is_arbn(afsl):
    r = afsl[0]["900010"]
    assert ids(r) == {IdScheme.AFSL: "900010", IdScheme.ARBN: "555555550"}


def test_afsl_bad_date_and_absent_id_kept(afsl):
    r = afsl[0]["900004"]
    assert r.party_type is PartyType.ORGANISATION  # foreign legal form "AG"
    assert ids(r) == {IdScheme.AFSL: "900004"}
    assert r.payload["abn_acn_kind"] == "absent"
    assert r.payload["licence_start"] is None
    assert r.payload["date_errors"] == {"licence_start": "31/02/2010"}


def test_afsl_partnership_is_organisation(afsl):
    r = afsl[0]["900007"]
    assert r.party_type is PartyType.ORGANISATION
    assert r.payload["party_type_basis"] == "partnership_of_individuals"
    assert IdScheme.ACN not in ids(r)


# --------------------------------------------------------------------------- Credit


@pytest.fixture(scope="module")
def credit():
    return run(tier2.CreditLicenceAdapter(), "credit_lic_fixture.csv")


def test_credit_trust_nine_digits_is_unverified(credit):
    r = credit[0]["900015"]
    assert ids(r) == {IdScheme.ACL: "900015"}
    assert r.payload["unverified_acn"] == "555555550"
    assert r.payload["abn_acn_kind"] == "unverified_acn"


def test_credit_person_with_org_word_surname(credit):
    r = credit[0]["900016"]
    assert r.party_type is PartyType.PERSON
    assert (r.payload["given_names"], r.payload["family_name"]) == ("JOHN", "CHURCH")


def test_credit_rejections(credit):
    assert credit[1] == ["invalid_licence_number"]


def test_credit_company_with_afsl_cross_key(credit):
    r = credit[0]["900001"]
    assert ids(r) == {
        IdScheme.ACL: "900001",
        IdScheme.AFSL: "900001",
        IdScheme.ABN: "11123456780",
        IdScheme.ACN: "123456780",
    }
    assert r.identifiers[0].scheme is IdScheme.ACL
    assert r.payload["business_names"] == ["EXAMPLE HOME LOANS", "EXAMPLE FINANCE"]
    assert r.payload["edrs"] == ["AFCA", "COSL"]
    assert r.payload["status"] == "approved"
    assert r.payload["licence_start"] == "2010-10-04"


def test_credit_person_last_comma_given(credit):
    r = credit[0]["900010"]
    assert r.party_type is PartyType.PERSON
    assert r.payload["given_names"] == "JOHN PAUL"
    assert r.payload["family_name"] == "CITIZEN"
    assert r.name_raw == "CITIZEN, JOHN PAUL"
    assert r.name_norm == "JOHN PAUL CITIZEN"
    assert ids(r) == {IdScheme.ACL: "900010", IdScheme.ABN: "63904805705"}
    assert r.payload["status"] == "suspended"
    assert r.payload["status_history"] == [
        {"reason": "Suspended at the request of Licensee/Registrant", "start": "2018-07-18", "end": "2020-07-11"},
        {"reason": "Licensee contravenes a licence condition", "start": "2013-01-02", "end": "2013-04-02"},
    ]


def test_credit_zero_stripped_acn_is_padded(credit):
    r = credit[0]["900011"]
    assert ids(r)[IdScheme.ACN] == "008819458"
    assert r.payload["identifier_provenance"] == {"acn": "source_zero_padded"}


def test_credit_name_only_and_invalid_abn(credit):
    person = credit[0]["900012"]
    assert ids(person) == {IdScheme.ACL: "900012"}
    assert person.payload["abn_acn_kind"] == "absent"
    bad = credit[0]["900014"]
    assert ids(bad) == {IdScheme.ACL: "900014"}
    assert bad.payload["abn_acn_kind"] == "invalid_abn"
    assert bad.payload["abn_acn_raw"] == "12345678901"


# --------------------------------------------------------------------------- Banned orgs


@pytest.fixture(scope="module")
def banned():
    return run(tier2.BannedOrgAdapter(), "bd_org_fixture.csv")


def test_banned_tab_delimited_and_rejections(banned):
    records, rejects = banned
    assert len(records) == 4
    assert rejects == ["missing_or_invalid_ban_start", "missing_name"]


def test_banned_two_bans_same_company_distinct_ids(banned):
    first = banned[0]["123456780|australian_financial_services_banning|2006-11-07"]
    second = banned[0]["123456780|credit_banning|2012-04-10"]
    assert first.name_raw == "EXAMPLE BROKING PTY LTD"  # NBSP folded
    assert ids(first) == {IdScheme.ACN: "123456780"}
    assert first.payload["ban_start"] == "2006-11-07"
    assert first.payload["ban_end"] == "2008-11-07"
    assert first.payload["permanent"] is False
    assert first.payload["document_url"] is None
    assert first.payload["comment"] is None
    assert second.payload["permanent"] is True
    assert second.payload["ban_end"] is None
    assert second.payload["document_url"].startswith("http://download.asic.gov.au/")


def test_banned_invalid_acn_is_name_only(banned):
    r = banned[0]["WRONG CHECKSUM|credit_banning|2015-02-01"]
    assert r.identifiers == ()
    assert r.payload["acn_raw"] == "123456789"
    assert r.party_type is PartyType.ORGANISATION


def test_banned_person_row_detected(banned):
    r = banned[0]["CITIZEN JOHN|credit_banning|2015-02-01"]
    assert r.party_type is PartyType.PERSON
    assert r.identifiers == ()


# --------------------------------------------------------------------------- Liquidators


def test_liquidators_are_people():
    records, rejects = run(tier2.LiquidatorAdapter(), "liquidator_fixture.csv")
    assert rejects == ["missing_liquidator_number"]
    a = records["900116"]
    assert a.party_type is PartyType.PERSON
    assert a.identifiers == (Identifier(IdScheme.LIQUIDATOR_NO, "900116"),)
    assert (a.payload["given_names"], a.payload["family_name"]) == ("JOHN PAUL", "CITIZEN")
    assert a.name_norm == "JOHN PAUL CITIZEN"
    assert a.payload["firm"] == "EXAMPLE ADVISORY PTY LTD"
    assert a.payload["registration_start"] == "2015-11-18"
    assert a.payload["status"] == "approved"
    b = records["900117"]
    assert b.payload["status"] == "suspended"
    assert b.payload["suspension_date"] == "2026-06-03"
    assert b.payload["official_liquidator_number"] == "16448"
    assert b.payload["official_liquidator_start"] == "1997-06-24"
    assert b.payload["firm"] is None


# --------------------------------------------------------------------------- GLEIF L1


@pytest.fixture(scope="module")
def l1():
    return run(tier2.GleifL1Adapter(), "gleif-lei2-fixture.csv")


def test_gleif_l1_rejections(l1):
    assert l1[1] == ["invalid_lei_checksum"]


def test_gleif_l1_au_acn_from_registration_authority(l1):
    r = l1[0]["FIXTURECHILDAU000136"]
    assert ids(r) == {IdScheme.LEI: "FIXTURECHILDAU000136", IdScheme.ACN: "123456780"}
    assert r.payload["registration_authority_entity_id_kind"] == "acn"
    assert r.payload["state"] == "NSW"
    assert r.payload["in_scope"] == "au_nz"
    assert r.payload["other_names"] == [{"name": "OLD EXAMPLE PTY LTD", "type": "PREVIOUS_LEGAL_NAME"}]
    assert r.payload["entity_creation_date"] == "2001-03-05"
    assert r.party_type is PartyType.ORGANISATION


def test_gleif_l1_au_abn_from_registration_authority(l1):
    r = l1[0]["FIXTUREPARENT0000118"]
    assert ids(r)[IdScheme.ABN] == "62098765434"
    assert r.payload["registration_authority_entity_id_kind"] == "abn"


def test_gleif_l1_foreign_register_number_not_trusted(l1):
    # 123456780 passes the ACN checksum, but it was issued by a US register.
    r = l1[0]["FIXTUREFOREIGN000124"]
    assert ids(r) == {IdScheme.LEI: "FIXTUREFOREIGN000124"}
    assert r.payload["in_scope"] == "referenced_counterparty"
    assert r.payload["registration_authority_entity_id_kind"] is None


def test_gleif_l1_scheme_number_is_not_an_acn(l1):
    # ARSN (ASIC registered scheme) shares the ACN checksum but is not a company number.
    r = next(r for r in l1[0].values() if r.name_raw == "EXAMPLE INCOME FUND")
    assert IdScheme.ACN not in ids(r)
    assert r.payload["arsn"] == "123456780"
    assert r.payload["registration_authority_entity_id_kind"] == "arsn"


def test_gleif_l1_nz_and_sole_proprietor(l1):
    # 8819458 zero-pads to a checksum-valid ACN by chance; it is an NZ company number.
    nz = l1[0]["FIXTURECHILDNZ000112"]
    assert ids(nz) == {IdScheme.LEI: "FIXTURECHILDNZ000112", IdScheme.NZ_COMPANY_NO: "8819458"}
    assert IdScheme.ACN not in ids(nz)
    assert nz.payload["in_scope"] == "au_nz"
    assert nz.payload["nz_company_number"] == "8819458"
    sole = next(r for r in l1[0].values() if r.name_raw == "CITIZEN, JANE")
    assert sole.party_type is PartyType.PERSON
    assert sole.payload["registration_authority_entity_id_kind"] == "invalid_or_other"


def test_gleif_l1_sole_proprietor_business_name_is_unknown(l1):
    r = next(r for r in l1[0].values() if r.name_raw == "Mega Clicks")
    assert r.party_type is PartyType.UNKNOWN
    assert IdScheme.ABN in ids(r)


def test_gleif_l1_nzbn(l1):
    r = next(r for r in l1[0].values() if r.name_raw == "EXAMPLE NZBN LIMITED")
    assert ids(r)[IdScheme.NZBN] == "9420000000014"


def test_gleif_l1_trust_carries_trustee_acn_in_payload_only(l1):
    # ELF 7TPC (Trust): GLEIF's RA000014 number is the trustee company's ACN.
    r = next(r for r in l1[0].values() if r.name_raw == "The Trustee for Example Family Trust")
    assert set(ids(r)) == {IdScheme.LEI}
    assert r.payload["trustee_acn"] == "123123124"


def test_gleif_l1_fund_under_asic_company_ra_is_arsn(l1):
    r = next(r for r in l1[0].values() if r.name_raw == "EXAMPLE WHOLESALE EQUITY FUND")
    assert ids(r)[IdScheme.ARSN] == "555555550"
    assert IdScheme.ACN not in ids(r)


def test_gleif_l1_annulled_and_duplicate(l1):
    annulled = next(r for r in l1[0].values() if r.name_raw == "ANNULLED EXAMPLE PTY LTD")
    assert set(ids(annulled)) == {IdScheme.LEI}
    assert annulled.payload["lei_status"] == "ANNULLED"
    assert annulled.payload["withheld_registration_number"] == "123456780"
    dup = next(r for r in l1[0].values() if r.payload["lei_status"] == "DUPLICATE")
    assert ids(dup)[IdScheme.ACN] == "123456780"  # kept; resolution reads lei_status


def test_gleif_l1_foreign_elf_is_arbn(l1):
    r = next(r for r in l1[0].values() if r.name_raw == "EXAMPLE BANK OF ASIA CO., LTD.")
    assert ids(r)[IdScheme.ARBN] == "098765434"
    assert IdScheme.ACN not in ids(r)


def test_gleif_l1_reads_golden_copy_zip(tmp_path):
    z = tmp_path / "golden.csv.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(FIX / "gleif-lei2-fixture.csv", "20261116-0000-gleif-goldencopy-lei2-golden-copy.csv")
    adapter = tier2.GleifL1Adapter()
    assert sum(1 for _ in adapter.parse(z)) == 14


# --------------------------------------------------------------------------- GLEIF L2


@pytest.fixture(scope="module")
def l2():
    return run(tier2.GleifL2Adapter(), "gleif-rr-fixture.csv")


def test_gleif_l2_rejections(l2):
    assert l2[1] == ["invalid_lei_checksum", "non_lei_node", "self_relationship"]
    assert len(l2[0]) == 4


def test_gleif_l2_direct_parent(l2):
    r = l2[0]["FIXTURECHILDAU000136|IS_DIRECTLY_CONSOLIDATED_BY|FIXTUREPARENT0000118"]
    p = r.payload
    assert (p["child_lei"], p["parent_lei"]) == ("FIXTURECHILDAU000136", "FIXTUREPARENT0000118")
    assert (p["start_lei"], p["end_lei"]) == ("FIXTURECHILDAU000136", "FIXTUREPARENT0000118")
    assert p["is_parent_relationship"] is True
    assert p["relationship_status"] == "ACTIVE"
    assert p["valid_from"] == "2015-01-01"
    assert p["valid_to"] is None
    assert p["periods"][1] == {"type": "ACCOUNTING_PERIOD", "start": "2025-01-01", "end": "2025-12-31"}
    assert p["qualifiers"] == [{"dimension": "ACCOUNTING_STANDARD", "category": "IFRS"}]
    assert r.identifiers == ()
    assert r.party_type is PartyType.UNKNOWN
    assert r.name_raw is None


def test_gleif_l2_ultimate_parent_with_percentage(l2):
    r = l2[0]["FIXTURECHILDAU000136|IS_ULTIMATELY_CONSOLIDATED_BY|FIXTUREFOREIGN000124"]
    assert r.payload["quantifiers"] == [
        {"method": "ACCOUNTING_CONSOLIDATION", "amount": "100.00", "units": "PERCENTAGE"}
    ]


def test_gleif_l2_inactive_has_end_and_non_parent_types_kept(l2):
    inactive = l2[0]["FIXTURECHILDNZ000112|IS_DIRECTLY_CONSOLIDATED_BY|FIXTUREPARENT0000118"]
    assert inactive.payload["relationship_status"] == "INACTIVE"
    assert inactive.payload["valid_to"] == "2023-06-30"
    fund = l2[0]["FIXTURECHILDNZ000112|IS_FUND-MANAGED_BY|FIXTUREFOREIGN000124"]
    assert fund.payload["is_parent_relationship"] is False
    # A fund manager is not an owner: no child/parent fields on non-consolidation edges.
    assert "parent_lei" not in fund.payload and "child_lei" not in fund.payload
    assert (fund.payload["start_lei"], fund.payload["end_lei"]) == ("FIXTURECHILDNZ000112", "FIXTUREFOREIGN000124")


# --------------------------------------------------------------------------- helpers


@pytest.mark.parametrize(
    "name,comma,expected",
    [
        ("UBS AG", False, PartyType.ORGANISATION),
        ("BNP PARIBAS", False, PartyType.ORGANISATION),
        ("VINCENT D'ANGELO", False, PartyType.PERSON),
        ("KEYSTART", True, PartyType.ORGANISATION),
        ("O'GRADY, KAREN MAREE", True, PartyType.PERSON),
        ("MIZUHO BANK, LTD.", True, PartyType.ORGANISATION),
        ("D F DUFFY & E M HUME", True, PartyType.ORGANISATION),
        ("CHURCH, JOHN", True, PartyType.PERSON),
        ("KIM, SE JIN", True, PartyType.PERSON),
        ("STATE STREET GLOBAL ADVISORS, AUSTRALIA, LIMITED", True, PartyType.ORGANISATION),
    ],
)
def test_classify_party(name, comma, expected):
    assert tier2.classify_party(name, comma_person_format=comma)[0] is expected


def test_parse_au_date():
    assert tier2.parse_au_date("07/11/2006") == date(2006, 11, 7)
    assert tier2.parse_au_date("") is None
    with pytest.raises(ValueError):
        tier2.parse_au_date("Permanent banning")


def test_filter_gleif_golden_copy(tmp_path):
    l1z, rrz = tmp_path / "l1.csv.zip", tmp_path / "rr.csv.zip"
    with zipfile.ZipFile(l1z, "w") as zf:
        zf.write(FIX / "gleif-lei2-fixture.csv", "x-lei2-golden-copy.csv")
    with zipfile.ZipFile(rrz, "w") as zf:
        zf.write(FIX / "gleif-rr-fixture.csv", "x-rr-golden-copy.csv")
    l1_out, rr_out = tmp_path / "l1" / "out.csv", tmp_path / "l2" / "out.csv"
    stats = tier2.filter_gleif_golden_copy(l1z, rrz, l1_out, rr_out)
    assert stats["l1_rows"] == 14
    assert stats["l1_in_region"] == 13  # everything except the US counterparty
    assert stats["rr_kept"] == 7
    assert stats["referenced_found"] == 1  # the US parent is pulled back in
    leis = [row["LEI"] for row in tier2.GleifL1Adapter().parse(l1_out)]
    assert leis[-1] == "FIXTUREFOREIGN000124"


@pytest.mark.parametrize(
    "name,guard",
    [
        ("PACKER & CO LTD", None),
        ("SA & JR PTY LTD", None),
        ("CREDIT UNION SA LTD", None),
        ("PLC RESOURCES LIMITED", None),
        ("SMITH HOLDINGS PTY LTD ATF SMITH FAMILY TRUST", "trustee_marker"),
        ("TRUSTEES OF HELYER FAMILY TRUST", "trustee_marker"),
        ("EXAMPLE UNIT TRUST", "trust_or_fund_name"),
        ("COLLINS PARTNERS ADVISORY PTY LTD & CRADOC NOMINEES PTY LTD", "multi_party_name"),
        ("RUFFER LLP", "foreign_body"),
        ("UBS AG", "foreign_body"),
        ("MIZUHO BANK, LTD.", "foreign_body"),
        ("JOHN SMITH", "no_company_legal_form"),
    ],
)
def test_acn_guard(name, guard):
    assert tier2.acn_guard(name) == guard


def test_foreign_body_abn_tail_is_not_derived_as_arbn():
    payload: dict = {}
    out = tier2.abn_acn_identifiers("11123456780", "PERSHING LLC", payload)
    assert [i.scheme for i in out] == [IdScheme.ABN]
    assert payload["unverified_arbn"] == "123456780"


def test_company_on_scheme_register_is_not_an_arsn():
    # Listed investment companies appear on ASIC's scheme register (RA001192) with their ACN.
    payload = {
        "registration_authority_id": "RA001192",
        "registration_authority_entity_id": "123456780",
        "registration_status": "ISSUED",
        "legal_form_code": "ADXG",
        "legal_jurisdiction": "AU",
    }
    ids_, _, kind = tier2.GleifL1Adapter().registration_identifiers(payload, "WAM EXAMPLE LIMITED")
    assert ids_ == [] and kind == "unverified_acn"
    assert payload["unverified_acn"] == "123456780"


# --------------------------------------------------------------------------- GLEIF parent closure


def _lei(prefix18: str) -> str:
    num = int("".join(str(int(ch, 36)) for ch in prefix18 + "00"))
    return prefix18 + f"{98 - num % 97:02d}"


def test_consolidation_closure_walks_chain_and_survives_cycle():
    parents = {"A": {"B"}, "B": {"C"}, "C": {"D"}, "D": {"B"}}  # B -> C -> D -> B cycle
    added, depth, cut = tier2.consolidation_closure({"A"}, parents, max_depth=10)
    assert added == {"B", "C", "D"}
    assert depth == 3 and cut == 0


def test_consolidation_closure_is_bounded():
    parents = {f"N{i}": {f"N{i + 1}"} for i in range(20)}
    added, depth, cut = tier2.consolidation_closure({"N0"}, parents, max_depth=10)
    assert depth == 10 and len(added) == 10 and cut == 1


def test_filter_gleif_follows_foreign_parent_chain(tmp_path):
    """AU child -> US parent (fixture) -> foreign grandparent added here: the grandparent
    and the US-to-grandparent edge must be in the slice; an unrelated foreign edge must not."""
    import csv as _csv

    grand, other_a, other_b = _lei("FIXTUREGRANDPARENT"), _lei("FIXTUREUNRELATEDA0"), _lei("FIXTUREUNRELATEDB0")
    foreign = "FIXTUREFOREIGN000124"
    l1_rows = list(_csv.reader((FIX / "gleif-lei2-fixture.csv").open(encoding="utf-8", newline="")))
    header, base = l1_rows[0], next(r for r in l1_rows[1:] if r[0] == foreign)
    for lei_ in (grand, other_a, other_b):
        l1_rows.append([lei_] + base[1:])
    rr_rows = list(_csv.reader((FIX / "gleif-rr-fixture.csv").open(encoding="utf-8", newline="")))
    rr_header = rr_rows[0]
    template = dict(zip(rr_header, rr_rows[1]))
    for child, parent, typ in (
        (foreign, grand, "IS_DIRECTLY_CONSOLIDATED_BY"),
        (other_a, other_b, "IS_DIRECTLY_CONSOLIDATED_BY"),
        (foreign, other_b, "IS_FUND-MANAGED_BY"),
    ):
        row = dict(template)
        row.update({"Relationship.StartNode.NodeID": child, "Relationship.EndNode.NodeID": parent,
                    "Relationship.RelationshipType": typ})
        rr_rows.append([row[h] for h in rr_header])

    def zipped(rows, name):
        csv_path = tmp_path / f"{name}.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            _csv.writer(fh, quoting=_csv.QUOTE_ALL).writerows(rows)
        z = tmp_path / f"{name}.csv.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.write(csv_path, f"x-{name}-golden-copy.csv")
        return z

    l1_out, rr_out = tmp_path / "o" / "l1.csv", tmp_path / "o" / "rr.csv"
    stats = tier2.filter_gleif_golden_copy(zipped(l1_rows, "lei2"), zipped(rr_rows, "rr"), l1_out, rr_out)
    leis = {row["LEI"] for row in tier2.GleifL1Adapter().parse(l1_out)}
    edges = {(r["Relationship.StartNode.NodeID"], r["Relationship.RelationshipType"], r["Relationship.EndNode.NodeID"])
             for r in tier2.GleifL2Adapter().parse(rr_out)}
    assert grand in leis and (foreign, "IS_DIRECTLY_CONSOLIDATED_BY", grand) in edges
    assert other_a not in leis and other_b not in leis
    assert (foreign, "IS_FUND-MANAGED_BY", other_b) not in edges  # chain follows consolidation only
    assert stats["closure_max_depth"] == 2 and stats["rr_chain_only_edges"] == 1


def test_gleif_l1_country_prefers_legal_address(l1):
    r = l1[0]["FIXTURECHILDAU000136"]
    assert r.payload["country"] == r.payload["legal_country"] == "AU"
    assert r.payload["hq_country"] == "AU"
