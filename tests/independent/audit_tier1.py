"""Independent audit of the Tier 1 adapters (ABR bulk extract, ASIC company register)
against the REAL raw files.

Run:  .venv/Scripts/python tests/independent/audit_tier1.py [--abr-n 300000] [--asic-full] [--full-abr-scan]

Written by an independent tester from Requirement.md, ARCHITECTURE.md 2.1, the ABR
XSD (data/raw/abr/bulkextract.xsd) and the raw data. Ground truth is computed here
with independent code (lxml for ABR, duckdb read_csv for ASIC); the adapters are only
the system under test. Checksums are re-implemented here.

Sections
  A. ABR: stream the first N <ABR> records of two members (Public01, Public15) and
     compare adapter output record by record with an independent parse.
  B. ABR ASICNumber -> ASIC cross-check: 2,000 ABN->ACN pairs looked up in the ASIC TSV.
  C. ASIC: duckdb profile of the full TSV (adjacency, Y rows, ABN field, dates) and,
     with --asic-full, the adapter over the full file compared per ACN.
  D. Hash / record_id stability.
  E. Name normalisation on 5,000 real Tier 1 names.

Read-only on data/raw. Writes only to a temp dir (ASIC TSV extracted for duckdb).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
import time
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from lxml import etree

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from bizgraph.domain.models import IdScheme, PartyType  # noqa: E402
from bizgraph.sources.adapters import tier1  # noqa: E402
from bizgraph.sources.base import RejectRecord  # noqa: E402

RAW = REPO / "data" / "raw"
ABR_ZIPS = [RAW / "abr" / "public_split_1_10.zip", RAW / "abr" / "public_split_11_20.zip"]
ABR_MEMBERS = [(ABR_ZIPS[0], "20261111_Public01.xml"), (ABR_ZIPS[1], "20261111_Public15.xml")]
ASIC_ZIP = RAW / "asic_company" / "company_202611.zip"
SNAP = date(2026, 11, 16)


# ----------------------------------------------------------------- independent checksums
def abn_ok(v: str | None) -> bool:
    if not v or len(v) != 11 or not v.isdigit() or v[0] == "0":
        return False
    d = [int(c) for c in v]
    d[0] -= 1
    return sum(x * w for x, w in zip(d, (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19))) % 89 == 0


def acn_ok(v: str | None) -> bool:
    if not v or len(v) != 9 or not v.isdigit():
        return False
    s = sum(int(c) * w for c, w in zip(v[:8], range(8, 0, -1)))
    return (10 - s % 10) % 10 == int(v[8])


def hdr(t: str) -> None:
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


# ----------------------------------------------------------------- limited XML stream
class LimitedAbrStream:
    """File-like over one zip member that stops after N <ABR> records and closes </Transfer>.

    The ABR extract writes one <ABR> per line, so this cuts on line boundaries.
    """

    def __init__(self, zpath: Path, member: str, n: int) -> None:
        self._zf = zipfile.ZipFile(zpath)
        self._fh = self._zf.open(member)
        self._n = n
        self._seen = 0
        self._buf = b""
        self._done = False

    def read(self, size: int = -1) -> bytes:
        while not self._done and (size < 0 or len(self._buf) < size):
            line = self._fh.readline()
            if not line:
                self._done = True
                break
            if b"<ABR " in line:
                self._seen += 1
                if self._seen > self._n:
                    self._buf += b"</Transfer>"
                    self._done = True
                    break
            self._buf += line
        if size < 0:
            out, self._buf = self._buf, b""
        else:
            out, self._buf = self._buf[:size], self._buf[size:]
        return out

    def close(self) -> None:
        self._fh.close()
        self._zf.close()


def gt_abr(zpath: Path, member: str, n: int) -> list[dict]:
    """Independent parse of the first n ABR records. Keeps every field the XSD defines."""
    out = []
    unknown_tags: Counter = Counter()
    known = {"ABN", "EntityType", "MainEntity", "LegalEntity", "ASICNumber", "GST", "DGR", "OtherEntity"}
    stream = LimitedAbrStream(zpath, member, n)
    for _, el in etree.iterparse(stream, events=("end",), tag="ABR", huge_tree=True):
        r: dict = {"_attrs": dict(el.attrib)}
        for ch in el:
            if ch.tag not in known:
                unknown_tags[ch.tag] += 1
        a = el.find("ABN")
        r["abn_text"] = a.text
        r["abn"] = (a.text or "").strip()
        r["status"] = a.get("status")
        r["status_from"] = a.get("ABNStatusFromDate")
        r["etype"] = el.findtext("EntityType/EntityTypeInd")
        r["etext"] = el.findtext("EntityType/EntityTypeText")
        me, le = el.find("MainEntity"), el.find("LegalEntity")
        r["holder"] = "Main" if me is not None else ("Legal" if le is not None else None)
        h = me if me is not None else le
        if me is not None:
            nin = me.find("NonIndividualName")
            r["mn_type"] = nin.get("type") if nin is not None else None
            r["org_name"] = me.findtext("NonIndividualName/NonIndividualNameText")
        if le is not None:
            ind = le.find("IndividualName")
            r["ind_type"] = ind.get("type")
            r["title"] = ind.findtext("NameTitle")
            r["given"] = [g.text for g in ind.findall("GivenName")]
            r["family"] = ind.findtext("FamilyName")
        r["state"] = h.findtext("BusinessAddress/AddressDetails/State") if h is not None else None
        r["postcode"] = h.findtext("BusinessAddress/AddressDetails/Postcode") if h is not None else None
        asic = el.find("ASICNumber")
        r["asic"] = asic.text if asic is not None else None
        r["asic_present"] = asic is not None
        r["asic_type"] = asic.get("ASICNumberType") if asic is not None else None
        g = el.find("GST")
        r["gst"] = (g.get("status"), g.get("GSTStatusFromDate")) if g is not None else None
        r["dgr"] = [
            (d.get("status"), d.get("DGRStatusFromDate"), d.findtext("NonIndividualName/NonIndividualNameText"))
            for d in el.findall("DGR")
        ]
        r["other"] = [
            (o.get("type"), o.findtext("NonIndividualNameText")) for o in el.findall("OtherEntity/NonIndividualName")
        ]
        out.append(r)
        el.clear()
        while el.getprevious() is not None:
            del el.getparent()[0]
    stream.close()
    if unknown_tags:
        print("  UNKNOWN child tags under <ABR>:", dict(unknown_tags))
    return out


def adapter_abr(zpath: Path, member: str, n: int, **kw) -> tuple[list, Counter, int]:
    """Run the real AbrAdapter.parse/to_record/accept on the first n records of one member."""
    orig = tier1._iter_members

    def fake(path, suffixes):
        s = LimitedAbrStream(zpath, member, n)
        yield f"{zpath.name}!{member}", s
        s.close()

    tier1._iter_members = fake
    try:
        ad = tier1.AbrAdapter(**kw)
        recs, rej, n_in = [], Counter(), 0
        for row in ad.parse(Path("ignored")):
            n_in += 1
            try:
                rec = ad.to_record(row, SNAP)
            except RejectRecord as e:
                rej[str(e)] += 1
                recs.append(None)
                continue
            recs.append((rec, ad.accept(rec)))
        return recs, rej, n_in
    finally:
        tier1._iter_members = orig


def section_abr(n: int) -> list[tuple[str, str, str]]:
    hdr(f"A. ABR: first {n:,} records of {', '.join(m for _, m in ABR_MEMBERS)}")
    pairs: list[tuple] = []  # (abn, acn, name, etype, status) for section B
    for zpath, member in ABR_MEMBERS:
        t = time.time()
        gt = gt_abr(zpath, member, n)
        recs, rej, n_in = adapter_abr(zpath, member, n, states="*", statuses="*")
        print(f"\n--- {member}: raw={len(gt):,} adapter records_in={n_in:,} "
              f"rejected={sum(rej.values()):,} {dict(rej)}  ({time.time() - t:.0f}s)")
        if n_in != len(gt):
            print("  FAIL records_in != raw count")
        c: Counter = Counter()
        etype_holder: Counter = Counter()
        etype_counts: Counter = Counter()
        asic_kinds: Counter = Counter()
        asic_by_etype: Counter = Counter()
        mismatches: defaultdict = defaultdict(list)
        acn_owner: defaultdict = defaultdict(list)
        for g, rr in zip(gt, recs):
            etype_holder[(g["etype"], g["holder"])] += 1
            etype_counts[(g["etype"], g["etext"])] += 1
            c[f"replaced={g['_attrs'].get('replaced')} status={g['status']}"] += 1
            c[f"status_from_sentinel={g['status_from'] == '19000101'}"] += 1
            if g["holder"] == "Legal":
                c[f"IND given_count={len(g['given'])}"] += 1
                c[f"IND title_present={g['title'] is not None}"] += 1
                if any(x is None or not x.strip() for x in g["given"]):
                    c["IND blank GivenName element"] += 1
                if not (g["family"] or "").strip():
                    c["IND blank FamilyName"] += 1
            c[f"state={g['state']!r}"] += 1
            if g["postcode"] and not (g["postcode"].isdigit() and len(g["postcode"]) == 4):
                c["postcode_non_4digit"] += 1
            if g["abn_text"] != g["abn"]:
                c["abn_text_has_whitespace"] += 1
            for t_, _ in g["other"]:
                c[f"other_type={t_}"] += 1
            # ASIC number classification (raw)
            a = g["asic"]
            if not g["asic_present"]:
                k = "absent"
            elif a is None or not a.strip():
                k = "empty"
            else:
                digits = "".join(ch for ch in a if ch.isdigit())
                if digits != a.strip():
                    k = "non-digit chars"
                elif len(digits) != 9:
                    k = f"len{len(digits)}"
                elif set(digits) == {"0"}:
                    k = "all zeros (checksum-valid!)"
                elif not acn_ok(digits):
                    k = "9 digits, bad checksum"
                elif g["abn"][2:] == digits:
                    k = "valid, = ABN[2:]"
                else:
                    k = "valid, != ABN[2:]"
            asic_kinds[(k, g["asic_type"])] += 1
            asic_by_etype[(g["etype"], k)] += 1

            if rr is None:
                mismatches["rejected"].append(g["abn"])
                continue
            rec, _acc = rr
            # ---- expectations
            exp_person = g["holder"] == "Legal"
            if (rec.party_type is PartyType.PERSON) != exp_person:
                mismatches["party_type"].append((g["abn"], g["etype"], g["holder"], rec.party_type))
            if rec.record_id != g["abn"]:
                mismatches["record_id"].append((g["abn"], rec.record_id))
            if rec.identifier(IdScheme.ABN) != g["abn"]:
                mismatches["abn_identifier"].append(g["abn"])
            got_acn = rec.identifier(IdScheme.ACN)
            digits = (g["asic"] or "").strip()
            exp_acn = digits if acn_ok(digits) and set(digits) != {"0"} else None
            if got_acn != exp_acn:
                mismatches["acn_identifier"].append((g["abn"], g["asic"], got_acn, g["etype"]))
            if got_acn:
                acn_owner[got_acn].append(g["abn"])
            if exp_person:
                exp_name = " ".join(x.strip() for x in [*g["given"], g["family"] or ""] if x and x.strip())
            else:
                exp_name = (g.get("org_name") or "").strip()
            if (rec.name_raw or "") != exp_name:
                mismatches["name_raw"].append((g["abn"], exp_name, rec.name_raw))
            p = rec.payload
            if p.get("state") != (g["state"] or None):
                mismatches["state"].append((g["abn"], g["state"], p.get("state")))
            if p.get("abn_status") != g["status"]:
                mismatches["abn_status"].append(g["abn"])
            sf = g["status_from"]
            exp_sf = None if sf == "19000101" else f"{sf[:4]}-{sf[4:6]}-{sf[6:]}"
            if p.get("abn_status_from") != exp_sf:
                mismatches["abn_status_from"].append((g["abn"], sf, p.get("abn_status_from")))
            got_other = [(o["type"], o["name"]) for o in p.get("other_names", [])]
            exp_other = [(t_, (nm or "").strip()) for t_, nm in g["other"] if nm and nm.strip()]
            if got_other != exp_other:
                mismatches["other_names"].append((g["abn"], exp_other, got_other))
            if p.get("replaced") != g["_attrs"].get("replaced"):
                mismatches["replaced"].append(g["abn"])
            if got_acn:
                pairs.append((g["abn"], got_acn, exp_name, g["etype"], g["status"]))

        print("  EntityTypeInd x holder:")
        for (et, ho), v in sorted(etype_holder.items(), key=lambda x: -x[1]):
            flag = "  <-- unexpected" if (et == "IND") != (ho == "Legal") else ""
            print(f"    {et} {ho}: {v:,}{flag}")
        print("  Entity type codes seen:", ", ".join(f"{k[0]}({v})" for k, v in etype_counts.most_common()))
        print("  Raw field profile:")
        for k, v in sorted(c.items()):
            print(f"    {k}: {v:,}")
        print("  ASICNumber kinds (kind, ASICNumberType):")
        for k, v in asic_kinds.most_common():
            print(f"    {k}: {v:,}")
        print("  ASICNumber valid-but-!=ABN[2:] / all-zero by entity type:")
        for (et, k), v in sorted(asic_by_etype.items(), key=lambda x: -x[1]):
            if k.startswith(("valid, !=", "all zeros", "9 digits")) or (k.startswith("valid") and et not in ("PRV", "PUB")):
                print(f"    {et} {k}: {v:,}")
        dup = {a: abns for a, abns in acn_owner.items() if len(abns) > 1}
        print(f"  ACN emitted on >1 ABN within this sample: {len(dup):,}  e.g. {list(dup.items())[:5]}")
        print("  Adapter vs independent parse, mismatches per field:")
        if not mismatches:
            print("    none")
        for k, v in mismatches.items():
            print(f"    {k}: {len(v):,}  e.g. {v[:4]}")
        # slice semantics
        acc = Counter((rr[0].payload.get("abn_status"), rr[0].payload.get("state"), rr[1]) for rr in recs if rr)
        print("  accept() with states='*', statuses='*' -> all True:", all(rr[1] for rr in recs if rr))
        del acc
    return pairs


def slice_semantics() -> None:
    hdr("A2. ABR slice filter semantics (env vars and *)")
    zpath, member = ABR_MEMBERS[0]
    old = {k: os.environ.get(k) for k in ("BIZGRAPH_ABR_STATES", "BIZGRAPH_ABR_STATUSES")}
    try:
        for states, statuses in [(None, None), ("*", "ACT"), ("wa, tas", "act"), ("ALL", "*"), ("", "")]:
            for k in old:
                os.environ.pop(k, None)
            if states is not None:
                os.environ["BIZGRAPH_ABR_STATES"] = states
                os.environ["BIZGRAPH_ABR_STATUSES"] = statuses
            recs, _rej, _n = adapter_abr(zpath, member, 20000)
            kept = Counter((r[0].payload["state"], r[0].payload["abn_status"]) for r in recs if r and r[1])
            print(f"  env states={states!r} statuses={statuses!r}: kept {sum(kept.values()):,}/20,000 "
                  f"by (state,status) {dict(kept.most_common(6))}")
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ----------------------------------------------------------------- ASIC ground truth
def asic_tsv() -> Path:
    d = Path(tempfile.gettempdir()) / "bizgraph_audit_tier1"
    d.mkdir(exist_ok=True)
    with zipfile.ZipFile(ASIC_ZIP) as zf:
        name = [n for n in zf.namelist() if n.lower().endswith(".csv")][0]
        out = d / Path(name).name
        if not out.exists() or out.stat().st_size != zf.getinfo(name).file_size:
            zf.extract(name, d)
    return out


def asic_con():
    import duckdb

    p = asic_tsv().as_posix()
    con = duckdb.connect()
    con.execute(
        f"""create table a as select row_number() over () rn, * from read_csv('{p}', delim='\t', header=true,
        all_varchar=true, quote='"', escape='"', strict_mode=false)"""
    )
    con.execute("""create table y as select * from a where "Current Name Indicator"='Y'""")
    return con


def section_crosscheck(con, pairs: list[tuple]) -> None:
    hdr("B. ABR emitted ACN -> ASIC company register cross-check (2,000 pairs per stratum)")
    rnd = random.Random(1)
    strata = {
        "ABR ACT, company types (PRV/PUB)": [p for p in pairs if p[4] == "ACT" and p[3] in ("PRV", "PUB")],
        "ABR CAN, company types (PRV/PUB)": [p for p in pairs if p[4] != "ACT" and p[3] in ("PRV", "PUB")],
        "ABR any status, NON-company types": [p for p in pairs if p[3] not in ("PRV", "PUB")],
    }
    for label, pool in strata.items():
        sample = rnd.sample(pool, min(2000, len(pool)))
        print(f"\n  -- {label}: pool {len(pool):,}, sampled {len(sample):,}")
        if not sample:
            continue
        con.execute("create or replace temp table s(abn varchar, acn varchar, name varchar, et varchar, st varchar)")
        con.executemany("insert into s values (?,?,?,?,?)", sample)
        rows = con.execute(
            """select s.abn, s.acn, s.name, s.et, max(y.ABN) asic_abn, max(trim(y."Company Name")) asic_name,
                      (select count(*) from a where a.ACN = s.acn) n_any,
                      (select max(y2.ACN) from y y2 where y2.ABN = s.abn) asic_acn_for_abn,
                      max(y.Type) asic_type
               from s left join y on y.ACN = s.acn group by all"""
        ).fetchall()
        cat: Counter = Counter()
        ex: defaultdict = defaultdict(list)
        for abn, acn, name, et, asic_abn, asic_name, n_any, acn_for_abn, asic_type in rows:
            if n_any == 0:
                k = "ACN not in ASIC register"
            elif asic_name is None:
                k = "ACN only on former-name rows"
            elif asic_abn == abn:
                k = "ASIC lists same ABN"
            elif asic_abn in (None, "", "0"):
                k = "ASIC ABN 0 for this ACN"
            else:
                k = "ASIC lists a DIFFERENT ABN for this ACN"
            if acn_for_abn and acn_for_abn != acn:
                k += " + ASIC maps this ABN to a DIFFERENT ACN"
            k2 = "ABN[2:]==ACN" if abn[2:] == acn else "ABN[2:]!=ACN"
            cat[(k, k2)] += 1
            ex[(k, k2)].append((abn, acn, et, name, asic_abn, asic_name, asic_type))
        for k, v in sorted(cat.items(), key=lambda x: -x[1]):
            print(f"    {k[0]} | {k[1]}: {v:,}  e.g. {ex[k][:3]}")
    print("\n  ASIC register (Y rows): ABN[2:] vs ACN:",
          con.execute("""select case when ABN='0' then 'abn 0' when substr(ABN,3)=ACN then 'ABN[2:]==ACN'
                         else 'ABN[2:]!=ACN' end k, count(*) from y group by 1""").fetchall())


def section_asic_profile(con) -> None:
    hdr("C. ASIC register profile (duckdb, full file)")
    q = lambda s: con.execute(s).fetchall()  # noqa: E731
    total, distinct = q("select count(*), count(distinct ACN) from a")[0]
    runs = q("select count(*) from (select ACN, lag(ACN) over (order by rn) p from a) where p is null or ACN<>p")[0][0]
    print(f"  rows={total:,} distinct ACN={distinct:,} contiguous runs={runs:,} "
          f"-> adjacency {'HOLDS' if runs == distinct else 'BROKEN'}")
    print("  Y rows per ACN:", q("""select ycnt, count(*) from (select ACN, sum(coalesce(("Current Name Indicator"='Y')::int,0)) ycnt
                                  from a group by ACN) group by 1 order by 1"""))
    print("  status of ACNs with no Y row:", q("""select Status, count(distinct ACN) from a where ACN in
        (select ACN from a group by ACN having sum(coalesce(("Current Name Indicator"='Y')::int,0))=0) group by 1"""))
    print("  ABN field on Y rows:", q("""select case when ABN is null then 'blank' when ABN='0' then '0'
        when length(ABN)=11 then 'len11' else 'other' end, count(*) from y group by 1"""))
    print("  Type on Y rows:", q("select Type, count(*) from y group by 1 order by 2 desc"))
    print("  Status on Y rows:", q("select Status, count(*) from y group by 1 order by 2 desc"))
    print("  padded names (Y rows):", q("""select count(*) from y where "Company Name"<>trim("Company Name")""")[0][0])
    print("  blank Date of Registration (Y):", q("""select count(*) from y where "Date of Registration" is null""")[0][0])
    print("  former rows whose ABN/Status/Type differ from Y row:", q(
        """select count(*) from a f join y using(ACN) where f."Current Name Indicator" is null and
           (f.ABN is distinct from y.ABN or f.Status is distinct from y.Status or f.Type is distinct from y.Type)""")[0][0])


def asic_ground_truth(con) -> dict[str, dict]:
    rows = con.execute(
        """with g as (
             select ACN,
               max(case when "Current Name Indicator"='Y' then trim("Company Name") end) ycur,
               max(case when "Current Name Indicator" is null then trim("Current Name") end) fcur,
               list(trim("Company Name") order by rn) filter (where "Current Name Indicator" is null) former,
               max(case when "Current Name Indicator"='Y' then ABN end) yabn, min(ABN) anyabn,
               max(case when "Current Name Indicator"='Y' then Status end) ystatus, min(Status) anystatus,
               max(case when "Current Name Indicator"='Y' then "Date of Registration" end) yreg,
               min("Date of Registration") anyreg,
               max(case when "Current Name Indicator"='Y' then "Date of Deregistration" end) ydereg
             from a group by ACN)
           select * from g"""
    ).fetchall()
    gt = {}
    for acn, ycur, fcur, former, yabn, anyabn, ystatus, anystatus, yreg, anyreg, ydereg in rows:
        gt[acn] = {
            "name": ycur or fcur,
            "former": [f for f in (former or []) if f],
            "abn": yabn if ycur is not None else anyabn,
            "status": ystatus if ycur is not None else anystatus,
            "reg": yreg if ycur is not None else anyreg,
            "dereg": ydereg,
        }
    return gt


def ddmmyyyy_iso(s: str | None) -> str | None:
    if not s or not s.strip():
        return None
    d, m, y = s.strip().split("/")
    return f"{y}-{m}-{d}"


def section_asic_adapter(con, full: bool) -> None:
    hdr(f"C2. ASIC adapter vs duckdb ground truth ({'FULL file' if full else 'first 300k raw rows'})")
    gt = asic_ground_truth(con)
    ad = tier1.AsicCompanyAdapter(statuses="*")
    t = time.time()
    n_in, rej, mism = 0, Counter(), defaultdict(list)
    seen = set()
    limit_rows = None if full else 300_000
    src = ASIC_ZIP
    if limit_rows:
        # deterministic sample: first 300k raw lines of the TSV as a plain file
        d = Path(tempfile.gettempdir()) / "bizgraph_audit_tier1"
        p = asic_tsv()
        src = d / "asic_head.csv"
        with p.open("rb") as fi, src.open("wb") as fo:
            for i, line in enumerate(fi):
                if i > limit_rows:
                    break
                fo.write(line)
    rows_iter = list(ad.parse(src)) if limit_rows else ad.parse(src)
    if limit_rows:
        rows_iter = rows_iter[:-1]  # last group may be cut by the head truncation
    for row in rows_iter:
        n_in += 1
        try:
            rec = ad.to_record(row, SNAP)
        except RejectRecord as e:
            rej[str(e)] += 1
            continue
        acn = rec.record_id
        if acn in seen:
            mism["duplicate record_id"].append(acn)
        seen.add(acn)
        g = gt.get(acn)
        if g is None:
            mism["acn not in gt"].append(acn)
            continue
        p = rec.payload
        if rec.name_raw != g["name"]:
            mism["name"].append((acn, g["name"], rec.name_raw))
        exp_abn = g["abn"] if g["abn"] and g["abn"] != "0" and abn_ok(g["abn"]) else None
        if rec.identifier(IdScheme.ABN) != exp_abn:
            mism["abn"].append((acn, g["abn"], rec.identifier(IdScheme.ABN)))
        if g["abn"] and g["abn"] != "0" and not abn_ok(g["abn"]):
            mism["raw ABN fails checksum (info)"].append((acn, g["abn"]))
        if p.get("status") != g["status"]:
            mism["status"].append((acn, g["status"], p.get("status")))
        if p.get("date_of_registration") != ddmmyyyy_iso(g["reg"]):
            mism["date_of_registration"].append((acn, g["reg"], p.get("date_of_registration")))
        if g["dereg"] is not None and p.get("date_of_deregistration") != ddmmyyyy_iso(g["dereg"]):
            mism["date_of_deregistration"].append((acn, g["dereg"], p.get("date_of_deregistration")))
        exp_former = []
        for f in g["former"]:
            if f.upper() != (g["name"] or "").upper() and f.upper() not in {x.upper() for x in exp_former}:
                exp_former.append(f)
        if p.get("former_names") != exp_former:
            mism["former_names"].append((acn, exp_former, p.get("former_names")))
        if rec.party_type is not PartyType.ORGANISATION:
            mism["party_type"].append(acn)
        if p.get("type") in ("FNOS", "RACN") and rec.identifier(IdScheme.ACN):
            mism["ARBN-holder (FNOS/RACN) emitted as scheme ACN (judgement)"].append((acn, p.get("type"), rec.name_raw))
    n_raw_acn = len(gt) if full else len(seen) + sum(rej.values())
    print(f"  adapter records_in={n_in:,} rejected={dict(rej)} distinct ACN in gt (full file)={len(gt):,} "
          f"({time.time() - t:.0f}s)")
    if full and n_in != len(gt):
        print("  FAIL records_in != distinct ACN in raw")
    del n_raw_acn
    for k, v in mism.items():
        print(f"  {k}: {len(v):,}  e.g. {v[:4]}")
    if not mism:
        print("  no mismatches")


# ----------------------------------------------------------------- stability
def section_stability() -> None:
    hdr("D. content_hash / record_id stability")
    zpath, member = ABR_MEMBERS[1]
    r1, _, _ = adapter_abr(zpath, member, 5000, states="*", statuses="*")
    r2, _, _ = adapter_abr(zpath, member, 5000, states="*", statuses="*")
    h1 = {r[0].record_id: r[0].content_hash for r in r1 if r}
    h2 = {r[0].record_id: r[0].content_hash for r in r2 if r}
    print(f"  ABR two runs: {len(h1):,} records, identical hashes: {h1 == h2}")
    leaks = [k for r in r1 if r for k in r[0].payload if k.startswith("_")]
    print(f"  ABR payload keys starting with '_' (file name leakage): {sorted(set(leaks))}")
    file_dep = any("public" in json.dumps(r[0].payload).lower() for r in r1[:200] if r)
    print(f"  ABR payload mentions source file name: {file_dep}")


# ----------------------------------------------------------------- names
def section_names(con) -> None:
    hdr("E. Name normalisation on 5,000 real Tier 1 names")
    from bizgraph.normalise.names import NameNormaliser

    nn = NameNormaliser()
    names = [r[0] for r in con.execute(
        """select trim("Company Name") from y using sample reservoir(4000 rows) repeatable (7)""").fetchall()]
    zpath, member = ABR_MEMBERS[1]
    recs, _, _ = adapter_abr(zpath, member, 60000, states="*", statuses="*")
    abr_names = [r[0].name_raw for r in recs if r and r[0].party_type is PartyType.ORGANISATION]
    rnd = random.Random(3)
    names += rnd.sample(abr_names, 1000)
    # targeted extra: trustee and legal form edge cases from real ABR names
    trustee = [n for n in abr_names if "TRUSTEE" in n.upper()][:300]
    findings: defaultdict = defaultdict(list)
    for nm in names + trustee:
        r = nn.normalise(nm)
        if r is None or not r.norm:
            findings["empty norm"].append((nm, r.trustee_of if r else None))
            continue
        if r.norm in {"PTY", "LTD", "THE", "TRUSTEE", "TRUST"}:
            findings["norm is a generic word"].append((nm, r.norm))
        if any(ord(c) > 127 for c in r.norm):
            findings["non-ascii in norm"].append((nm, r.norm))
        if nm.upper().startswith("THE TRUSTEE FOR") and not r.trustee_of:
            findings["'THE TRUSTEE FOR' not split"].append((nm, r.norm))
        if nm.upper().startswith("THE TRUSTEE FOR") and r.trustee_of:
            findings["'THE TRUSTEE FOR X' -> norm (trust name moved to trustee_of)"].append((nm, r.norm, r.trustee_of))
        if r.legal_form == "CO" and not nm.upper().rstrip(". ").endswith(("CO", "COMPANY")):
            findings["CO stripped oddly"].append((nm, r.norm))
        if r.legal_form is None and any(nm.upper().rstrip(" .").endswith(x) for x in ("PTY. LTD", "PTY LTD", "LIMITED")):
            findings["legal form not stripped"].append((nm, r.norm))
        if r.legal_form and r.norm.endswith((" PTY", " LTD", " LIMITED", " PROPRIETARY")):
            findings["legal form residue"].append((nm, r.norm, r.legal_form))
        if "(" in nm and r.norm.count(" ") > 0 and "IN LIQUIDATION" in nm.upper():
            findings["status words kept in norm"].append((nm, r.norm))
        if unicodedata.normalize("NFKC", nm) != nm:
            findings["raw not NFKC"].append(nm)
        if nm.upper().endswith(("PTY. LTD.", "PTY. LIMITED")) and r.legal_form != "PTY LTD":
            findings["'PTY. LTD.' variant not canonicalised"].append((nm, r.norm, r.legal_form))
    norm_freq = Counter(r[0].name_norm for r in recs if r and r[0].party_type is PartyType.ORGANISATION)
    n_org = sum(norm_freq.values())
    print(f"  ABR org records in first 60k of {member}: {n_org:,}; most frequent name_norm (collapse risk):")
    for k, v in norm_freq.most_common(8):
        print(f"    {k!r}: {v:,} ({v / n_org:.1%})")
    print(f"  sampled {len(names) + len(trustee):,} names")
    for k, v in sorted(findings.items(), key=lambda x: -len(x[1])):
        print(f"  {k}: {len(v)}  e.g. {v[:4]}")
    # same entity, two spellings, must collide
    pairs = [("ABC PTY. LTD.", "ABC PTY LTD"), ("ABC PROPRIETARY LIMITED", "ABC PTY LTD"),
             ("THE ABC COMPANY PTY LTD", "ABC CO PTY LTD"), ("A & B PTY LTD", "A AND B PTY LTD"),
             ("SMITH & CO PTY LTD", "SMITH PTY LTD")]
    for a, b in pairs:
        print(f"  {a!r} vs {b!r}: {nn.normalise(a).norm!r} / {nn.normalise(b).norm!r}")


# ----------------------------------------------------------------- F. full-population scan (all 20 members)
def section_full_scan(con) -> None:
    """Regex scan of all ~20.66M ABR records (about 5 min): IND/LegalEntity consistency,
    replaced flag, ASICNumber kinds, and every ACN that is not ABN[2:] or sits on a non-company
    type, joined to the ASIC register."""
    import re

    hdr("F. ABR full-population scan (all 20 members) + ASIC join")
    rx_head = re.compile(rb'replaced="(\w)"><ABN status="(\w+)" ABNStatusFromDate="\d+">(\d+)</ABN><EntityType><EntityTypeInd>(\w+)<')
    rx_name = re.compile(rb"<NonIndividualNameText>([^<]*)<")
    rx_state = re.compile(rb"<State>([^<]*)</State>")
    rx_asic = re.compile(rb'<ASICNumber ASICNumberType="[^"]*"(?: />|>([^<]*)</ASICNumber>)')
    c: Counter = Counter()
    rows = []
    for z in ABR_ZIPS:
        with zipfile.ZipFile(z) as zf:
            for name in sorted(zf.namelist()):
                for line in zf.open(name):
                    if b"<ABR " not in line:
                        continue
                    m = rx_head.search(line)
                    rep, st, abn, et = (x.decode() for x in m.groups())
                    legal = b"<LegalEntity>" in line
                    c["records"] += 1
                    c[f"replaced={rep}"] += 1
                    c[f"IND={et == 'IND'} LegalEntity={legal}"] += 1
                    a = rx_asic.search(line)
                    if not a:
                        continue
                    v = (a.group(1) or b"").decode().strip()
                    if legal:
                        c["IND with ASICNumber"] += 1
                    if v and set(v) == {"0"}:
                        c["ASICNumber all zeros"] += 1
                        print("  all-zero ASICNumber:", abn, et, st)
                    if acn_ok(v) and (v != abn[2:] or et not in ("PRV", "PUB")) and not legal:
                        nm = rx_name.search(line)
                        stt = rx_state.search(line)
                        rows.append((abn, v, et, nm.group(1).decode("utf-8", "replace") if nm else None, st,
                                     stt.group(1).decode() if stt else None))
    for k, v in sorted(c.items()):
        print(f"  {k}: {v:,}")
    con.execute("create or replace temp table r(abn varchar, acn varchar, et varchar, name varchar, st varchar, state varchar)")
    con.executemany("insert into r values (?,?,?,?,?,?)", rows)
    res = con.execute("""select case when r.et in ('PRV','PUB') then 'company' else 'non-company' end g,
          r.acn = substr(r.abn,3) acn_is_abn_tail,
          case when y.ACN is null then 'ACN not in ASIC' when y.ABN=r.abn then 'ASIC same ABN'
               when y.ABN='0' then 'ASIC ABN 0' else 'ASIC DIFFERENT ABN' end k,
          count(*) n, count(*) filter (where st='ACT') n_act,
          count(*) filter (where st='ACT' and state in ('WA','TAS')) n_slice
        from r left join y on y.ACN=r.acn group by all order by 1,2,3""").fetchall()
    print("  (group, ACN==ABN[2:], ASIC verdict, n, n ACT, n ACT in WA/TAS):")
    for row in res:
        print("   ", row)
    print("  ASIC DIFFERENT ABN examples:")
    for row in con.execute("""select r.abn, r.acn, r.et, r.name, r.st, r.state, y.ABN, trim(y."Company Name")
                              from r join y on y.ACN=r.acn where y.ABN<>'0' and y.ABN<>r.abn limit 20""").fetchall():
        print("   ", row)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--abr-n", type=int, default=300_000)
    ap.add_argument("--asic-full", action="store_true")
    ap.add_argument("--skip-abr", action="store_true")
    ap.add_argument("--full-abr-scan", action="store_true", help="section F, ~5 min")
    args = ap.parse_args()
    t = time.time()
    con = asic_con()
    pairs = [] if args.skip_abr else section_abr(args.abr_n)
    if not args.skip_abr:
        slice_semantics()
        section_crosscheck(con, pairs)
    section_asic_profile(con)
    section_asic_adapter(con, args.asic_full)
    section_stability()
    section_names(con)
    if args.full_abr_scan:
        section_full_scan(con)
    print(f"\nTotal {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
