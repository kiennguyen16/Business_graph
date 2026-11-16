"""Independent contract tests for the Tier 1 adapters (ABR bulk extract, ASIC company register).

Derived from Requirement.md ("a wrong link is worse than no link"; Tier 1 is the
identity backbone), ARCHITECTURE.md 2.1, the ABR XSD (data/raw/abr/bulkextract.xsd)
and shapes observed in the raw files, not from the author's tests. Fixtures are
small synthetic files written to tmp_path that copy real raw layouts.

Tests marked `finding` are expected to FAIL against the current adapter: each pins a
defect found by the audit (tests/independent/audit_tier1.py).

Run:  .venv/Scripts/python -m pytest tests/independent/test_tier1_contract.py -q -p no:cacheprovider
Real-data checks (slow, read-only on data/raw):  RUN_REAL=1 (same command)
"""

from __future__ import annotations

import os
import shutil
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from bizgraph.domain.models import IdScheme, PartyType
from bizgraph.sources.adapters import tier1
from bizgraph.sources.adapters.tier1 import AbrAdapter, AsicCompanyAdapter
from bizgraph.sources.base import RejectRecord

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
SNAP = date(2026, 11, 16)
REAL = pytest.mark.skipif(not os.environ.get("RUN_REAL"), reason="set RUN_REAL=1 for real-data checks")


def abn_ok(v: str) -> bool:
    if len(v) != 11 or not v.isdigit() or v[0] == "0":
        return False
    d = [int(c) for c in v]
    d[0] -= 1
    return sum(x * w for x, w in zip(d, (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19))) % 89 == 0


def acn_ok(v: str) -> bool:
    if len(v) != 9 or not v.isdigit():
        return False
    s = sum(int(c) * w for c, w in zip(v[:8], range(8, 0, -1)))
    return (10 - s % 10) % 10 == int(v[8])


def make_abn(acn: str) -> str:
    """Company ABN = 2 check digits + ACN (the ATO construction)."""
    for p in range(10, 100):
        if abn_ok(f"{p}{acn}"):
            return f"{p}{acn}"
    raise AssertionError(acn)


# Real ABNs/ACNs seen in the raw extract (checksum-valid).
ACN_QBE = "000000948"
ABN_QBE = "11000000948"
ACN_B = "000002568"
ABN_B = "11000002568"


def _ind_abn(n: int) -> str:
    """Deterministic checksum-valid ABNs for individuals (not derived from an ACN)."""
    out, x = [], 51824753556
    while len(out) <= n:
        if abn_ok(str(x)):
            out.append(str(x))
        x += 1
    return out[n]


# ----------------------------------------------------------------------------- fixtures
def abr_record(
    abn: str,
    etype: str = "PRV",
    etext: str = "Australian Private Company",
    status: str = "ACT",
    status_from: str = "19991101",
    replaced: str = "N",
    org_name: str | None = "QBE INSURANCE (INTERNATIONAL) LTD",
    person: tuple[str | None, list[str], str] | None = None,
    state: str = "WA",
    postcode: str = "6000",
    asic: str | None = None,
    asic_type: str = "undetermined",
    gst: tuple[str, str] | None = ("ACT", "20000701"),
    dgr: list[tuple[str, str, str]] = (),
    other: list[tuple[str, str]] = (),
) -> str:
    addr = f"<BusinessAddress><AddressDetails><State>{state}</State><Postcode>{postcode}</Postcode></AddressDetails></BusinessAddress>"
    if person is not None:
        title, given, family = person
        t = f"<NameTitle>{title}</NameTitle>" if title else ""
        g = "".join(f"<GivenName>{x}</GivenName>" for x in given)
        holder = f'<LegalEntity><IndividualName type="LGL">{t}{g}<FamilyName>{family}</FamilyName></IndividualName>{addr}</LegalEntity>'
    else:
        holder = f'<MainEntity><NonIndividualName type="MN"><NonIndividualNameText>{org_name}</NonIndividualNameText></NonIndividualName>{addr}</MainEntity>'
    a = "" if asic is None else f'<ASICNumber ASICNumberType="{asic_type}">{asic}</ASICNumber>'
    gs = "" if gst is None else f'<GST status="{gst[0]}" GSTStatusFromDate="{gst[1]}" />'
    d = "".join(
        f'<DGR DGRStatusFromDate="{f}" status="{s}"><NonIndividualName type="DGR"><NonIndividualNameText>{n}</NonIndividualNameText></NonIndividualName></DGR>'
        for s, f, n in dgr
    )
    o = "".join(
        f'<OtherEntity><NonIndividualName type="{t}"><NonIndividualNameText>{n}</NonIndividualNameText></NonIndividualName></OtherEntity>'
        for t, n in other
    )
    return (
        f'<ABR recordLastUpdatedDate="20180216" replaced="{replaced}"><ABN status="{status}" ABNStatusFromDate="{status_from}">{abn}</ABN>'
        f"<EntityType><EntityTypeInd>{etype}</EntityTypeInd><EntityTypeText>{etext}</EntityTypeText></EntityType>"
        f"{holder}{a}{gs}{d}{o}</ABR>"
    )


