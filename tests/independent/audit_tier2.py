"""Independent audit of the Tier 2 adapters against the REAL raw files.

Run:  .venv/Scripts/python tests/independent/audit_tier2.py [--no-register]

Written by an independent tester. It does not use the author's tests and only
uses the adapters as the system under test: identifier checksums are
re-implemented here, coverage is recomputed straight from the raw CSVs with
pandas, and emitted ACNs are cross-checked against the ASIC company register
(data/raw/asic_company/company_202611.zip) when it is present.

Prints a sectioned report to stdout. Read-only on data/raw.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from bizgraph.domain.models import IdScheme, PartyType  # noqa: E402
from bizgraph.sources.adapters import tier2  # noqa: E402
from bizgraph.sources.base import RejectRecord  # noqa: E402

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

# ----------------------------------------------------------------- independent checksums


def abn_ok(v: str) -> bool:
    if not re.fullmatch(r"[1-9]\d{10}", v or ""):
        return False
    d = [int(c) for c in v]
    d[0] -= 1
    w = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
    return sum(a * b for a, b in zip(d, w)) % 89 == 0


def acn_ok(v: str) -> bool:
    if not re.fullmatch(r"\d{9}", v or ""):
        return False
    s = sum(int(v[i]) * (8 - i) for i in range(8))
    return (10 - s % 10) % 10 == int(v[8])


def lei_ok(v: str) -> bool:
    if not re.fullmatch(r"[0-9A-Z]{18}\d{2}", v or ""):
        return False
    return int("".join(str(int(c, 36)) for c in v)) % 97 == 1


CHECK = {IdScheme.ABN: abn_ok, IdScheme.ACN: acn_ok, IdScheme.LEI: lei_ok}

# ----------------------------------------------------------------- independent name compare

_LEGAL = {
    "PTY", "LTD", "LIMITED", "PROPRIETARY", "THE", "CO", "COMPANY", "NL", "INC",
    "INCORPORATED", "CORP", "CORPORATION", "AND",
}


def nkey(name: str) -> str:
    s = (name or "").upper().replace("&", " AND ")
    s = re.sub(r"\(.*?\)", " ", s)  # drop "(FORMERLY ...)" style asides
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    toks = [t for t in s.split() if t not in _LEGAL]
    return " ".join(toks)


def sim(a: str, b: str) -> float:
    ka, kb = nkey(a), nkey(b)
    if not ka or not kb:
        return 0.0
    return difflib.SequenceMatcher(None, ka, kb).ratio()


def best_sim(name: str, candidates: set[str]) -> tuple[float, str]:
    best = (0.0, "")
    for c in candidates:
        s = sim(name, c)
        if s > best[0]:
            best = (s, c)
    return best


# ----------------------------------------------------------------- run adapters


def run_adapter(source: str):
    ad = ADAPTERS[source]()
    path = FILES[source]
    recs, rejects, n_in = [], Counter(), 0
    rows = []
    for row in ad.parse(path):
        n_in += 1
        rows.append(row)
        try:
            recs.append(ad.to_record(row, SNAP))
        except RejectRecord as exc:
            rejects[str(exc)] += 1
    return recs, rejects, n_in, rows


def hdr(t: str) -> None:
    print("\n" + "=" * 100 + f"\n{t}\n" + "=" * 100)


def raw_df(source: str) -> pd.DataFrame:
    p = FILES[source]
    first = p.open(encoding="utf-8-sig").readline()
    sep = "\t" if first.count("\t") > first.count(",") else ","
    return pd.read_csv(p, sep=sep, dtype=str, keep_default_na=False, encoding="utf-8-sig")


# ----------------------------------------------------------------- company register


def load_register(acns: set[str], abns: set[str]):
    """ACN -> {names}, ACN -> {abns}, ACN -> status ; ABN -> {acns} (only for wanted keys)."""
    by_acn_names: dict[str, set[str]] = defaultdict(set)
    by_acn_abn: dict[str, set[str]] = defaultdict(set)
    by_acn_status: dict[str, str] = {}
    by_acn_type: dict[str, str] = {}
    abn_to_acn: dict[str, set[str]] = defaultdict(set)
    with zipfile.ZipFile(COMPANY_ZIP) as zf:
        member = zf.namelist()[0]
        with zf.open(member) as fh:
            for chunk in pd.read_csv(
                fh, sep="\t", dtype=str, keep_default_na=False, encoding="utf-8-sig",
                chunksize=500_000, quoting=3,
                usecols=["Company Name", "ACN", "Type", "Status", "ABN", "Current Name"],
            ):
                hit = chunk[chunk["ACN"].isin(acns) | chunk["ABN"].isin(abns)]
                for r in hit.itertuples(index=False):
                    acn = r[1]
                    by_acn_names[acn].add(r[0])
                    if r[5]:
                        by_acn_names[acn].add(r[5])
                    if r[4]:
                        by_acn_abn[acn].add(r[4])
                        abn_to_acn[r[4]].add(acn)
                    by_acn_status[acn] = r[3]
                    by_acn_type[acn] = r[2]
    return by_acn_names, by_acn_abn, by_acn_status, by_acn_type, abn_to_acn


# ----------------------------------------------------------------- main


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-register", action="store_true")
    args = ap.parse_args()

    R, REJ, NIN, ROWS = {}, {}, {}, {}
    for s in ADAPTERS:
        R[s], REJ[s], NIN[s], ROWS[s] = run_adapter(s)

    # ------------------------------------------------------------ 1 counts
    hdr("1. Row accounting: raw rows (pandas) vs adapter records_in / emitted / rejected")
    for s in ADAPTERS:
        df = raw_df(s)
        print(f"{s:18s} raw={len(df):>7} records_in={NIN[s]:>7} emitted={len(R[s]):>7} "
              f"rejected={sum(REJ[s].values()):>5} {dict(REJ[s])}")
        if len(df) != NIN[s]:
            print(f"   !! raw row count differs from records_in by {NIN[s] - len(df)}")

    # ------------------------------------------------------------ 2 checksums
    hdr("2. Independent checksum of every emitted ABN/ACN/LEI")
    for s, recs in R.items():
        bad = []
        n = Counter()
        for r in recs:
            for i in r.identifiers:
                n[i.scheme.value] += 1
                f = CHECK.get(i.scheme)
                if f and not f(i.value):
                    bad.append((r.record_id, i))
        print(f"{s:18s} ids={dict(n)} checksum_failures={len(bad)} {bad[:5]}")

    # ------------------------------------------------------------ 3 record_id uniqueness / stability
    hdr("3. record_id uniqueness and run-twice stability")
    for s in ADAPTERS:
        ids = Counter(r.record_id for r in R[s])
        dups = [(k, v) for k, v in ids.items() if v > 1]
        recs2, _, _, _ = run_adapter(s)
        a = {(r.record_id, r.content_hash, r.identifiers, r.party_type, r.name_norm) for r in R[s]}
        b = {(r.record_id, r.content_hash, r.identifiers, r.party_type, r.name_norm) for r in recs2}
        print(f"{s:18s} unique_ids={len(ids)} dup_ids={len(dups)} {dups[:5]} stable={a == b}")
        if dups:
            for k, _ in dups[:3]:
                same = [r for r in R[s] if r.record_id == k]
                hashes = {r.content_hash for r in same}
                print(f"   dup {k}: {len(same)} records, {len(hashes)} distinct content hashes; "
                      f"names={[r.name_raw for r in same]}")

    # ------------------------------------------------------------ 4 coverage (independent, pandas)
    hdr("4. Identifier coverage recomputed from raw with pandas (no adapter code)")
    company_form = re.compile(r"\b(PTY|PROPRIETARY|LTD|LIMITED|NL|NO LIABILITY)\b", re.I)
    for s, col, namecol in [
        ("asic_afsl", "AFS_LIC_ABN_ACN", "AFS_LIC_NAME"),
        ("asic_credit", "CRED_LIC_ABN_ACN", "CRED_LIC_NAME"),
    ]:
        df = raw_df(s)
        d = df[col].str.replace(r"\D", "", regex=True)
        is_abn = d.str.len().eq(11) & d.map(abn_ok)
        acn_stated = d.str.len().between(1, 9) & d.str.zfill(9).map(acn_ok) & ~d.str.fullmatch("0+")
        derived = is_abn & df[namecol].str.contains(company_form) & d.str[2:].map(acn_ok)
        zeros = d.eq("") | d.str.fullmatch("0+")
        other = ~(is_abn | acn_stated | zeros)
        n = len(df)
        print(f"{s}: rows={n} valid_abn={is_abn.sum()} acn_stated={acn_stated.sum()} "
              f"(zero-padded {int((acn_stated & d.str.len().lt(9)).sum())}) derived_acn={derived.sum()} "
              f"acn_any={int((acn_stated | derived).sum())} abn_or_acn={int((is_abn | acn_stated).sum())} "
              f"absent={zeros.sum()} invalid_other={other.sum()} "
              f"len_dist={d.str.len().value_counts().to_dict()}")
        if other.any():
            print("   invalid/other raw values:", df.loc[other, [namecol, col]].head(10).values.tolist())
        if s == "asic_credit":
            a = df["CRED_LIC_AFSL_NUM"].str.replace(r"\D", "", regex=True).str.lstrip("0")
            print(f"   credit with AFSL number: {int(a.ne('').sum())}; status={df.CRED_LIC_STATUS.value_counts().to_dict()}"
                  f"; end_dt non-empty={int(df.CRED_LIC_END_DT.ne('').sum())}")
    df = raw_df("asic_banned_org")
    d = df["BD_ORG_ACN"].str.replace(r"\D", "", regex=True)
    print(f"asic_banned_org: rows={len(df)} valid_acn={int(d.str.zfill(9).map(acn_ok).sum())} "
          f"permanent={int(df.BD_ORG_END_DT.str.contains('ermanent').sum())} "
          f"empty_end={int(df.BD_ORG_END_DT.eq('').sum())}")
    df = raw_df("asic_liquidator")
    print(f"asic_liquidator: rows={len(df)} firm_nonempty={int(df.LIQ_FIRM.ne('').sum())} "
          f"no_comma_names={int((~df.LIQ_NAME.str.contains(',')).sum())} status={df.LIQ_STATUS.value_counts().to_dict()}")

    g = pd.read_csv(FILES["gleif_l1"], dtype=str, keep_default_na=False)
    ra = g["Entity.RegistrationAuthority.RegistrationAuthorityID"]
    eid = g["Entity.RegistrationAuthority.RegistrationAuthorityEntityID"].str.replace(r"\D", "", regex=True)
    c_la = g["Entity.LegalAddress.Country"]
    c_hq = g["Entity.HeadquartersAddress.Country"]
    jur = g["Entity.LegalJurisdiction"].str[:2]
    au = c_la.eq("AU")
    nz = c_la.eq("NZ")
    inreg = c_la.isin(["AU", "NZ"]) | c_hq.isin(["AU", "NZ"]) | jur.isin(["AU", "NZ"])
    g_acn = ra.eq("RA000014") & eid.str.len().between(1, 9) & eid.str.zfill(9).map(acn_ok)
    g_abn = ra.isin(["RA000013", "RA000762", "RA000714"]) & eid.str.len().eq(11) & eid.map(abn_ok)
    print(f"gleif_l1: rows={len(g)} lei_valid={int(g.LEI.map(lei_ok).sum())} in_region={int(inreg.sum())} "
          f"out_of_region={int((~inreg).sum())} legal_addr_AU={int(au.sum())} NZ={int(nz.sum())}")
    print(f"   RA ACN valid={int(g_acn.sum())} RA ABN valid={int(g_abn.sum())} either={int((g_acn | g_abn).sum())}")
    print(f"   among legal_addr AU: acn={int((g_acn & au).sum())} abn={int((g_abn & au).sum())} "
          f"either={int(((g_acn | g_abn) & au).sum())} / {int(au.sum())} = {((g_acn | g_abn) & au).sum() / au.sum():.1%}")
    au_any = c_la.eq("AU") | c_hq.eq("AU") | jur.eq("AU")
    print(f"   AU by (legal|hq|jurisdiction) = {int(au_any.sum())}; either among those={int(((g_acn | g_abn) & au_any).sum())}")
    print("   RA counts for legal_addr AU:", ra[au].value_counts().head(12).to_dict())
    print("   registration status (legal AU):", g.loc[au, "Registration.RegistrationStatus"].value_counts().to_dict())
    print("   SOLE_PROPRIETOR rows:", int(g["Entity.EntityCategory"].eq("SOLE_PROPRIETOR").sum()))
    nzra = ra.eq("RA000466")
    nz_acn_pass = nzra & eid.str.len().between(1, 9) & eid.str.zfill(9).map(acn_ok)
    print(f"   RA000466 rows={int(nzra.sum())}, 13-digit={int((nzra & eid.str.len().eq(13)).sum())}, "
          f"pass ACN checksum by chance={int(nz_acn_pass.sum())}")

    # ------------------------------------------------------------ 5 dates
    hdr("5. Dates: raw formats and silent None")
    date_cols = {
        "asic_afsl": {"AFS_LIC_START_DT": "licence_start"},
        "asic_credit": {"CRED_LIC_START_DT": "licence_start", "CRED_LIC_END_DT": "licence_end"},
        "asic_banned_org": {"BD_ORG_START_DT": "ban_start", "BD_ORG_END_DT": "ban_end"},
        "asic_liquidator": {
            "LIQ_START_DT": "registration_start", "OFF_LIQ_START_DT": "official_liquidator_start",
            "LIQ_SUSP_DT": "suspension_date",
        },
    }
    for s, cols in date_cols.items():
        df = raw_df(s)
        for col, key in cols.items():
            v = df[col].str.strip()
            fmt = v.str.replace(r"\d", "9", regex=True).value_counts().to_dict()
            # map raw row -> emitted record by order (no rejections in these files)
            silent = 0
            mism = 0
            if len(R[s]) == len(df):
                for raw, rec in zip(v, R[s]):
                    got = rec.payload.get(key)
                    if raw and re.fullmatch(r"\d{2}/\d{2}/\d{4}", raw):
                        exp = datetime.strptime(raw, "%d/%m/%Y").date().isoformat()
                        if got is None:
                            silent += 1
                        elif got != exp:
                            mism += 1
            errs = sum(1 for r in R[s] if key in (r.payload.get("date_errors") or {}))
            print(f"{s:16s} {col:18s} formats={fmt} silent_none={silent} wrong={mism} date_errors={errs}")
    # credit status history
    sh = Counter()
    for r in R["asic_credit"]:
        for h in r.payload["status_history"]:
            sh["parsed" if h["start"] else "unparsed"] += 1
    df = raw_df("asic_credit")
    print("credit status_history segments:", dict(sh), "raw non-empty rows:",
          int(df.CRED_LIC_STATUS_HISTORY.ne("").sum()))
    print("   samples:", df.loc[df.CRED_LIC_STATUS_HISTORY.ne(""), "CRED_LIC_STATUS_HISTORY"].head(5).tolist())
    # GLEIF L2 periods
    rr = pd.read_csv(FILES["gleif_l2"], dtype=str, keep_default_na=False)
    for i in range(1, 6):
        for c in ("startDate", "endDate"):
            col = f"Relationship.Period.{i}.{c}"
            vals = rr[col][rr[col] != ""]
            if len(vals):
                fmts = vals.str.replace(r"\d", "9", regex=True).value_counts().head(3).to_dict()
                print(f"gleif_l2 {col}: n={len(vals)} formats={fmts}")
    l2_by_id = {r.record_id: r for r in R["gleif_l2"]}
    nonone = 0
    for row in ROWS["gleif_l2"]:
        k = f"{row.get('Relationship.StartNode.NodeID')}|{row.get('Relationship.RelationshipType')}|{row.get('Relationship.EndNode.NodeID')}"
        rec = l2_by_id.get(k)
        if not rec:
            continue
        nraw = sum(1 for i in range(1, 6) if row.get(f"Relationship.Period.{i}.startDate"))
        nparsed = sum(1 for p in rec.payload["periods"] if p["start"])
        if nraw != nparsed:
            nonone += 1
    print("gleif_l2 period start dates lost in parsing:", nonone)
    rel_period_missing = sum(1 for r in R["gleif_l2"] if r.payload["valid_from"] is None)
    print("gleif_l2 records with no RELATIONSHIP_PERIOD start (valid_from None):", rel_period_missing)
    l1_dates = 0
    for row, rec in zip(ROWS["gleif_l1"], R["gleif_l1"]):
        for raw_key, k in (("Entity.EntityCreationDate", "entity_creation_date"),
                           ("Registration.InitialRegistrationDate", "initial_registration_date")):
            if row.get(raw_key) and rec.payload.get(k) is None:
                l1_dates += 1
    print("gleif_l1 non-empty raw dates parsed to None:", l1_dates)

    # ------------------------------------------------------------ 6 party typing
    hdr("6. Person vs organisation typing")
    for s in ("asic_afsl", "asic_credit", "asic_banned_org", "gleif_l1"):
        recs = R[s]
        pc = Counter(r.party_type.value for r in recs)
        basis = Counter(r.payload.get("party_type_basis") for r in recs)
        print(f"{s}: {dict(pc)} basis={dict(basis)}")
    # all AFSL persons
    afsl_people = [r for r in R["asic_afsl"] if r.party_type is PartyType.PERSON]
    print("\nAFSL PERSON (all):")
    for r in afsl_people:
        print(f"   {r.record_id} {r.name_raw!r} ids={[(i.scheme.value, i.value) for i in r.identifiers]}")
    # AFSL orgs that look like people: no org word basis default_organisation
    print("\nAFSL default_organisation / partnership (all):")
    for r in R["asic_afsl"]:
        if r.payload["party_type_basis"] in ("default_organisation", "partnership_of_individuals"):
            print(f"   {r.record_id} {r.name_raw!r} basis={r.payload['party_type_basis']} abn_acn_kind={r.payload.get('abn_acn_kind')}")
    print("\nCredit no_person_format / partnership (all):")
    for r in R["asic_credit"]:
        if r.payload["party_type_basis"] in ("no_person_format", "partnership_of_individuals"):
            print(f"   {r.record_id} {r.name_raw!r} basis={r.payload['party_type_basis']}")
    print("\nCredit PERSON with an ACN or a derived ACN (should be none):")
    for r in R["asic_credit"]:
        if r.party_type is PartyType.PERSON and r.identifier(IdScheme.ACN):
            print(f"   {r.record_id} {r.name_raw!r} {r.payload['identifier_provenance']}")
    print("\nCredit ORGANISATION whose name has a comma but basis organisation_word (sample 30):")
    k = 0
    for r in R["asic_credit"]:
        if r.party_type is PartyType.ORGANISATION and "," in r.name_raw and r.payload["party_type_basis"] == "organisation_word":
            if re.fullmatch(r"[A-Z'\- ]+, [A-Z'\- ]+", r.name_raw) and not re.search(r"\b(PTY|LTD|LIMITED|TRUST)\b", r.name_raw):
                print(f"   {r.record_id} {r.name_raw!r}")
                k += 1
                if k >= 30:
                    break
    print("\nLiquidators whose name is not 'LAST, GIVEN' or carries an org word:")
    for r in R["asic_liquidator"]:
        if r.payload["given_names"] is None or tier2._ORG_WORDS.search(r.name_raw):
            print(f"   {r.record_id} {r.name_raw!r}")
    print("\nGLEIF SOLE_PROPRIETOR typed PERSON (sample 25) and typed ORG (all):")
    sp = [r for r in R["gleif_l1"] if r.payload["entity_category"] == "SOLE_PROPRIETOR"]
    for r in [x for x in sp if x.party_type is PartyType.PERSON][:25]:
        print(f"   P {r.record_id} {r.name_raw!r} ids={[i.scheme.value for i in r.identifiers]}")
    for r in [x for x in sp if x.party_type is PartyType.ORGANISATION]:
        print(f"   O {r.record_id} {r.name_raw!r}")
    print("\nGLEIF typed PERSON that carry an ACN (a person cannot hold an ACN):")
    for r in R["gleif_l1"]:
        if r.party_type is PartyType.PERSON and r.identifier(IdScheme.ACN):
            print(f"   {r.record_id} {r.name_raw!r} acn={r.identifier(IdScheme.ACN)}")

    # ------------------------------------------------------------ 7 trustee / derived ACN risk
    hdr("7. ACN derived from ABN on trustee / trust / partnership names")
    for s in ("asic_afsl", "asic_credit"):
        hits = []
        for r in R[s]:
            if r.payload["identifier_provenance"].get("acn") == "derived_from_abn":
                n = r.name_raw.upper()
                if re.search(r"TRUST|\bATF\b|TRUSTEE|PARTNERSHIP|\b&\b|\bAND\b.*\b(PTY|LTD)\b.*\b(PTY|LTD)\b|\bT/AS\b|TRADING AS", n):
                    hits.append(r)
        print(f"{s}: derived ACNs on trust/partnership-shaped names: {len(hits)}")
        for r in hits[:40]:
            print(f"   {r.record_id} {r.name_raw!r} abn={r.identifier(IdScheme.ABN)} acn={r.identifier(IdScheme.ACN)}")

    # ------------------------------------------------------------ 8 cross-source ACN consistency
    hdr("8. Same ACN / ABN under different names across Tier 2 sources")
    acn_names: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    abn_names: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for s in ("asic_afsl", "asic_credit", "asic_banned_org", "gleif_l1"):
        for r in R[s]:
            a = r.identifier(IdScheme.ACN)
            if a:
                prov = (r.payload.get("identifier_provenance") or {}).get("acn", "")
                acn_names[a].append((s, r.record_id, r.name_raw, prov))
            b = r.identifier(IdScheme.ABN)
            if b:
                abn_names[b].append((s, r.record_id, r.name_raw, ""))
    for label, m in (("ACN", acn_names), ("ABN", abn_names)):
        conflicts = []
        multi = 0
        for k, lst in m.items():
            if len(lst) < 2:
                continue
            multi += 1
            names = [x[2] for x in lst]
            worst = min(sim(names[0], n) for n in names[1:])
            if worst < 0.6:
                conflicts.append((worst, k, lst))
        conflicts.sort()
        print(f"{label}: values shared by >1 record={multi}; with dissimilar names (<0.6)={len(conflicts)}")
        for w, k, lst in conflicts[:40]:
            print(f"   {label} {k} sim={w:.2f}: " + " | ".join(f"{s}:{rid}:{n!r}:{p}" for s, rid, n, p in lst[:4]))

    # within-GLEIF: same ACN/ABN on several LEIs
    hdr("8b. GLEIF: one ACN/ABN on several LEIs, by registration status")
    for scheme in (IdScheme.ACN, IdScheme.ABN):
        m = defaultdict(list)
        for r in R["gleif_l1"]:
            v = r.identifier(scheme)
            if v:
                m[v].append(r)
        multi = {k: v for k, v in m.items() if len(v) > 1}
        st = Counter()
        for v in multi.values():
            st[tuple(sorted(x.payload["registration_status"] or "" for x in v))] += 1
        print(f"{scheme.value}: values on >1 LEI={len(multi)}; status combos={st.most_common(8)}")
        for k, v in list(multi.items())[:6]:
            print(f"   {k}: " + " | ".join(f"{x.record_id} {x.name_raw!r} {x.payload['registration_status']}" for x in v))
    st = Counter()
    for r in R["gleif_l1"]:
        if len(r.identifiers) > 1:
            st[r.payload["registration_status"]] += 1
    print("GLEIF records emitting ABN/ACN by registration status:", dict(st))

    # ------------------------------------------------------------ 9 company register cross-check
    if not args.no_register and COMPANY_ZIP.exists():
        hdr("9. Cross-check emitted ACNs against the ASIC company register")
        acns, abns = set(), set()
        for s in ("asic_afsl", "asic_credit", "asic_banned_org", "gleif_l1"):
            for r in R[s]:
                if r.identifier(IdScheme.ACN):
                    acns.add(r.identifier(IdScheme.ACN))
                b = r.identifier(IdScheme.ABN)
                if b:
                    abns.add(b)
                    acns.add(b[2:])
        # GLEIF ARSN / NZ numbers too (to show the danger of trusting them)
        for r in R["gleif_l1"]:
            for k in ("arsn",):
                if r.payload.get(k):
                    acns.add(re.sub(r"\D", "", r.payload[k]).zfill(9))
        names, reg_abn, status, ctype, abn_to_acn = load_register(acns, abns)
        print(f"register rows matched: acns={len(names)} abns={len(abn_to_acn)}")
        for s in ("asic_afsl", "asic_credit", "asic_banned_org", "gleif_l1"):
            buckets = Counter()
            bad = []
            for r in R[s]:
                a = r.identifier(IdScheme.ACN)
                if not a:
                    continue
                prov = (r.payload.get("identifier_provenance") or {}).get("acn", "?")
                if a not in names:
                    buckets[(prov, "not_in_register")] += 1
                    bad.append((0.0, prov, "not_in_register", r, ""))
                    continue
                sc, best = best_sim(r.name_raw, names[a])
                abn = r.identifier(IdScheme.ABN)
                abn_conflict = bool(abn and reg_abn.get(a) and abn not in reg_abn[a])
                if abn_conflict:
                    buckets[(prov, "register_abn_differs")] += 1
                    bad.append((sc, prov, "register_abn_differs", r, f"{best} reg_abn={reg_abn[a]}"))
                if sc >= 0.85:
                    buckets[(prov, "name_ok")] += 1
                elif sc >= 0.6:
                    buckets[(prov, "name_partial")] += 1
                else:
                    buckets[(prov, "name_mismatch")] += 1
                    bad.append((sc, prov, "name_mismatch", r, best))
            print(f"\n{s}: " + ", ".join(f"{k[0]}/{k[1]}={v}" for k, v in sorted(buckets.items())))
            bad.sort(key=lambda x: x[0])
            for sc, prov, why, r, best in bad[:25]:
                print(f"   {why:22s} {prov:32s} sim={sc:.2f} {r.record_id} {r.name_raw!r} acn={r.identifier(IdScheme.ACN)} "
                      f"abn={r.identifier(IdScheme.ABN)} reg={best!r} regstatus={status.get(r.identifier(IdScheme.ACN))}")
        # missed derivations: ABN whose last 9 digits are a registered ACN with that ABN, but no ACN emitted
        hdr("9b. ABNs that the register confirms belong to a company, but no ACN was emitted")
        for s in ("asic_afsl", "asic_credit", "gleif_l1"):
            missed = []
            for r in R[s]:
                b = r.identifier(IdScheme.ABN)
                if b and not r.identifier(IdScheme.ACN) and b[2:] in reg_abn and b in reg_abn[b[2:]]:
                    missed.append(r)
            print(f"{s}: {len(missed)} e.g. {[(r.record_id, r.name_raw) for r in missed[:8]]}")
        # derived ACN where the register says that ACN's ABN is a different number (wrong-entity risk)
        hdr("9c. GLEIF ARSN values: would they collide with a company ACN if trusted?")
        coll = 0
        for r in R["gleif_l1"]:
            v = r.payload.get("arsn")
            if v:
                d = re.sub(r"\D", "", v).zfill(9)
                if d in names:
                    coll += 1
        print("ARSNs that equal a company-register ACN:", coll)
    else:
        print("\n(company register cross-check skipped)")

    # ------------------------------------------------------------ 10 credit AFSL cross-link
    hdr("10. Credit CRED_LIC_AFSL_NUM -> AFSL register: same entity?")
    afsl_by_no = {r.record_id: r for r in R["asic_afsl"]}
    ok = miss = conflict = 0
    ex = []
    for r in R["asic_credit"]:
        a = r.payload.get("afsl_number")
        if not a:
            continue
        t = afsl_by_no.get(a)
        if not t:
            miss += 1
            continue
        ids1 = {(i.scheme, i.value) for i in r.identifiers if i.scheme in (IdScheme.ABN, IdScheme.ACN)}
        ids2 = {(i.scheme, i.value) for i in t.identifiers if i.scheme in (IdScheme.ABN, IdScheme.ACN)}
        if ids1 & ids2 or sim(r.name_raw, t.name_raw) >= 0.85:
            ok += 1
        else:
            conflict += 1
            ex.append((r.record_id, r.name_raw, sorted(ids1), a, t.name_raw, sorted(ids2)))
    print(f"credit rows with AFSL: consistent={ok} afsl_not_in_afsl_file={miss} conflicting={conflict}")
    for e in ex[:15]:
        print("   ", e)
    # AFSL number value equal to ACL number?
    same = sum(1 for r in R["asic_credit"] if r.payload.get("afsl_number") == r.record_id)
    print("credit rows where AFSL number == ACL number:", same)

    # ------------------------------------------------------------ 11 GLEIF L1 RA mapping
    hdr("11. GLEIF L1: RA -> identifier mapping")
    ra_ct = Counter()
    for row, rec in zip(ROWS["gleif_l1"], R["gleif_l1"]):
        raid = row.get("Entity.RegistrationAuthority.RegistrationAuthorityID", "")
        kinds = tuple(sorted(i.scheme.value for i in rec.identifiers if i.scheme is not IdScheme.LEI))
        ra_ct[(raid, kinds)] += 1
    for (raid, kinds), n in sorted(ra_ct.items(), key=lambda x: -x[1])[:30]:
        print(f"   {raid:10s} emits={kinds} n={n}")
    wrong_ra = [r for r in R["gleif_l1"] if len(r.identifiers) > 1
                and r.payload["registration_authority_id"] not in tier2.GleifL1Adapter.AU_RA_SCHEMES]
    print("records emitting ABN/ACN from a non-AU RA:", len(wrong_ra))
    oor = [r for r in R["gleif_l1"] if r.payload["in_scope"] == "referenced_counterparty" and len(r.identifiers) > 1]
    print("out-of-region counterparties emitting ABN/ACN:", len(oor))
    ann = [r for r in R["gleif_l1"] if r.payload["registration_status"] in ("ANNULLED", "DUPLICATE") and len(r.identifiers) > 1]
    print("ANNULLED/DUPLICATE LEIs that still emit ABN/ACN:", len(ann),
          [(r.record_id, r.name_raw, r.payload["registration_status"]) for r in ann[:6]])

    # ------------------------------------------------------------ 12 GLEIF L2
    hdr("12. GLEIF L2 direction, cycles, dangling ends")
    l1 = {r.record_id: r for r in R["gleif_l1"]}
    dangling = sum(1 for r in R["gleif_l2"] if r.payload["child_lei"] not in l1 or r.payload["parent_lei"] not in l1)
    print("edges with an end missing from L1:", dangling)
    indeg, outdeg = Counter(), Counter()
    for r in R["gleif_l2"]:
        if r.payload["relationship_type"] == "IS_ULTIMATELY_CONSOLIDATED_BY":
            indeg[r.payload["parent_lei"]] += 1
            outdeg[r.payload["child_lei"]] += 1
    print("UCB: max children per parent_lei:", [(l1[k].name_raw if k in l1 else k, v) for k, v in indeg.most_common(5)])
    print("UCB: max parents per child_lei (should be 1):", outdeg.most_common(3))
    for k, v in indeg.most_common(2):
        kids = [r.payload["child_lei"] for r in R["gleif_l2"]
                if r.payload["parent_lei"] == k and r.payload["relationship_type"] == "IS_ULTIMATELY_CONSOLIDATED_BY"][:5]
        print(f"   parent {l1.get(k).name_raw if k in l1 else k}: kids {[l1[c].name_raw if c in l1 else c for c in kids]}")
    for t in ("IS_DIRECTLY_CONSOLIDATED_BY", "IS_ULTIMATELY_CONSOLIDATED_BY"):
        c = Counter(r.payload["child_lei"] for r in R["gleif_l2"] if r.payload["relationship_type"] == t)
        print(f"{t}: children with >1 parent: {sum(1 for v in c.values() if v > 1)}")
    # cycles over parent edges
    adj = defaultdict(set)
    for r in R["gleif_l2"]:
        if r.payload["is_parent_relationship"]:
            adj[r.payload["child_lei"]].add(r.payload["parent_lei"])
    cycles = []
    color = {}

    def dfs(u, stack):
        color[u] = 1
        stack.append(u)
        for v in adj.get(u, ()):
            if color.get(v) == 1:
                cycles.append(stack[stack.index(v):] + [v])
            elif not color.get(v):
                dfs(v, stack)
        stack.pop()
        color[u] = 2

    sys.setrecursionlimit(100000)
    for u in list(adj):
        if not color.get(u):
            dfs(u, [])
    print("cycles over parent edges:", len(cycles), cycles[:3])
    rel_types = Counter(r.payload["relationship_type"] for r in R["gleif_l2"])
    print("types:", dict(rel_types))
    fund_parent = sum(1 for r in R["gleif_l2"] if r.payload["relationship_type"] == "IS_FUND-MANAGED_BY")
    print(f"IS_FUND-MANAGED_BY edges stored with manager as 'parent_lei': {fund_parent}")
    st = Counter(r.payload["relationship_status"] for r in R["gleif_l2"])
    rs = Counter(r.payload["registration_status"] for r in R["gleif_l2"])
    print("relationship_status:", dict(st), "registration_status:", dict(rs))
    selfrows = [row for row in ROWS["gleif_l2"] if row.get("Relationship.StartNode.NodeID") == row.get("Relationship.EndNode.NodeID")]
    print("self rows by type:", Counter(r.get("Relationship.RelationshipType") for r in selfrows))
    pct = Counter()
    for r in R["gleif_l2"]:
        for q in r.payload["quantifiers"]:
            pct[(q["method"], q["units"])] += 1
    print("quantifiers:", dict(pct))

    # ------------------------------------------------------------ 13 banned
    hdr("13. Banned orgs")
    for r in R["asic_banned_org"]:
        p = r.payload
        print(f"   {r.record_id:60s} type={r.party_type.value} start={p['ban_start']} end={p['ban_end']} "
              f"perm={p['permanent']} url={'y' if p['document_url'] else 'n'} name={r.name_raw!r} norm={r.name_norm!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
