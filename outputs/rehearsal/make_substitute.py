"""Build a 200-row stand-in for `dirty_references.jsonl`.

    .venv/Scripts/python outputs/rehearsal/make_substitute.py [--db data/snap_v3_rehearsal.duckdb] [--seed 20261118]

Writes, next to this script:
  dirty_references_substitute.jsonl  {"reference_id", "reference"} x 200 (what the resolver sees)
  answer_key.jsonl                   reference_id -> expected canonical key or NOT_IN_GRAPH, category, provenance

How the truth is set, without looking at any matcher output (no link, candidate or abstention table
is read):
  * Register samples (AFSL, credit, banned orgs, ACCC, GLEIF): the record's own stated ABN, else ACN,
    joined to the `identifier` table; kept only when it names exactly one non-quarantined party.
  * ABR samples (WA / TAS companies, trusts, trading names): the party itself; kept only when its
    normalised name (or alias) belongs to that one party in the name index, so the reference is not
    ambiguous by construction.
  * Big national companies and near-name hard negatives: a hand list of names, each checked to exist
    under the stated ABN.
  * Exactly 12 NOT_IN_GRAPH: real ASIC-registered companies outside the slice, NZ namesakes of AU
    companies, and invented names. Each is checked absent by ABN, ACN and normalised name against
    party_canonical, alias and the resolution name index.

Then each name is corrupted the way a human or an upstream system would: case, legal form dropped /
abbreviated / expanded / "Pty. Ltd.", "&" vs "and", a one-word typo, trustee wording, trading names,
appended address or state text, an embedded ABN / ACN in about 20% of rows (some with a wrong check
digit), acronyms. Seeded and deterministic for a given database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bizgraph.normalise.identifiers import AbnValidator, AcnValidator  # noqa: E402
from bizgraph.normalise.names import NameNormaliser  # noqa: E402

NAMES = NameNormaliser()
ABN_OK = AbnValidator().is_valid
ACN_OK = AcnValidator().is_valid

# Target counts (in graph 188 + absent 12 = 200). The ABR company pool fills any shortfall.
TARGET = {
    "afsl_licensee": 28,
    "credit_licensee": 22,
    "gleif_au": 28,
    "accc_recipient": 8,
    "banned_org": 10,
    "abr_trust": 18,
    "abr_trading_name": 10,
}
N_TOTAL = 200
STATE_NAMES = {"WA": "Western Australia", "TAS": "Tasmania", "NSW": "New South Wales", "VIC": "Victoria",
               "QLD": "Queensland", "SA": "South Australia", "ACT": "ACT", "NT": "Northern Territory"}
CAPITAL = {"WA": "Perth", "TAS": "Hobart", "NSW": "Sydney", "VIC": "Melbourne", "QLD": "Brisbane",
           "SA": "Adelaide", "ACT": "Canberra", "NT": "Darwin"}

# Big national companies: (reference text, expected ABN, corruption note). Text written by hand.
NATIONALS = [
    ("CBA", "48123123124", "acronym"),
    ("Commonwealth Bank of Aust., Sydney NSW", "48123123124", "abbreviation+address"),
    ("comonwealth bank", "48123123124", "typo+lower+drop_form"),
    ("Westpac Banking Corp", "33007457141", "abbreviate_form"),
    ("WESTPAC BANKING CORPORATION ABN 33 007 457 141", "33007457141", "embedded_abn"),
    ("Telstra Corporation Ltd", "33051775556", "abbreviate_form"),
    ("Telstra Group", "56650620303", "drop_form"),
    ("National Australia Bank Ltd (NAB)", "12004044937", "abbreviate_form+acronym"),
    ("ANZ Banking Group Limited", "11005357522", "acronym_inside_name"),
    ("BHP Group Ltd., Melbourne VIC", "49004028077", "abbreviate_form+address"),
    ("woolworths group", "88000014675", "lower+drop_form"),
    ("Wesfarmers Ltd, Perth WA", "28008984049", "abbreviate_form+address"),
    ("Qantas Airways Limited", "16009661901", "case"),
    ("Rio Tinto Ltd", "96004458404", "abbreviate_form"),
]
# Near-names of the nationals that are different entities in the graph.
HARD_NEGATIVES_IN_GRAPH = [
    ("Commonwealth Superannuation Corporation", "48882817243", "brief_test_case"),
    ("Commonwealth Super Corp, Canberra ACT", "48882817243", "abbreviation+address"),
    ("Commonwealth Bank Officers Superannuation Corp Pty Ltd", "76074519798", "abbreviate_form"),
    ("Commonwealth Bank Staff Golf Club (WA)", "14546967869", "state"),
    ("Westpac Banking Corp Tasmanian Staff Social Club", "29538116301", "abbreviation"),
    ("Telstra Energy (Markets) Pty Ltd", "25645100456", "case"),
    ("ANZ Securities Ltd", "16004997111", "abbreviate_form"),
    ("Wesfarmers Transport Limited", "16008670077", "case"),
]
# Not in the graph: NZ namesakes of AU entities, and invented businesses.
NZ_NAMESAKES = ["Westpac New Zealand Limited", "ANZ Bank New Zealand Ltd", "Woolworths New Zealand Limited"]
INVENTED = ["Quenda Creek Hydroponics Pty Ltd", "Bluewren Freight & Logistics Pty Ltd, Hobart TAS",
            "Kestrel Ridge Capital Partners Pty. Ltd."]
N_ASIC_ABSENT = 12 - len(NZ_NAMESAKES) - len(INVENTED)

LEGAL_FORMS = re.compile(
    r"\s*\b(PTY\.?\s*LTD\.?|PTY\.?\s*LIMITED|PROPRIETARY\s+LIMITED|LIMITED|LTD\.?|INCORPORATED|INC\.?)\s*$",
    re.IGNORECASE)


def stable_hash(s: str) -> int:
    return int(hashlib.md5(s.encode()).hexdigest()[:12], 16)


# --------------------------------------------------------------------------- corruption helpers


def change_case(s: str, rng: random.Random) -> tuple[str, str]:
    op = rng.choice(["lower", "upper", "title"])
    return {"lower": s.lower(), "upper": s.upper(), "title": s.title()}[op], op


def legal_form(s: str, rng: random.Random) -> tuple[str, str | None]:
    m = LEGAL_FORMS.search(s)
    if not m:
        return s, None
    stem, form = s[: m.start()], re.sub(r"\s+", " ", m.group(1).upper().replace(".", ""))
    if form in ("PTY LTD", "PTY LIMITED", "PROPRIETARY LIMITED"):
        choices = ["", " Pty. Ltd.", " Pty Ltd", " Proprietary Limited", " P/L", " Pty"]
    elif form in ("LIMITED", "LTD"):
        choices = ["", " Ltd", " Limited", " Ltd."]
    else:
        choices = ["", " Inc"]
    choices = [c for c in choices if c.upper().replace(".", "").strip() != form] or [""]
    new = rng.choice(choices)
    return stem + new, ("drop_form" if not new else f"form:{new.strip()}")


def amp(s: str) -> tuple[str, str | None]:
    if "&" in s:
        return s.replace("&", "and"), "amp_to_and"
    if re.search(r"\bAND\b", s, re.IGNORECASE):
        return re.sub(r"\b[Aa][Nn][Dd]\b", "&", s, count=1), "and_to_amp"
    return s, None


def typo(s: str, rng: random.Random) -> tuple[str, str | None]:
    words = [(m.start(), m.group(0)) for m in re.finditer(r"[A-Za-z]{5,}", s)]
    words = [(i, w) for i, w in words if w.upper() not in ("LIMITED", "PROPRIETARY", "TRUSTEE", "TRUST")]
    if not words:
        return s, None
    i, w = rng.choice(words)
    p = rng.randrange(1, len(w) - 1)
    op = rng.choice(["swap", "drop", "double", "replace"])
    if op == "swap":
        nw = w[:p] + w[p + 1] + w[p] + w[p + 2:]
    elif op == "drop":
        nw = w[:p] + w[p + 1:]
    elif op == "double":
        nw = w[:p] + w[p] + w[p:]
    else:
        nw = w[:p] + rng.choice("aeiourstnl") + w[p + 1:]
    if w.isupper():
        nw = nw.upper()
    elif w.islower():
        nw = nw.lower()
    if nw == w:
        return s, None
    return s[:i] + nw + s[i + len(w):], f"typo:{w}->{nw}"


def trustee(s: str, rng: random.Random) -> tuple[str, str | None]:
    m = re.match(r"^\s*(?:THE\s+)?TRUSTEE\s+FOR\s+(?:THE\s+)?(.+)$", s, re.IGNORECASE)
    if not m:
        return s, None
    core = m.group(1).strip()
    op = rng.choice(["bare", "trustee_for", "atf", "the_x"])
    new = {"bare": core, "trustee_for": f"Trustee for {core}", "atf": f"ATF {core}",
           "the_x": f"The {core}"}[op]
    return new, f"trustee:{op}"


def address(s: str, state: str | None, postcode: str | None, rng: random.Random,
            street: str | None = None) -> tuple[str, str | None]:
    if not state:
        return s, None
    city = CAPITAL.get(state, "")
    opts = [f"{s}, {state}", f"{s} ({state})", f"{s}, {city} {state}" + (f" {postcode}" if postcode else ""),
            f"{s} - {STATE_NAMES.get(state, state)}"]
    if street:
        opts.append(f"{s}, {street}, {city} {state}" + (f" {postcode}" if postcode else ""))
    new = rng.choice(opts)
    return new, "address"


def fmt_abn(v: str, rng: random.Random) -> str:
    style = rng.choice(["spaced", "plain", "colon"])
    spaced = f"{v[:2]} {v[2:5]} {v[5:8]} {v[8:]}"
    return {"spaced": f"ABN {spaced}", "plain": f"ABN {v}", "colon": f"ABN: {spaced}"}[style]


def fmt_acn(v: str, rng: random.Random) -> str:
    spaced = f"{v[:3]} {v[3:6]} {v[6:]}"
    return rng.choice([f"ACN {spaced}", f"(ACN {v})", f"A.C.N. {spaced}".replace("A.C.N.", "ACN")])


def break_checksum(v: str, ok, rng: random.Random) -> str:
    for _ in range(50):
        p = rng.randrange(len(v))
        nv = v[:p] + str((int(v[p]) + rng.randrange(1, 10)) % 10) + v[p + 1:]
        if not ok(nv) and nv[0] != "0":
            return nv
    raise RuntimeError("could not break checksum")


def corrupt(name: str, rng: random.Random, *, state=None, postcode=None, street=None, abn=None, acn=None,
            embed: str | None = None) -> tuple[str, list[str], dict | None]:
    """Apply 1 to 3 realistic corruptions. `embed` is None, 'valid' or 'bad_checksum'."""
    ops: list[str] = []
    s = name.strip()
    s, op = trustee(s, rng) if rng.random() < 0.8 else (s, None)
    ops += [op] if op else []
    pool = ["case", "form", "amp", "typo", "address"]
    weights = [0.35, 0.45, 0.25, 0.3, 0.25]
    picked = [p for p, w in zip(pool, weights) if rng.random() < w]
    if not picked and not ops:
        picked = [rng.choice(["case", "form"])]
    for p in ["form", "amp", "typo", "case", "address"]:  # fixed order: the address goes last
        if p not in picked:
            continue
        if p == "case":
            s, op = change_case(s, rng)
        elif p == "form":
            s, op = legal_form(s, rng)
        elif p == "amp":
            s, op = amp(s)
        elif p == "typo":
            s, op = typo(s, rng)
        else:
            s, op = address(s, state, postcode, rng, street)
        ops += [op] if op else []
    emb = None
    if embed:
        scheme, val = ("abn", abn) if abn and (not acn or rng.random() < 0.7) else ("acn", acn)
        if val:
            ok = ABN_OK if scheme == "abn" else ACN_OK
            shown = val if embed == "valid" else break_checksum(val, ok, rng)
            txt = fmt_abn(shown, rng) if scheme == "abn" else fmt_acn(shown, rng)
            s = rng.choice([f"{s} {txt}", f"{s}, {txt}", f"{txt} {s}"]) if not s.endswith(")") else f"{s} {txt}"
            emb = {"scheme": scheme, "shown": shown, "true": val, "checksum_valid": ok(shown)}
            ops.append(f"embed_{scheme}_{embed}")
    if not ops:
        s, op = change_case(s, rng)
        ops.append(op)
    return re.sub(r"\s+", " ", s).strip(), ops, emb


# --------------------------------------------------------------------------- sampling


class Builder:
    def __init__(self, con: duckdb.DuckDBPyConnection, seed: int) -> None:
        self.con = con
        self.rng = random.Random(seed)
        self.seed = seed
        self.used_keys: set[str] = set()
        con.execute("""CREATE TEMP TABLE name_keys AS
                       SELECT name_norm, count(DISTINCT canonical_key) AS n FROM res_name_index GROUP BY 1""")

    def q(self, sql: str, params=None) -> list[tuple]:
        return self.con.execute(sql, params or []).fetchall()

    def key_for(self, abn: str | None, acn: str | None) -> str | None:
        for scheme, v in (("abn", abn), ("acn", acn)):
            if not v:
                continue
            rows = self.q("""SELECT DISTINCT i.canonical_key FROM identifier i
                             JOIN party_canonical p USING (canonical_key)
                             WHERE i.scheme = ? AND i.value = ? AND NOT coalesce(p.quarantined, false)""",
                          [scheme, v])
            if len(rows) == 1:
                return rows[0][0]
            if len(rows) > 1:
                return None
        return None

    def ptype(self, key: str) -> str | None:
        rows = self.q("SELECT party_type FROM party_canonical WHERE canonical_key = ?", [key])
        return rows[0][0] if rows else None

    def take(self, pool: list[dict], n: int) -> list[dict]:
        pool = sorted(pool, key=lambda r: stable_hash(f"{self.seed}:{r['_sort']}"))
        out = []
        for r in pool:
            if len(out) >= n:
                break
            if r["expected"] in self.used_keys:
                continue
            self.used_keys.add(r["expected"])
            out.append(r)
        return out

    def register(self, source: str, category: str, n: int) -> list[dict]:
        rows = self.q("""SELECT record_id, name_raw, abn, acn, state, payload FROM (
                           SELECT *, row_number() OVER (PARTITION BY record_id ORDER BY snapshot_date DESC,
                                                        load_seq DESC) AS rn
                           FROM source_record WHERE source = ?) WHERE rn = 1 AND name_raw IS NOT NULL
                         ORDER BY record_id""", [source])
        pool, seen_names = [], set()
        for rid, name, abn, acn, state, payload in rows:
            if source == "gleif_l1" and stable_hash(f"g{rid}") % 20:
                continue  # thin the 119k GLEIF records before the identifier lookups
            key = self.key_for(abn, acn)
            if not key or name.upper() in seen_names:
                continue
            seen_names.add(name.upper())
            street, postcode = None, None
            if source == "gleif_l1":
                pl = json.loads(payload) if isinstance(payload, str) else payload
                la = pl.get("legal_address") or {}
                if (la.get("country") or "AU") != "AU":
                    continue
                street = la.get("firstaddressline")
                postcode = la.get("postalcode")
            pool.append({"_sort": rid, "expected": key, "category": category, "source": source, "source_record_id": rid,
                         "name": re.sub(r"\s*\(formerly .*\)$", "", name, flags=re.IGNORECASE), "state": state,
                         "postcode": postcode, "street": street, "abn": abn, "acn": acn})
        return self.take(pool, n)

    def abr(self, category: str, n: int, where: str) -> list[dict]:
        rows = self.q(f"""SELECT p.canonical_key, p.name, p.abn, p.acn, p.state, p.postcode, p.entity_type
                          FROM party_canonical p JOIN res_name_index x
                            ON x.canonical_key = p.canonical_key AND x.kind = 'name'
                          JOIN name_keys k ON k.name_norm = x.name_norm AND k.n = 1
                          WHERE p.slice_reason = 'state_slice' AND p.status = 'ACTIVE'
                            AND NOT coalesce(p.quarantined, false) AND {where}
                            AND md5_number(p.canonical_key) % 500 = 7
                          ORDER BY p.canonical_key""")
        pool = [{"_sort": k, "expected": k, "category": category, "source": "abr", "source_record_id": k,
                 "name": name, "state": st, "postcode": pc, "street": None, "abn": abn, "acn": acn,
                 "entity_type": et} for k, name, abn, acn, st, pc, et in rows]
        return self.take(pool, n)

    def trading_names(self, n: int) -> list[dict]:
        rows = self.q("""SELECT p.canonical_key, x.name_raw, x.kind, p.state, p.postcode, p.abn
                         FROM res_name_index x JOIN name_keys k ON k.name_norm = x.name_norm AND k.n = 1
                         JOIN party_canonical p ON p.canonical_key = x.canonical_key
                         WHERE x.kind IN ('trading_name', 'business_name') AND p.slice_reason = 'state_slice'
                           AND p.status = 'ACTIVE' AND NOT coalesce(p.quarantined, false)
                           AND length(x.name_raw) >= 12 AND md5_number(x.canonical_key) % 300 = 11
                         ORDER BY 1, 2""")
        pool = [{"_sort": f"{k}|{nm}", "expected": k, "category": "abr_trading_name", "source": "abr",
                 "source_record_id": k, "name": nm, "alias_kind": kind, "state": st, "postcode": pc, "street": None,
                 "abn": abn, "acn": None} for k, nm, kind, st, pc, abn in rows]
        return self.take(pool, n)

    def by_abn(self, items, category: str) -> list[dict]:
        out = []
        for text, abn, note in items:
            rows = self.q("SELECT canonical_key, name FROM party_canonical WHERE abn = ?", [abn])
            assert len(rows) == 1, f"{text}: {abn} -> {rows}"
            out.append({"expected": rows[0][0], "category": category, "source": "hand_list",
                        "source_record_id": abn, "name": rows[0][1], "text": text, "ops": [note]})
        return out

    def is_absent(self, name: str, abn: str | None = None, acn: str | None = None) -> bool:
        norm = NAMES.normalise(re.sub(r",.*$", "", name))
        norm = norm.norm if norm else ""
        for scheme, v in (("abn", abn), ("acn", acn)):
            if v and self.q("SELECT 1 FROM identifier WHERE scheme = ? AND value = ?", [scheme, v]):
                return False
            if v and self.q(f"SELECT 1 FROM party_canonical WHERE {scheme} = ?", [v]):
                return False
        if self.q("SELECT 1 FROM res_name_index WHERE name_norm = ?", [norm]):
            return False
        if self.q("SELECT 1 FROM party_canonical WHERE name_norm = ? OR upper(name) = upper(?)", [norm, name]):
            return False
        if self.q("SELECT 1 FROM alias WHERE alias_norm = ? OR upper(alias) = upper(?)", [norm, name]):
            return False
        return True

    def asic_absent(self, n: int) -> list[dict]:
        rows = self.q("""SELECT record_id, name_raw, abn, acn, payload->>'previous_state_of_registration'
                         FROM source_record WHERE source = 'asic_company' AND payload->>'status' = 'REGD'
                           AND payload->>'type' = 'APTY' AND md5_number(record_id) % 4000 = 3
                           AND upper(name_raw) LIKE '% PTY LTD' AND abn IS NOT NULL
                         ORDER BY record_id""")
        pool = []
        for rid, name, abn, acn, prev_state in rows:
            if not self.is_absent(name, abn, acn):
                continue
            if re.match(r"^\d", name) or "TRUST" in name.upper() or "NOMINEES" in name.upper():
                continue  # keep ordinary trading names
            pool.append({"_sort": rid, "expected": "NOT_IN_GRAPH", "category": "absent_out_of_slice",
                         "source": "asic_company", "source_record_id": rid, "name": name,
                         "state": prev_state if prev_state not in ("WA", "TAS") else None, "postcode": None,
                         "street": None, "abn": abn, "acn": acn})
        pool = sorted(pool, key=lambda r: stable_hash(f"{self.seed}:{r['_sort']}"))
        return pool[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "snap_v3_rehearsal.duckdb"))
    ap.add_argument("--seed", type=int, default=20261118)
    ap.add_argument("--out-dir", default=str(HERE))
    args = ap.parse_args()
    con = duckdb.connect(args.db, read_only=True)
    b = Builder(con, args.seed)
    rng = b.rng

    picked: list[dict] = []
    nat = b.by_abn(NATIONALS, "national_company")
    hard = b.by_abn(HARD_NEGATIVES_IN_GRAPH, "hard_negative_in_graph")
    b.used_keys.update(r["expected"] for r in nat + hard)
    picked += b.register("asic_afsl", "afsl_licensee", TARGET["afsl_licensee"])
    picked += b.register("asic_credit", "credit_licensee", TARGET["credit_licensee"])
    picked += b.register("gleif_l1", "gleif_au", TARGET["gleif_au"])
    picked += b.register("accc_notice", "accc_recipient", TARGET["accc_recipient"])
    picked += b.register("asic_banned_org", "banned_org", TARGET["banned_org"])
    trust_types = "('DIT','DTT','FUT','FXT','HYT','TRT','DST','UIT')"
    picked += b.abr("abr_trust", TARGET["abr_trust"],
                    f"p.entity_type IN {trust_types} AND upper(p.name) LIKE 'THE TRUSTEE FOR %'")
    picked += b.trading_names(TARGET["abr_trading_name"])

    absent = []
    for nm in NZ_NAMESAKES:
        assert b.is_absent(nm), nm
        absent.append({"expected": "NOT_IN_GRAPH", "category": "absent_nz_namesake", "source": "hand_list",
                       "source_record_id": None, "name": nm, "text": nm, "ops": ["nz_namesake"]})
    for nm in INVENTED:
        assert b.is_absent(nm), nm
        absent.append({"expected": "NOT_IN_GRAPH", "category": "absent_invented", "source": "hand_list",
                       "source_record_id": None, "name": nm, "text": nm, "ops": ["invented"]})
    asic_abs = b.asic_absent(N_ASIC_ABSENT)
    assert len(asic_abs) == N_ASIC_ABSENT

    n_fill = N_TOTAL - len(picked) - len(nat) - len(hard) - len(absent) - len(asic_abs)
    picked += b.abr("abr_company", n_fill, "p.entity_type = 'PRV'")
    assert len(picked) + len(nat) + len(hard) + len(absent) + len(asic_abs) == N_TOTAL, "pool too small"

    # About 20% of rows carry an identifier; about one in five of those has a broken check digit.
    eligible = [r for r in picked + asic_abs if r.get("abn") or r.get("acn")]
    eligible.sort(key=lambda r: stable_hash(f"{args.seed}:emb:{r['source_record_id']}:{r['name']}"))
    n_embed = 40 - 1  # one hand-written national row already carries an ABN
    embed_mode = {id(r): ("bad_checksum" if i % 5 == 4 else "valid") for i, r in enumerate(eligible[:n_embed])}
    for r in asic_abs[:2]:  # an out-of-slice company stating its real ABN: the identifier is not in the graph
        embed_mode.setdefault(id(r), "valid")

    rows = []
    for r in picked + asic_abs:
        text, ops, emb = corrupt(r["name"], rng, state=r.get("state"), postcode=r.get("postcode"),
                                 street=r.get("street"), abn=r.get("abn"), acn=r.get("acn"),
                                 embed=embed_mode.get(id(r)))
        r.update(text=text, ops=ops, embedded=emb)
        rows.append(r)
    for r in nat + hard + absent:
        r.setdefault("embedded", None)
        rows.append(r)
    for r in rows:
        # Every sampled reference differs from the register text; the hand lists are left as written.
        if r["text"].strip() == r["name"].strip() and r["source"] != "hand_list":
            for form in rng.sample(["lower", "title", "upper"], 3):
                new = {"lower": r["text"].lower(), "title": r["text"].title(), "upper": r["text"].upper()}[form]
                if new != r["text"]:
                    r["text"] = new
                    r["ops"].append(form)
                    break

    rows.sort(key=lambda r: stable_hash(f"{args.seed}:order:{r['category']}:{r['name']}:{r['text']}"))
    out = Path(args.out_dir)
    with (out / "dirty_references_substitute.jsonl").open("w", encoding="utf-8", newline="\n") as fi, \
            (out / "answer_key.jsonl").open("w", encoding="utf-8", newline="\n") as fk:
        for i, r in enumerate(rows, 1):
            rid = f"R{i:03d}"
            fi.write(json.dumps({"reference_id": rid, "reference": r["text"]}, ensure_ascii=False) + "\n")
            fk.write(json.dumps({
                "reference_id": rid, "expected": r["expected"], "category": r["category"],
                "reference": r["text"], "true_name": r["name"], "source": r["source"],
                "source_record_id": r["source_record_id"], "corruptions": r["ops"],
                "party_type": None if r["expected"] == "NOT_IN_GRAPH" else b.ptype(r["expected"]),
                "embedded_identifier": r.get("embedded"),
            }, ensure_ascii=False) + "\n")
    from collections import Counter

    print(json.dumps({"rows": len(rows), "by_category": Counter(r["category"] for r in rows),
                      "not_in_graph": sum(r["expected"] == "NOT_IN_GRAPH" for r in rows),
                      "with_identifier": sum(1 for r in rows if re.search(r"\b(ABN|ACN)\b", r["text"])),
                      "bad_checksum": sum(1 for r in rows if r.get("embedded") and not r["embedded"]["checksum_valid"])},
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
