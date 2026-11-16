"""Independent contract tests for the Tier 2 adapters, run over the REAL raw files.

Derived from Requirement.md (a wrong link is worse than no link; report identifier
coverage; people vs organisations; banned register = accusation risk) and from the raw
data itself, not from the author's tests. Checksums are re-implemented here.

Tests marked `finding` are expected to FAIL against the current adapter: each one pins
a wrong-identifier or typing risk found by the audit (tests/independent/audit_tier2.py).

Run:  .venv/Scripts/python -m pytest tests/independent/test_tier2_contract.py -q
Slow register cross-check: add  -m "register"  (or set RUN_REGISTER=1).
"""

from __future__ import annotations

import os
import re
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from bizgraph.domain.models import IdScheme, PartyType
from bizgraph.sources.adapters import tier2
from bizgraph.sources.base import RejectRecord

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
SNAP = date(2026, 11, 16)
FILES = {
    "asic_afsl": RAW / "asic_afsl" / "afs_lic_202611.csv",
    "asic_credit": RAW / "asic_credit" / "credit_lic_202611.csv",
    "asic_banned_org": RAW / "asic_banned_org" / "bd_org_202611.csv",
    "asic_liquidator": RAW / "asic_liquidator" / "liquidator_202611.csv",
    "gleif_l1": RAW / "gleif_l1" / "20261116-gleif-lei2-au-nz.csv",
    "gleif_l2": RAW / "gleif_l2" / "20261116-gleif-rr-au-nz.csv",
}
ADAPTERS = {
    "asic_afsl": tier2.AfslAdapter,
    "asic_credit": tier2.CreditLicenceAdapter,
    "asic_banned_org": tier2.BannedOrgAdapter,
    "asic_liquidator": tier2.LiquidatorAdapter,
    "gleif_l1": tier2.GleifL1Adapter,
    "gleif_l2": tier2.GleifL2Adapter,
}
COMPANY_ZIP = RAW / "asic_company" / "company_202611.zip"

pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in FILES.values()), reason="real Tier 2 raw files not present"
)

# ------------------------------------------------------------------ independent validators


def abn_ok(v: str) -> bool:
    if not re.fullmatch(r"[1-9]\d{10}", v or ""):
        return False
    d = [int(c) for c in v]
    d[0] -= 1
    return sum(a * b for a, b in zip(d, [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19])) % 89 == 0


def acn_ok(v: str) -> bool:
    if not re.fullmatch(r"\d{9}", v or ""):
        return False
    s = sum(int(v[i]) * (8 - i) for i in range(8))
    return (10 - s % 10) % 10 == int(v[8])


def lei_ok(v: str) -> bool:
    return bool(re.fullmatch(r"[0-9A-Z]{18}\d{2}", v or "")) and int(
        "".join(str(int(c, 36)) for c in v)
    ) % 97 == 1


CHECK = {IdScheme.ABN: abn_ok, IdScheme.ACN: acn_ok, IdScheme.LEI: lei_ok}