def abr_file(path: Path, records: list[str]) -> Path:
    head = (
        '<?xml version="1.0"?><Transfer error="none" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:noNamespaceSchemaLocation="BulkExtract.xsd"><TransferInfo><FileSequenceNumber>1</FileSequenceNumber>'
        f"<RecordCount>{len(records)}</RecordCount><ExtractTime>2026-11-11T12:20:05</ExtractTime></TransferInfo>\n"
    )
    path.write_text(head + "\n".join(records) + "\n</Transfer>", encoding="utf-8")
    return path


def run_abr(path: Path, **kw) -> tuple[list, Counter, int]:
    ad = AbrAdapter(**kw)
    out, rej, n = [], Counter(), 0
    for row in ad.parse(path):
        n += 1
        try:
            rec = ad.to_record(row, SNAP)
        except RejectRecord as e:
            rej[str(e)] += 1
            continue
        out.append((rec, ad.accept(rec)))
    return out, rej, n


def by_id(recs):
    return {r.record_id: r for r, _ in recs}


ASIC_HEADER = [
    "Company Name", "ACN", "Type", "Class", "Sub Class", "Status", "Date of Registration",
    "Date of Deregistration", "Previous State of Registration", "State Registration number",
    "Modified since last report", "Current Name Indicator", "ABN", "Current Name", "Current Name Start Date",
]


def asic_row(name, acn, cur="Y", abn=None, status="REGD", typ="APTY", reg="08/01/1990", dereg="",
             current_name="", start="", cls="LMSH", sub="PROP") -> list[str]:
    abn = make_abn(acn) if abn is None else abn
    return [name, acn, typ, cls, sub, status, reg, dereg, "NSW", "46869041", "", cur, abn, current_name, start]


def asic_file(path: Path, rows: list[list[str]], raw_lines: list[str] = ()) -> Path:
    lines = ["\t".join(ASIC_HEADER)] + ["\t".join(r) for r in rows] + list(raw_lines)
    path.write_bytes(("﻿" + "\r\n".join(lines) + "\r\n").encode("utf-8"))
    return path


def run_asic(path: Path, **kw):
    ad = AsicCompanyAdapter(**kw)
    out, rej, n = [], Counter(), 0
    for row in ad.parse(path):
        n += 1
        try:
            out.append(ad.to_record(row, SNAP))
        except RejectRecord as e:
            rej[str(e)] += 1
    return out, rej, n


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("BIZGRAPH_ABR_STATES", "BIZGRAPH_ABR_STATUSES", "BIZGRAPH_ASIC_STATUSES"):
        monkeypatch.delenv(k, raising=False)


# ============================================================================ ABR
def test_abr_company_gets_abn_and_acn_and_is_organisation(tmp_path):
    f = abr_file(tmp_path / "a.xml", [abr_record(ABN_QBE, etype="PUB", asic=ACN_QBE)])
    (rec, _), = run_abr(f, states="*", statuses="*")[0]
    assert rec.record_id == ABN_QBE
    assert rec.party_type is PartyType.ORGANISATION
    assert rec.identifier(IdScheme.ABN) == ABN_QBE
    assert rec.identifier(IdScheme.ACN) == ACN_QBE
    assert rec.name_raw == "QBE INSURANCE (INTERNATIONAL) LTD"


@pytest.mark.parametrize(
    "etype",
    ["PRV", "PUB", "PTR", "FPT", "DIT", "DTT", "FUT", "SMF", "TRT", "UIE", "OIE", "COP", "SGE", "CGE", "LGE", "TGE", "STR", "SSS"],
)
def test_abr_non_individual_types_are_organisations(tmp_path, etype):
    """Partnerships, trusts, super funds and government entities are not people."""
    f = abr_file(tmp_path / "a.xml", [abr_record(ABN_QBE, etype=etype, org_name="THE TRUSTEE FOR SMITH FAMILY TRUST")])
    (rec, _), = run_abr(f, states="*", statuses="*")[0]
    assert rec.party_type is PartyType.ORGANISATION


def test_abr_individual_name_assembly(tmp_path):
    ab = [_ind_abn(i) for i in range(4)]
    recs = [
        abr_record(ab[0], etype="IND", etext="Individual/Sole Trader", person=("MR", ["JOHN", "PAUL"], "SMITH")),
        abr_record(ab[1], etype="IND", etext="Individual/Sole Trader", person=(None, [], "MADONNA")),
        abr_record(ab[2], etype="IND", etext="Individual/Sole Trader", person=("DR", ["MARY"], "O'BRIEN")),
        abr_record(ab[3], etype="IND", etext="Individual/Sole Trader", person=(None, ["  ", "ANNE"], "LEE")),
    ]
    out = by_id(run_abr(abr_file(tmp_path / "a.xml", recs), states="*", statuses="*")[0])
    assert all(r.party_type is PartyType.PERSON for r in out.values())
    assert out[ab[0]].name_raw == "JOHN PAUL SMITH"  # title kept out of the name
    assert out[ab[0]].payload["name_title"] == "MR"
    assert out[ab[0]].payload["given_names"] == ["JOHN", "PAUL"]
    assert out[ab[1]].name_raw == "MADONNA"
    assert out[ab[2]].name_raw == "MARY O'BRIEN"
    assert out[ab[3]].name_raw == "ANNE LEE"


@pytest.mark.finding
@pytest.mark.parametrize(
    "etype,abn,name,asic",
    [
        # Real records: the ASICNumber is the corporate TRUSTEE's / another body's ACN (that ACN has its own ABN).
        ("TRT", "41877448580", "The Trustee for ICM ELECTRICS TRUST", "059820281"),
        ("PTR", "31199125391", "MARK &amp; AMANDA CATHERINE SELBY", "154100651"),
    ],
)
def test_abr_trust_or_partnership_does_not_take_another_entitys_acn(tmp_path, etype, abn, name, asic):
    """A trust / partnership is not a company. When its ASICNumber is not ABN[2:], it is
    another legal entity's ACN; emitting it as this party's ACN identifier makes the exact
    ACN path merge the trust with its trustee company."""
    f = abr_file(tmp_path / "a.xml", [abr_record(abn, etype=etype, org_name=name, asic=asic)])
    (rec, _), = run_abr(f, states="*", statuses="*")[0]
    assert rec.identifier(IdScheme.ACN) is None


@pytest.mark.finding
def test_abr_individual_never_gets_acn(tmp_path):
    """An individual cannot hold an ACN; a 9-digit ASICNumber on IND must not become one.
    Latent: 0 of 11.24M IND records carry an ASICNumber in the 2026-11-11 extract."""
    f = abr_file(tmp_path / "a.xml", [abr_record(_ind_abn(0), etype="IND", person=(None, ["A"], "B"), asic=ACN_B)])
    (rec, _), = run_abr(f, states="*", statuses="*")[0]
    assert rec.identifier(IdScheme.ACN) is None