def raw_df(source: str) -> pd.DataFrame:
    p = FILES[source]
    first = p.open(encoding="utf-8-sig").readline()
    sep = "\t" if first.count("\t") > first.count(",") else ","
    return pd.read_csv(p, sep=sep, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def run(source: str):
    ad = ADAPTERS[source]()
    recs, rejects, n_in = [], Counter(), 0
    for row in ad.parse(FILES[source]):
        n_in += 1
        try:
            recs.append(ad.to_record(row, SNAP))
        except RejectRecord as exc:
            rejects[str(exc)] += 1
    return recs, rejects, n_in


@pytest.fixture(scope="module")
def runs():
    return {s: run(s) for s in ADAPTERS}


def by_id(runs, source):
    return {r.record_id: r for r in runs[source][0]}


# ------------------------------------------------------------------ accounting / stability


@pytest.mark.parametrize("source", list(ADAPTERS))
def test_every_raw_row_is_accounted_for(runs, source):
    recs, rejects, n_in = runs[source]
    assert n_in == len(raw_df(source)), "parse() row count differs from pandas row count"
    assert len(recs) + sum(rejects.values()) == n_in
    allowed = {"gleif_l2": {"self_relationship"}}.get(source, set())
    assert set(rejects) <= allowed, f"unexpected rejections {dict(rejects)}"


@pytest.mark.parametrize("source", list(ADAPTERS))
def test_record_ids_unique_and_stable_across_runs(runs, source):
    recs = runs[source][0]
    ids = Counter(r.record_id for r in recs)
    assert not [k for k, v in ids.items() if v > 1]
    again = run(source)[0]
    a = [(r.record_id, r.content_hash, r.identifiers, r.party_type) for r in recs]
    b = [(r.record_id, r.content_hash, r.identifiers, r.party_type) for r in again]
    assert a == b


@pytest.mark.parametrize("source", list(ADAPTERS))
def test_every_emitted_identifier_passes_independent_checksum(runs, source):
    bad = [
        (r.record_id, i)
        for r in runs[source][0]
        for i in r.identifiers
        if i.scheme in CHECK and not CHECK[i.scheme](i.value)
    ]
    assert not bad


# ------------------------------------------------------------------ coverage vs outputs doc


def _doc_int(s: str) -> int:
    return int(s.replace(",", ""))


def test_coverage_doc_matches_independent_recount():
    doc = (REPO / "outputs" / "identifier_coverage.md").read_text(encoding="utf-8")
    form = re.compile(r"\b(?:PTY|PROPRIETARY|LTD|LIMITED|NL|NO LIABILITY)\b", re.I)
    for src, col, namecol in [
        ("asic_afsl", "AFS_LIC_ABN_ACN", "AFS_LIC_NAME"),
        ("asic_credit", "CRED_LIC_ABN_ACN", "CRED_LIC_NAME"),
    ]:
        df = raw_df(src)
        d = df[col].str.replace(r"\D", "", regex=True)
        abn = d.str.len().eq(11) & d.map(abn_ok)
        acn_stated = d.str.len().between(1, 9) & ~d.str.fullmatch("0+") & d.str.zfill(9).map(acn_ok)
        derived = abn & df[namecol].str.contains(form) & d.str[2:].map(acn_ok)
        line = next(l for l in doc.splitlines() if l.startswith(f"| `{src}`"))
        cells = [c.strip() for c in line.split("|")]
        assert _doc_int(cells[2]) == len(df)
        assert _doc_int(cells[4].split()[0]) == abn.sum()
        # The naive recount trusts every checksum-valid ACN. After the audit fixes the
        # adapter refuses trustee / joint-name / foreign numbers, so the documented
        # counts may only be LOWER than the naive recount, never higher.
        assert _doc_int(cells[5].split()[0]) <= (acn_stated | derived).sum()
        assert _doc_int(cells[6].split()[0]) <= acn_stated.sum()
        assert _doc_int(cells[7].split()[0]) <= (abn | acn_stated).sum()

    g = pd.read_csv(FILES["gleif_l1"], dtype=str, keep_default_na=False)
    ra = g["Entity.RegistrationAuthority.RegistrationAuthorityID"]
    e = g["Entity.RegistrationAuthority.RegistrationAuthorityEntityID"].str.replace(r"\D", "", regex=True)
    acn = ra.eq("RA000014") & e.str.len().between(1, 9) & e.str.zfill(9).map(acn_ok)
    abn = ra.isin(["RA000013", "RA000762", "RA000714"]) & e.str.len().eq(11) & e.map(abn_ok)
    # Naive recount is pinned; the doc's "before" column must still show it. The
    # "after" numbers are lower by design (trusts, schemes, ANNULLED withheld).
    assert "34,387" in doc and acn.sum() == 34387
    assert abn.sum() == 14168
    assert (acn | abn).sum() == 48555


# ------------------------------------------------------------------ dates


DATE_COLS = {
    "asic_afsl": {"AFS_LIC_START_DT": "licence_start"},
    "asic_credit": {"CRED_LIC_START_DT": "licence_start", "CRED_LIC_END_DT": "licence_end"},
    "asic_banned_org": {"BD_ORG_START_DT": "ban_start", "BD_ORG_END_DT": "ban_end"},
    "asic_liquidator": {
        "LIQ_START_DT": "registration_start",
        "OFF_LIQ_START_DT": "official_liquidator_start",
        "LIQ_SUSP_DT": "suspension_date",
    },
}


@pytest.mark.parametrize("source", list(DATE_COLS))
def test_dates_parse_and_none_only_when_raw_empty(runs, source):
    df = raw_df(source)
    recs = runs[source][0]
    assert len(recs) == len(df)
    for col, key in DATE_COLS[source].items():
        for raw, rec in zip(df[col].str.strip(), recs):
            got = rec.payload.get(key)
            if re.fullmatch(r"\d{2}/\d{2}/\d{4}", raw):
                assert got == datetime.strptime(raw, "%d/%m/%Y").date().isoformat(), (rec.record_id, col)
            elif raw == "" or "ermanent" in raw:
                assert got is None
            else:
                pytest.fail(f"unexpected raw date format {raw!r} in {col}")
        assert not any(key in (r.payload.get("date_errors") or {}) for r in recs)


def test_gleif_l2_period_dates_all_parsed(runs):
    for r in runs["gleif_l2"][0]:
        assert r.payload["valid_from"] is not None
        for p in r.payload["periods"]:
            assert p["start"] is None or re.fullmatch(r"\d{4}-\d{2}-\d{2}", p["start"])


# ------------------------------------------------------------------ banned register


def test_banned_every_row_kept_with_valid_acn_and_permanent_flag(runs):
    df = raw_df("asic_banned_org")
    recs = runs["asic_banned_org"][0]
    assert len(recs) == len(df) == 15
    for raw, rec in zip(df.itertuples(index=False), recs):
        assert rec.identifier(IdScheme.ACN) == re.sub(r"\D", "", raw.BD_ORG_ACN).zfill(9)
        assert rec.party_type is PartyType.ORGANISATION
        assert rec.payload["permanent"] == ("ermanent" in raw.BD_ORG_END_DT)
        assert len(rec.identifiers) == 1  # never derives or guesses anything else
    perm = [r for r in recs if r.payload["permanent"]]
    assert [r.name_raw for r in perm] == ["M.A.I PACIFIC PTY LTD"]
    assert perm[0].payload["ban_end"] is None


# ------------------------------------------------------------------ GLEIF


def test_gleif_l2_direction_child_is_startnode(runs):
    """GLEIF RR-CDF: 'The StartNode of the child entity has its accounts fully consolidated
    by the EndNode parent entity'. Macquarie Group must be a parent with many children."""
    l1 = by_id(runs, "gleif_l1")
    kids = Counter(
        r.payload["parent_lei"]
        for r in runs["gleif_l2"][0]
        if r.payload["relationship_type"] == "IS_ULTIMATELY_CONSOLIDATED_BY"
    )
    top, n = kids.most_common(1)[0]
    assert l1[top].name_raw == "MACQUARIE GROUP LIMITED" and n > 50
    df = pd.read_csv(FILES["gleif_l2"], dtype=str, keep_default_na=False)
    row = df.iloc[0]
    rec = by_id(runs, "gleif_l2")[
        f"{row['Relationship.StartNode.NodeID']}|{row['Relationship.RelationshipType']}|{row['Relationship.EndNode.NodeID']}"
    ]
    assert rec.payload["child_lei"] == row["Relationship.StartNode.NodeID"]


def test_gleif_l2_parent_edges_acyclic_and_single_parent(runs):
    adj = defaultdict(set)
    per_type = defaultdict(Counter)
    for r in runs["gleif_l2"][0]:
        p = r.payload
        if p["is_parent_relationship"]:
            adj[p["child_lei"]].add(p["parent_lei"])
            per_type[p["relationship_type"]][p["child_lei"]] += 1
    for t, c in per_type.items():
        assert max(c.values()) == 1, t
    for start in adj:  # each node has <= 2 parents (direct, ultimate): walk is cheap
        seen, frontier = {start}, set(adj[start])
        while frontier:
            assert start not in frontier, f"cycle through {start}"
            seen |= frontier
            frontier = {q for f in frontier for q in adj.get(f, ())} - seen


def test_gleif_l2_edge_ends_present_in_l1(runs):
    l1 = by_id(runs, "gleif_l1")
    # Design decision: every edge has start_lei/end_lei; child/parent only on consolidation edges.
    assert all(r.payload["start_lei"] in l1 and r.payload["end_lei"] in l1 for r in runs["gleif_l2"][0])
    for r in runs["gleif_l2"][0]:
        assert ("parent_lei" in r.payload) == r.payload["is_parent_relationship"]


def test_gleif_ra_mapping_only_trusted_registers(runs):
    # Updated for the ARSN / ARBN / NZBN / NZ_COMPANY_NO schemes.
    trusted = tier2.GleifL1Adapter.RA_ALLOWED_SCHEMES
    for r in runs["gleif_l1"][0]:
        extra = [i for i in r.identifiers if i.scheme is not IdScheme.LEI]
        if extra:
            ra = r.payload["registration_authority_id"]
            assert ra in trusted
            assert all(i.scheme in trusted[ra] for i in extra)
            assert r.payload["in_scope"] == "au_nz"


@pytest.mark.finding
def test_gleif_annulled_lei_emits_no_party_identifier(runs):
    """ANNULLED = LEI issued in error. Its ABN/ACN should not be trusted as an exact key."""
    bad = [
        (r.record_id, r.name_raw)
        for r in runs["gleif_l1"][0]
        if r.payload["registration_status"] == "ANNULLED" and len(r.identifiers) > 1
    ]
    assert not bad, f"{len(bad)} ANNULLED LEIs emit ABN/ACN: {bad}"


@pytest.mark.finding
def test_gleif_trust_lei_does_not_carry_trustee_company_acn(runs):
    """A trust or managed fund has no ACN. Under RA000014 GLEIF stores the TRUSTEE
    company's ACN for trusts (e.g. 'The Trustee for Austral 151 Trust' carries ACN
    620721726, which the ASIC register and another LEI both say is ARCSIDE PTY LTD).
    Emitting it as the trust's ACN merges the trust into the trustee company."""
    trust = re.compile(
        r"\bATF\b|AS (THE )?TRUSTEES? (FOR|OF)|TRUSTEE FOR|^THE TRUSTEE|\bTRUST( NO\.? ?\d+)?$"
        r"|SUPER(ANNUATION)? FUND$|UNIT TRUST|FAMILY TRUST",
        re.I,
    )
    bad = [
        (r.record_id, r.name_raw, r.identifier(IdScheme.ACN))
        for r in runs["gleif_l1"][0]
        if r.identifier(IdScheme.ACN) and trust.search(r.name_raw)
    ]
    assert not bad, f"{len(bad)} trust-named LEIs emit an ACN, e.g. {bad[:5]}"


# ------------------------------------------------------------------ ASIC identifier interpretation


@pytest.mark.finding
def test_credit_trust_name_with_nine_digits_is_not_an_acn(runs):
    """Raw: 'TRUSTEES OF HELYER FAMILY TRUST', CRED_LIC_ABN_ACN=142952672. A trust cannot
    hold an ACN and the number is not in the ASIC company register. Five such rows."""
    bad = [
        (r.record_id, r.name_raw, r.identifier(IdScheme.ACN))
        for r in runs["asic_credit"][0]
        if r.identifier(IdScheme.ACN) and re.search(r"\bTRUST$", r.name_raw)
        and not re.search(r"\b(PTY|LTD|LIMITED)\b", r.name_raw)
    ]
    assert not bad, bad


@pytest.mark.finding
def test_foreign_body_nine_digit_number_is_arbn_not_acn(runs):
    """AFSL 526358 'RUFFER LLP' 642497630: a registered foreign body's number is an ARBN
    (IdScheme.ARBN exists). It is emitted as ACN."""
    r = by_id(runs, "asic_afsl")["526358"]
    assert r.identifier(IdScheme.ACN) is None and r.identifier(IdScheme.ARBN) == "642497630"


VALID_COMPANY_ABN = "66061804671"  # PACKER & CO LTD; last 9 digits pass the ACN check


@pytest.mark.finding
@pytest.mark.parametrize(
    "name",
    [
        "SMITH HOLDINGS PTY LTD ATF SMITH FAMILY TRUST",
        "FRESHWATER FINANCE PTY LTD & THE TRUSTEE FOR COMPASS MORTGAGE SOLUTIONS TRUST",
        "COLLINS PARTNERS ADVISORY PTY LTD & CRADOC NOMINEES PTY LTD",
    ],
)
def test_no_acn_derived_for_trust_or_multi_party_abn(name):
    """These name shapes occur in the real AFSL/credit files (the last two verbatim). The ABN
    belongs to a trust or partnership, so its last 9 digits are not anyone's ACN. Today they
    escape only because the 1-in-10 ACN checksum happened to fail."""
    payload: dict = {}
    ids = tier2.abn_acn_identifiers(VALID_COMPANY_ABN, name, payload)
    assert IdScheme.ACN not in {i.scheme for i in ids}, payload["identifier_provenance"]


def test_acn_derived_for_plain_company():
    payload: dict = {}
    ids = tier2.abn_acn_identifiers(VALID_COMPANY_ABN, "PACKER & CO LTD", payload)
    assert ("acn", "061804671") in {(i.scheme.value, i.value) for i in ids}
    assert payload["identifier_provenance"]["acn"] == "derived_from_abn"


def test_no_acn_derived_for_sole_trader_abn():
    payload: dict = {}
    ids = tier2.abn_acn_identifiers(VALID_COMPANY_ABN, "JOHN SMITH", payload)
    assert [i.scheme for i in ids] == [IdScheme.ABN]


def test_credit_afsl_cross_reference_points_to_same_entity(runs):
    afsl = by_id(runs, "asic_afsl")
    checked = 0
    for r in runs["asic_credit"][0]:
        a = r.payload.get("afsl_number")
        if a and a in afsl:
            k1 = {i for i in r.identifiers if i.scheme in (IdScheme.ABN, IdScheme.ACN)}
            k2 = {i for i in afsl[a].identifiers if i.scheme in (IdScheme.ABN, IdScheme.ACN)}
            assert k1 & k2 or r.name_raw == afsl[a].name_raw, (r.record_id, a)
            checked += 1
    assert checked > 300


# ------------------------------------------------------------------ party typing


@pytest.mark.parametrize(
    "name,comma,expected",
    [
        ("SMITH & CO", False, PartyType.ORGANISATION),
        ("J SMITH PTY LTD", False, PartyType.ORGANISATION),
        ("THE TRUSTEE FOR SMITH FAMILY TRUST", False, PartyType.ORGANISATION),
        ("F PALMER & M E PALMER", False, PartyType.ORGANISATION),
        ("SMITH, JOHN", True, PartyType.PERSON),
        ("DOUGLAS HOWARD HEWITT", False, PartyType.PERSON),
    ],
)
def test_classify_party_basics(name, comma, expected):
    assert tier2.classify_party(name, comma_person_format=comma)[0] is expected


@pytest.mark.finding
@pytest.mark.parametrize(
    "name",
    ["CHURCH, JOHN", "KIM, SE JIN", "PARK, SA RA", "BANK, MARY", "UNION, PETER", "CAPITAL, ANNA"],
)
def test_comma_format_person_with_org_word_surname_or_given(name):
    """Surnames/given names that collide with _ORG_WORDS tokens (CHURCH, SE, SA, BANK...).
    Judgement call: no such row in this snapshot, but the 'LAST, GIVEN' shape is decisive
    in the credit/liquidator registers and the org-word check runs first."""
    assert tier2.classify_party(name, comma_person_format=True)[0] is PartyType.PERSON


@pytest.mark.finding
def test_gleif_sole_proprietor_business_name_not_typed_person(runs):
    """GLEIF 25490025KDEUE89ESO89 'Mega Clicks' (SOLE_PROPRIETOR) is typed PERSON by the
    'two alphabetic tokens' rule; it is a business name."""
    r = by_id(runs, "gleif_l1")["25490025KDEUE89ESO89"]
    assert r.party_type is not PartyType.PERSON


def test_liquidators_all_people_with_split_names(runs):
    for r in runs["asic_liquidator"][0]:
        assert r.party_type is PartyType.PERSON and r.payload["family_name"] and r.payload["given_names"]
        # Liquidator numbers are now IdScheme.LIQUIDATOR_NO.
        assert [i.scheme for i in r.identifiers] == [IdScheme.LIQUIDATOR_NO]
        assert r.identifier(IdScheme.LIQUIDATOR_NO) == r.record_id.lstrip("0")


def test_no_person_carries_an_acn(runs):
    for s in ("asic_afsl", "asic_credit", "gleif_l1"):
        assert not [r.record_id for r in runs[s][0] if r.party_type is PartyType.PERSON and r.identifier(IdScheme.ACN)]


# ------------------------------------------------------------------ register cross-check (slow)


@pytest.mark.register
@pytest.mark.skipif(
    not COMPANY_ZIP.exists() or not os.environ.get("RUN_REGISTER"), reason="set RUN_REGISTER=1"
)
def test_asic_derived_acns_agree_with_company_register(runs):
    """Every ACN derived from an ABN must exist in the company register with that ABN."""
    want = {}
    for s in ("asic_afsl", "asic_credit"):
        for r in runs[s][0]:
            if r.payload["identifier_provenance"].get("acn") == "derived_from_abn":
                want[r.identifier(IdScheme.ACN)] = r.identifier(IdScheme.ABN)
    reg_abn = defaultdict(set)
    with zipfile.ZipFile(COMPANY_ZIP) as zf, zf.open(zf.namelist()[0]) as fh:
        for chunk in pd.read_csv(fh, sep="\t", dtype=str, keep_default_na=False, quoting=3,
                                 encoding="utf-8-sig", usecols=["ACN", "ABN"], chunksize=500_000):
            hit = chunk[chunk.ACN.isin(want)]
            for acn, abn in zip(hit.ACN, hit.ABN):
                reg_abn[acn].add(abn)
    conflicts = [(a, b, reg_abn[a]) for a, b in want.items() if reg_abn.get(a) and b not in reg_abn[a]]
    assert not conflicts
    assert len(set(want) - set(reg_abn)) <= 2  # BEST BUY AUTO FINANCE (long deregistered)