@pytest.mark.parametrize("asic", ["", "   ", "12345678", "000002569", "0000025680", "N/A"])
def test_abr_invalid_asic_number_yields_no_acn_but_keeps_record(tmp_path, asic):
    f = abr_file(tmp_path / "a.xml", [abr_record(ABN_B, asic=asic)])
    (rec, _), = run_abr(f, states="*", statuses="*")[0]
    assert rec.identifier(IdScheme.ACN) is None
    assert rec.identifier(IdScheme.ABN) == ABN_B
    assert rec.payload["asic_number_valid"] is False


@pytest.mark.finding
def test_abr_all_zero_asic_number_is_not_an_acn(tmp_path):
    """'000000000' passes the ACN check digit (sum 0 -> check 0) but is not an ACN.

    Emitting it makes every record carrying it share one exact-match key. Real case:
    ABN 43695732660 (PUB, THE AUSTRALIAN BIRTHRIGHT MOVEMENT, CAN) has ASICNumber 000000000.
    """
    f = abr_file(tmp_path / "a.xml", [abr_record(ABN_B, asic="000000000")])
    (rec, _), = run_abr(f, states="*", statuses="*")[0]
    assert rec.identifier(IdScheme.ACN) is None


def test_abr_invalid_abn_rejected_with_reason_and_counted(tmp_path):
    bad = ABN_B[:-1] + str((int(ABN_B[-1]) + 1) % 10)
    f = abr_file(tmp_path / "a.xml", [abr_record(bad), abr_record(ABN_QBE)])
    recs, rej, n = run_abr(f, states="*", statuses="*")
    assert n == 2 and len(recs) == 1
    assert rej == Counter({"invalid_abn_checksum": 1})


def test_abr_dates_and_sentinel(tmp_path):
    f = abr_file(
        tmp_path / "a.xml",
        [abr_record(ABN_B, status="CAN", status_from="20190501", gst=("NON", "19000101"),
                    dgr=[("ACT", "19000101", "QBE FOUNDATION")])],
    )
    (rec, _), = run_abr(f, states="*", statuses="*")[0]
    p = rec.payload
    assert p["abn_status"] == "CAN"
    assert p["abn_status_from"] == "2019-05-01"
    assert p["gst_status"] == "NON" and p["gst_status_from"] is None
    assert p["dgr"][0]["status_from"] is None and p["dgr"][0]["name"] == "QBE FOUNDATION"
    assert p["record_last_updated"] == "2018-02-16"


def test_abr_other_names_captured_in_order(tmp_path):
    other = [("TRD", "SNP SECURITY"), ("OTN", "SECURITY NETWORK PROTECTION"), ("BN", "BCD SECURITY ALARM")]
    f = abr_file(tmp_path / "a.xml", [abr_record(ABN_B, other=other)])
    (rec, _), = run_abr(f, states="*", statuses="*")[0]
    assert [(o["type"], o["name"]) for o in rec.payload["other_names"]] == other


def test_abr_replaced_flag_preserved(tmp_path):
    f = abr_file(tmp_path / "a.xml", [abr_record(ABN_B, replaced="Y")])
    (rec, _), = run_abr(f, states="*", statuses="*")[0]
    assert rec.payload["replaced"] == "Y"


def test_abr_xml_entities_decoded(tmp_path):
    f = abr_file(tmp_path / "a.xml", [abr_record(ABN_B, org_name="SYDNEY NIGHT PATROL &amp; INQUIRY CO PTY LTD")])
    (rec, _), = run_abr(f, states="*", statuses="*")[0]
    assert rec.name_raw == "SYDNEY NIGHT PATROL & INQUIRY CO PTY LTD"


# ---- slice
def _slice_fixture(tmp_path):
    return abr_file(
        tmp_path / "a.xml",
        [
            abr_record(ABN_QBE, state="WA", status="ACT"),
            abr_record(ABN_B, state="TAS", status="CAN"),
            abr_record(_ind_abn(0), etype="IND", person=(None, ["A"], "B"), state="NSW", status="ACT"),
            abr_record(_ind_abn(1), etype="IND", person=(None, ["C"], "D"), state="", status="ACT"),
        ],
    )


def test_abr_default_slice_is_active_wa_tas(tmp_path):
    recs, _, _ = run_abr(_slice_fixture(tmp_path))
    assert {r.record_id for r, acc in recs if acc} == {ABN_QBE}


def test_abr_slice_env_vars_and_star(tmp_path, monkeypatch):
    f = _slice_fixture(tmp_path)
    monkeypatch.setenv("BIZGRAPH_ABR_STATES", "*")
    monkeypatch.setenv("BIZGRAPH_ABR_STATUSES", "act")
    recs, _, _ = run_abr(f)
    assert {r.record_id for r, acc in recs if acc} == {ABN_QBE, _ind_abn(0), _ind_abn(1)}
    monkeypatch.setenv("BIZGRAPH_ABR_STATES", "nsw, tas")
    monkeypatch.setenv("BIZGRAPH_ABR_STATUSES", "*")
    recs, _, _ = run_abr(f)
    assert {r.record_id for r, acc in recs if acc} == {ABN_B, _ind_abn(0)}


def test_abr_blank_state_is_none(tmp_path):
    recs, _, _ = run_abr(_slice_fixture(tmp_path), states="*", statuses="*")
    assert by_id(recs)[_ind_abn(1)].payload["state"] is None


# ---- input shapes, hashing, accounting
def test_abr_zip_and_dir_inputs_equivalent_and_hash_independent_of_file_name(tmp_path):
    recs = [abr_record(ABN_QBE, asic=ACN_QBE, other=[("BN", "QBE")]), abr_record(ABN_B)]
    x1 = abr_file(tmp_path / "20261111_Public01.xml", recs)
    d2 = tmp_path / "other"
    d2.mkdir()
    x2 = d2 / "renamed_something_else.xml"
    shutil.copy(x1, x2)
    z = tmp_path / "public_split_1_10.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(x1, "20261111_Public01.xml")
    h = []
    for src in (x1, x2, z, d2):
        recs_, _, _ = run_abr(src, states="*", statuses="*")
        h.append({r.record_id: r.content_hash for r, _ in recs_})
    assert h[0] == h[1] == h[2] == h[3] and len(h[0]) == 2


class _FakeStore:
    class _Snap:
        def file_hash(self, p):
            return "h"

        def exists(self, s, h):
            return False

        def record(self, *a, **k):
            pass

    class _Rec:
        def __init__(self):
            self.seen = []

        def upsert(self, batch, adapter_version=None):
            self.seen.extend(batch)
            return len(batch)

    def __init__(self):
        self.snapshots = self._Snap()
        self.records = self._Rec()


def test_abr_run_accounts_every_record(tmp_path):
    bad = ABN_B[:-1] + str((int(ABN_B[-1]) + 1) % 10)
    f = _slice_fixture(tmp_path)
    text = f.read_text(encoding="utf-8").replace("</Transfer>", abr_record(bad) + "\n</Transfer>")
    f.write_text(text, encoding="utf-8")
    store = _FakeStore()
    stats = AbrAdapter().run(f, SNAP, store)
    assert stats.records_in == 5
    assert stats.records_in == stats.records_new + stats.records_unchanged + stats.records_rejected
    assert stats.rejection_reasons == Counter({"outside_slice": 3, "invalid_abn_checksum": 1})
    assert [r.record_id for r in store.records.seen] == [ABN_QBE]


# ---- name normalisation as used by Tier 1
@pytest.mark.finding
@pytest.mark.parametrize(
    "raw",
    ["The Trustee for Drum Line Trust", "THE TRUSTEE FOR REITBERGER SUPER FUND", "The Trustee for SMITH FAMILY TRUST"],
)
def test_abr_trust_name_norm_is_not_the_bare_word_the(tmp_path, raw):
    """ABR trusts are named 'The Trustee for X'. name_norm must keep X, not collapse to 'THE'.

    On real data ~40% of non-individual ABR records collapse to the same norm, so a
    NAME_NORMALISED_EXACT path or a norm-based block would put them all together.
    """
    f = abr_file(tmp_path / "a.xml", [abr_record(ABN_B, etype="DIT", org_name=raw)])
    (rec, _), = run_abr(f, states="*", statuses="*")[0]
    assert rec.name_norm not in (None, "", "THE")
    assert any(tok in rec.name_norm for tok in raw.upper().split()[3:])


# ============================================================================ ASIC
def test_asic_groups_names_one_record_per_acn(tmp_path):
    acn = "000000019"
    f = asic_file(
        tmp_path / "c.csv",
        [
            asic_row("LOVINI HOLDINGS PTY LTD", acn, cur="", current_name="MONAKA PTY LTD", start="28/01/2016"),
            asic_row("MONAKA PTY LTD", acn),
            asic_row("OLDER NAME PTY LTD", acn, cur="", current_name="MONAKA PTY LTD", start="28/01/2016"),
            asic_row("CHRISTENSEN & ASSOCIATES PTY LTD", "000000028"),
        ],
    )
    recs, rej, n = run_asic(f)
    assert n == 2 and not rej
    r = {x.record_id: x for x in recs}
    assert r[acn].name_raw == "MONAKA PTY LTD"
    assert r[acn].payload["former_names"] == ["LOVINI HOLDINGS PTY LTD", "OLDER NAME PTY LTD"]
    assert r[acn].payload["current_name_start_date"] == "2016-01-28"
    assert r[acn].identifier(IdScheme.ACN) == acn and r[acn].identifier(IdScheme.ABN) == make_abn(acn)
    assert r[acn].party_type is PartyType.ORGANISATION


@pytest.mark.finding
def test_asic_grouping_does_not_depend_on_row_adjacency(tmp_path):
    """One record per ACN is the contract. The Nov-2026 file happens to be ACN-contiguous
    (verified by the audit), but nothing enforces it; a re-sorted file silently yields
    two records with the same record_id."""
    acn = "000000019"
    f = asic_file(
        tmp_path / "c.csv",
        [
            asic_row("LOVINI HOLDINGS PTY LTD", acn, cur="", current_name="MONAKA PTY LTD", start="28/01/2016"),
            asic_row("CHRISTENSEN & ASSOCIATES PTY LTD", "000000028"),
            asic_row("MONAKA PTY LTD", acn),
        ],
    )
    recs, _, _ = run_asic(f)
    ids = Counter(r.record_id for r in recs)
    assert ids[acn] == 1


def test_asic_company_without_current_row_uses_current_name_column(tmp_path):
    acn = "002849327"
    f = asic_file(
        tmp_path / "c.csv",
        [
            asic_row("GALDFEN PTY LTD" + " " * 80, acn, cur="", abn="0", status="CNCL",
                     current_name="JARDEN MORGAN SECURITIES PTY LTD" + " " * 60, start="20/09/2010"),
            asic_row("PAUL MORGAN & CO (N S W) PTY LTD", acn, cur="", abn="0", status="CNCL",
                     current_name="JARDEN MORGAN SECURITIES PTY LTD" + " " * 60, start="20/09/2010"),
        ],
    )
    (rec,), rej, _ = run_asic(f)
    assert rec.name_raw == "JARDEN MORGAN SECURITIES PTY LTD"
    assert rec.payload["former_names"] == ["GALDFEN PTY LTD", "PAUL MORGAN & CO (N S W) PTY LTD"]
    assert rec.payload["no_current_name_row"] is True
    assert rec.identifier(IdScheme.ABN) is None
    assert rec.payload["status"] == "CNCL"


@pytest.mark.parametrize("abn", ["0", "", "12345678901", "1100000056"])
def test_asic_abn_zero_blank_invalid_not_emitted(tmp_path, abn):
    f = asic_file(tmp_path / "c.csv", [asic_row("X PTY LTD", "000000055", abn=abn)])
    (rec,), _, _ = run_asic(f)
    assert rec.identifier(IdScheme.ABN) is None
    assert rec.identifier(IdScheme.ACN) == "000000055"


def test_asic_dates_and_padding(tmp_path):
    f = asic_file(
        tmp_path / "c.csv",
        [
            asic_row("PADDED PTY LTD" + " " * 86, "000000046", status="DRGD", reg="17/03/1988", dereg="01/02/2003"),
            asic_row("NO DATES PTY LTD", "000000055", reg="", dereg=""),
        ],
    )
    recs, _, _ = run_asic(f)
    r = {x.record_id: x for x in recs}
    assert r["000000046"].name_raw == "PADDED PTY LTD"
    assert r["000000046"].payload["date_of_registration"] == "1988-03-17"
    assert r["000000046"].payload["date_of_deregistration"] == "2003-02-01"
    assert r["000000055"].payload["date_of_registration"] is None
    assert r["000000055"].payload["date_of_deregistration"] is None


def test_asic_csv_quoting_as_in_real_file(tmp_path):
    """Real rows: a name field fully quoted with doubled quotes, and a bare quote mid-field."""
    acn1, acn2 = "001996890", "000842160"
    raw = [
        "\t".join(['"""OAKLAN"" INVESTMENTS PTY LIMITED"', acn1, "APTY", "LMSH", "PROP", "REGD", "26/09/1980", "", "NSW",
                   "25416306", "", "Y", make_abn(acn1), "", ""]),
        "\t".join(["KLENAIL PTY LTD", acn1, "APTY", "LMSH", "PROP", "REGD", "26/09/1980", "", "NSW", "25416306", "", "",
                   make_abn(acn1), '"""OAKLAN"" INVESTMENTS PTY LIMITED"', "20/04/2001"]),
        "\t".join(['FEDERATION OF SYDNEY & NSW "KARAISKAKIS" LIMITED', acn2, "APUB", "LMGT", "ULSN", "REGD", "01/01/1970",
                   "", "NSW", "1", "", "Y", make_abn(acn2), "", ""]),
    ]
    recs, rej, n = run_asic(asic_file(tmp_path / "c.csv", [], raw_lines=raw))
    r = {x.record_id: x for x in recs}
    assert n == 2
    assert r[acn1].name_raw == '"OAKLAN" INVESTMENTS PTY LIMITED'
    assert r[acn1].payload["former_names"] == ["KLENAIL PTY LTD"]
    assert r[acn2].name_raw == 'FEDERATION OF SYDNEY & NSW "KARAISKAKIS" LIMITED'


def test_asic_invalid_acn_rejected(tmp_path):
    f = asic_file(tmp_path / "c.csv", [asic_row("X PTY LTD", "000000056", abn="0")])
    _, rej, n = run_asic(f)
    assert n == 1 and rej == Counter({"invalid_acn_checksum": 1})


@pytest.mark.finding
@pytest.mark.parametrize("typ", ["FNOS", "RACN"])
def test_asic_registered_bodies_are_arbn_not_acn(tmp_path, typ):
    """FNOS (foreign company) and RACN (registered Australian body) carry an ARBN in the
    ACN column. IdScheme has ARBN; labelling it ACN makes ACN-scheme joins and the
    'ACN under two names' invariant mix two identifier kinds."""
    f = asic_file(tmp_path / "c.csv", [asic_row("BNP PARIBAS", "000000117", typ=typ, cls="NONE", sub="NONE", abn="0")])
    (rec,), _, _ = run_asic(f)
    assert rec.identifier(IdScheme.ACN) is None
    assert rec.identifier(IdScheme.ARBN) == "000000117"


def test_asic_status_slice(tmp_path, monkeypatch):
    f = asic_file(tmp_path / "c.csv", [asic_row("A PTY LTD", "000000019"), asic_row("B PTY LTD", "000000028", status="DRGD")])
    monkeypatch.setenv("BIZGRAPH_ASIC_STATUSES", "regd")
    ad = AsicCompanyAdapter()
    kept = [r.record_id for r in (ad.to_record(x, SNAP) for x in ad.parse(f)) if ad.accept(r)]
    assert kept == ["000000019"]


def test_asic_hash_stable_and_independent_of_file_name(tmp_path):
    rows = [asic_row("MONAKA PTY LTD", "000000019"), asic_row("CHRISTENSEN PTY LTD", "000000028")]
    f1 = asic_file(tmp_path / "COMPANY_202611.csv", rows)
    f2 = asic_file(tmp_path / "renamed.tsv", rows)
    z = tmp_path / "company_202611.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(f1, "COMPANY_202611.csv")
    hs = [{r.record_id: r.content_hash for r in run_asic(p)[0]} for p in (f1, f2, z, f1)]
    assert hs[0] == hs[1] == hs[2] == hs[3]


# ============================================================================ real data
@REAL
def test_real_asic_adjacency_and_record_count():
    """Every ACN appears in exactly one contiguous run, and the adapter emits one record per ACN."""
    import duckdb

    z = RAW / "asic_company" / "company_202611.zip"
    with zipfile.ZipFile(z) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        tmp = Path(os.environ.get("TEMP", "/tmp")) / "bizgraph_audit_tier1"
        tmp.mkdir(exist_ok=True)
        p = tmp / Path(name).name
        if not p.exists():
            zf.extract(name, tmp)
    con = duckdb.connect()
    con.execute(f"""create table a as select row_number() over () rn, ACN from read_csv('{p.as_posix()}', delim='\t',
                 header=true, all_varchar=true, quote='"', escape='"', strict_mode=false)""")
    distinct, runs = con.execute(
        "select (select count(distinct ACN) from a), count(*) from (select ACN, lag(ACN) over (order by rn) p from a) "
        "where p is null or ACN<>p"
    ).fetchone()
    assert distinct == runs
    n_groups = sum(1 for _ in AsicCompanyAdapter(statuses="*").parse(z))
    assert n_groups == distinct


@REAL
def test_real_abr_sample_records_in_equals_raw_and_types_consistent():
    """First 50k records of Public15: nothing silently dropped, IND <-> LegalEntity <-> PERSON."""
    from lxml import etree

    z = RAW / "abr" / "public_split_11_20.zip"
    member = "20261111_Public15.xml"
    n = 50_000

    class Lim:
        def __init__(self):
            self.fh = zipfile.ZipFile(z).open(member)
            self.k, self.buf, self.done = 0, b"", False

        def read(self, size=-1):
            while not self.done and len(self.buf) < max(size, 1 << 16):
                line = self.fh.readline()
                if not line:
                    self.done = True
                    break
                if b"<ABR " in line:
                    self.k += 1
                    if self.k > n:
                        self.buf += b"</Transfer>"
                        self.done = True
                        break
                self.buf += line
            out, self.buf = (self.buf, b"") if size < 0 else (self.buf[:size], self.buf[size:])
            return out

    raw = {}
    for _, el in etree.iterparse(Lim(), events=("end",), tag="ABR"):
        raw[el.findtext("ABN")] = el.find("LegalEntity") is not None
        el.clear()
    orig = tier1._iter_members
    tier1._iter_members = lambda path, suffixes: iter([(member, Lim())])
    try:
        recs, rej, n_in = run_abr(Path("x"), states="*", statuses="*")
    finally:
        tier1._iter_members = orig
    assert n_in == len(raw) == n
    assert sum(rej.values()) + len(recs) == n_in
    for rec, _ in recs:
        assert (rec.party_type is PartyType.PERSON) == raw[rec.record_id]
