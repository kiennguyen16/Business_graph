"""Stratified, seeded sample of matcher decisions for blind labelling.

Strata are (source, decision, outcome, band): decision is link or abstain, outcome is the match type or
the abstain reason, band is a score band for name-path links (>=0.97, 0.95-0.97, 0.90-0.95, <0.90), a
distance-below-threshold band for abstentions (near0.05, near0.10, far, none) and `id` for exact links.
A plan names how many records to draw per (source, decision, outcome); inside a group the draw is spread
over bands (at least one per band, near-threshold abstention bands weighted x3) and, inside a band, taken
in a fixed order: sha256(seed | source | record_id). The same store, plan and seed always give the same
sample, and adding records to the store only adds rows that sort after the drawn ones in their stratum.

Two files are written:
* `labels/sample_<version>.csv` (blind): the reference record, a candidate list and register facts.
  No score, decision, match type, stratum or best-candidate column. The candidate list is the union of
  identifier lookups, exact-name lookups, the matcher's blocked candidates and the decided targets,
  ordered by an independent name similarity (rapidfuzz token_set_ratio), so the decided target is
  present but not marked.
* `labels/sample_<version>_decisions.csv`: sample_id, version, stratum, decision, target, score, reason
  for every matcher version in the store. Join it only after labelling.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

TIER3_SOURCES = frozenset({"accc_notice", "tga_artg", "annual_reports"})

# Columns the labeller sees. Anything about the matcher's decision is deliberately absent.
BLIND_COLUMNS = [
    "sample_id", "source", "record_id", "tier",
    "ref_name", "ref_party_type", "ref_abn", "ref_acn", "ref_lei", "ref_licence_no", "ref_state",
    "ref_facts", "candidates", "register_facts",
]
DECISION_COLUMNS = [
    "sample_id", "source", "record_id", "version", "role", "stratum", "decision", "outcome",
    "target", "score", "threshold",
]


def tier_of(source: str) -> int:
    return 3 if source in TIER3_SOURCES else 2


def sample_id_for(source: str, record_id: str) -> str:
    """Stable, version-independent id: the same record gets the same id in every sample."""
    return "S" + hashlib.sha256(f"{source}|{record_id}".encode()).hexdigest()[:10]


def order_key(seed: int, source: str, record_id: str) -> str:
    return hashlib.sha256(f"{seed}|{source}|{record_id}".encode()).hexdigest()


@dataclass(frozen=True)
class Quota:
    source: str
    decision: str  # link | abstain | *
    outcome: str  # match type / reason, `NAME_*` prefix pattern, or *
    n: int | None  # None = take all
    role: str = "primary"
    segment: str = "*"  # e.g. 'foreign' (GLEIF legal jurisdiction outside AU)

    def matches(self, row: pd.Series) -> bool:
        if self.source != "*" and row["source"] != self.source:
            return False
        if self.segment != "*" and row.get("segment", "") != self.segment:
            return False
        if self.decision != "*" and row["decision"] != self.decision:
            return False
        if self.outcome == "*":
            return True
        if self.outcome.endswith("*"):
            return str(row["outcome"]).startswith(self.outcome[:-1])
        return row["outcome"] == self.outcome


# Default plan. `primary` quotas run against the version being evaluated; `name_only` quotas against
# an identifier-stripped run of the same code (if one is given), which is where the AFSL and credit
# name path is exercised on records whose stated ABN is independent ground truth.
DEFAULT_PLAN: tuple[Quota, ...] = (
    Quota("accc_notice", "*", "*", None),
    Quota("asic_banned_org", "*", "*", None),
    Quota("gleif_l1", "link", "NAME_FUZZY", 8),
    Quota("gleif_l1", "link", "NAME_NORMALISED_EXACT", 12),
    Quota("gleif_l1", "link", "NAME_SEMANTIC", 4),
    Quota("gleif_l1", "link", "WIKIDATA_ALIAS", 4),
    Quota("gleif_l1", "link", "EXACT_ACN", 12),
    Quota("gleif_l1", "link", "EXACT_ABN", 10),
    Quota("gleif_l1", "link", "EXACT_LEI", 4),
    Quota("asic_afsl", "link", "EXACT_ABN", 5),
    Quota("asic_afsl", "link", "EXACT_ACN", 5),
    Quota("asic_afsl", "link", "EXACT_LICENCE_NO", 3),
    Quota("asic_credit", "link", "EXACT_ABN", 4),
    Quota("asic_credit", "link", "EXACT_ACN", 4),
    Quota("asic_credit", "link", "EXACT_LICENCE_NO", 3),
    Quota("asic_afsl", "link", "NAME_*", 5),
    Quota("asic_credit", "link", "NAME_*", 5),
    Quota("gleif_l1", "abstain", "BELOW_THRESHOLD", 15),
    Quota("gleif_l1", "abstain", "AMBIGUOUS", 8),
    Quota("gleif_l1", "abstain", "NO_CANDIDATE", 3),
    Quota("gleif_l1", "abstain", "PARTY_TYPE_CONFLICT", 3),
    Quota("gleif_l1", "abstain", "IDENTIFIER_CONFLICT", 5),
    Quota("gleif_l1", "abstain", "QUARANTINED_TARGET", 3),
    Quota("asic_afsl", "abstain", "*", 4),
    Quota("asic_credit", "abstain", "*", 4),
    Quota("asic_liquidator", "abstain", "*", 3),
    Quota("asic_liquidator", "link", "*", 5),
    Quota("asic_afsl", "link", "NAME_FUZZY", 5, role="name_only"),
    Quota("asic_afsl", "link", "NAME_NORMALISED_EXACT", 5, role="name_only"),
    Quota("asic_credit", "link", "NAME_FUZZY", 5, role="name_only"),
    Quota("asic_credit", "link", "NAME_NORMALISED_EXACT", 5, role="name_only"),
    Quota("asic_afsl", "abstain", "AMBIGUOUS", 3, role="name_only"),
    Quota("asic_credit", "abstain", "AMBIGUOUS", 3, role="name_only"),
    Quota("asic_afsl", "abstain", "BELOW_THRESHOLD", 3, role="name_only"),
    Quota("asic_credit", "abstain", "BELOW_THRESHOLD", 3, role="name_only"),
    # Census added after a population query showed 75 of 253 v2 GLEIF name links come from LEIs whose
    # legal jurisdiction is not AU. Appended last so the draws above are unchanged.
    Quota("gleif_l1", "link", "NAME_*", None, segment="foreign"),
)

# Top-up for a later version, run with --exclude-labelled so it only adds records: every name-path link,
# the new abstain reasons, the sole-trader ABN links and ended licences.
TOPUP_PLAN: tuple[Quota, ...] = (
    Quota("gleif_l1", "link", "NAME_*", None),
    Quota("gleif_l1", "abstain", "JURISDICTION_MISMATCH", 20),
    Quota("gleif_l1", "link", "EXACT_ABN", 20, segment="au-person-abn"),
    Quota("asic_afsl", "link", "EXACT_*", 10, segment="ended"),
    Quota("asic_credit", "link", "EXACT_*", 10, segment="ended"),
    Quota("asic_afsl", "abstain", "*", 5, segment="ended"),
    Quota("asic_credit", "abstain", "*", 5, segment="ended"),
    Quota("asic_afsl", "abstain", "PARTY_TYPE_CONFLICT", 5),
    Quota("gleif_l1", "abstain", "AMBIGUOUS", None),
    Quota("gleif_l1", "abstain", "BELOW_THRESHOLD", 8, segment="au"),
    Quota("asic_afsl", "link", "NAME_*", 5),
    Quota("asic_credit", "link", "NAME_*", 5),
)
PLANS = {"default": DEFAULT_PLAN, "topup": TOPUP_PLAN}


# --------------------------------------------------------------------------------------------------
# Population


def policy_for(con: duckdb.DuckDBPyConnection, version: str) -> dict[str, Any]:
    row = con.execute("SELECT policy FROM matcher_version WHERE version = ?", [version]).fetchall()
    if not row:
        raise KeyError(f"unknown matcher version {version}")
    return json.loads(row[0][0]) if row[0][0] else {}


def threshold_for(policy: dict[str, Any], source: str) -> float:
    p = policy.get("policy", policy)
    return float(p.get("per_source", {}).get(source, p.get("default", 0.9)))


def path_of(match_type: str | None) -> str:
    if match_type is None:
        return "abstain"
    return "exact" if str(match_type).startswith("EXACT_") else "name"


def band_of(decision: str, outcome: str, score: float | None, threshold: float) -> str:
    if decision == "link":
        if path_of(outcome) == "exact":
            return "id"
        s = float(score or 0.0)
        if s >= 0.97:
            return "ge0.97"
        if s >= 0.95:
            return "0.95-0.97"
        if s >= 0.90:
            return "0.90-0.95"
        return "lt0.90"
    if score is None or pd.isna(score):
        return "none"
    gap = threshold - float(score)
    if gap <= 0.05:
        return "near0.05"
    if gap <= 0.10:
        return "near0.10"
    return "far"


SEGMENT_SQL = """
    CASE WHEN d.source = 'gleif_l1' THEN
             CASE WHEN coalesce(r.payload->>'legal_jurisdiction', 'AU') NOT LIKE 'AU%' THEN 'foreign'
                  WHEN r.person_abn THEN 'au-person-abn'
                  ELSE 'au' END
         WHEN d.source IN ('asic_afsl', 'asic_credit') THEN
             CASE WHEN r.last_seen < r.source_last THEN 'ended' ELSE 'current' END
         ELSE '' END
"""


# A party key is minted from its strongest identifier (urn:abn, else urn:acn, ...), so a canonical rebuild
# that gives a party an ABN re-mints its key. Decisions stored before such a rebuild then point at keys
# that no longer exist. They are mapped to the current party through the identifier table and flagged.
STALE_KEY_SQL = """
    SELECT k.canonical_key AS old_key, any_value(i.canonical_key) AS new_key
    FROM (SELECT DISTINCT {col} AS canonical_key FROM {rel}) k
    LEFT JOIN party_canonical p ON p.canonical_key = k.canonical_key
    JOIN identifier i ON i.scheme = split_part(k.canonical_key, ':', 2)
                     AND i.value = split_part(k.canonical_key, ':', 3)
    WHERE p.canonical_key IS NULL AND k.canonical_key LIKE 'urn:%'
    GROUP BY k.canonical_key
"""


def resolve_stale_targets(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["stale_target"] = None
    if df.empty:
        return df
    con.register("st_dec", df[["target"]].dropna())
    mapping = dict(con.execute(STALE_KEY_SQL.format(col="target", rel="st_dec")).fetchall())
    con.unregister("st_dec")
    if mapping:
        hit = df["target"].isin(list(mapping))
        df.loc[hit, "stale_target"] = df.loc[hit, "target"]
        df.loc[hit, "target"] = df.loc[hit, "target"].map(mapping)
    return df


def decisions_for(con: duckdb.DuckDBPyConnection, version: str) -> pd.DataFrame:
    """Every decision of one matcher version, with its stratum.

    The stratum carries a segment that is a property of the reference record, not of the decision:
    for GLEIF, 'foreign' (legal jurisdiction not AU), 'au-person-abn' (the stated ABN belongs to a person
    party, i.e. a sole trader) or 'au'; for AFSL and credit, 'ended' (the licence is absent from the
    latest capture) or 'current'.
    """
    df = con.execute(
        f"""
        WITH d AS (
            SELECT source, record_id, 'link' AS decision, match_type AS outcome, canonical_key AS target,
                   confidence AS score
            FROM link WHERE matcher_version = ?
            UNION ALL
            SELECT source, record_id, 'abstain', reason, best_candidate, best_score
            FROM abstention WHERE matcher_version = ?
        ), r0 AS (
            SELECT source, record_id, payload, abn, last_seen_snapshot AS last_seen,
                   max(last_seen_snapshot) OVER (PARTITION BY source) AS source_last
            FROM source_record
            WHERE source IN ('gleif_l1', 'asic_afsl', 'asic_credit')
            QUALIFY row_number() OVER (PARTITION BY source, record_id
                                       ORDER BY last_seen_snapshot DESC, snapshot_date DESC) = 1
        ), r AS (
            SELECT r0.*, EXISTS (SELECT 1 FROM identifier i JOIN party_canonical p USING (canonical_key)
                                 WHERE i.scheme = 'abn' AND i.value = r0.abn AND p.party_type = 'person')
                         AS person_abn
            FROM r0
        )
        SELECT d.*, {SEGMENT_SQL} AS segment
        FROM d LEFT JOIN r ON r.source = d.source AND r.record_id = d.record_id
        """,
        [version, version],
    ).df()
    df = resolve_stale_targets(con, df)
    policy = policy_for(con, version)
    df["version"] = version
    df["threshold"] = [threshold_for(policy, s) for s in df["source"]]
    df["band"] = [
        band_of(d, o, s, t) for d, o, s, t in zip(df["decision"], df["outcome"], df["score"], df["threshold"])
    ]
    df["stratum"] = (df["source"] + "|" + df["decision"] + "|" + df["outcome"].astype(str) + "|" + df["band"]
                     + "|" + df["segment"].fillna(""))
    df["path"] = [path_of(o) if d == "link" else "abstain" for d, o in zip(df["decision"], df["outcome"])]
    return df


def _allocate(band_sizes: dict[str, int], n: int) -> dict[str, int]:
    """At least one per band (near-threshold first), the rest by weighted largest remainder."""
    def weight(b: str) -> float:
        return 3.0 if b.startswith("near") else 1.0

    bands = sorted(band_sizes, key=lambda b: (not b.startswith("near"), b))
    alloc = {b: 0 for b in bands}
    left = n
    for b in bands:
        if left and band_sizes[b]:
            alloc[b] = 1
            left -= 1
    while left > 0:
        room = {b: band_sizes[b] - alloc[b] for b in bands if band_sizes[b] > alloc[b]}
        if not room:
            break
        total_w = sum(band_sizes[b] * weight(b) for b in room)
        best = max(room, key=lambda b: (band_sizes[b] * weight(b) / total_w) * n - alloc[b])
        alloc[best] += 1
        left -= 1
    return alloc


def draw(population: pd.DataFrame, plan: Iterable[Quota], seed: int, role: str) -> pd.DataFrame:
    """Apply the quotas of one role to a version's decisions. Deterministic for a given seed."""
    pop = population.copy()
    pop["_order"] = [order_key(seed, s, r) for s, r in zip(pop["source"], pop["record_id"])]
    taken: list[pd.DataFrame] = []
    used: set[tuple[str, str]] = set()
    for q in plan:
        if q.role != role:
            continue
        mask = pop.apply(q.matches, axis=1) if len(pop) else pd.Series([], dtype=bool)
        group = pop[mask & ~pop.set_index(["source", "record_id"]).index.isin(list(used))]
        if group.empty:
            continue
        if q.n is None or q.n >= len(group):
            pick = group
        else:
            sizes = group.groupby("band").size().to_dict()
            alloc = _allocate(sizes, q.n)
            parts = [
                group[group["band"] == b].sort_values("_order").head(k) for b, k in alloc.items() if k
            ]
            pick = pd.concat(parts)
        seg = "" if q.segment == "*" else f"|{q.segment}"
        pick = pick.assign(quota=f"{q.source}|{q.decision}|{q.outcome}{seg}|n={q.n}", role=role)
        used |= set(zip(pick["source"], pick["record_id"]))
        taken.append(pick)
    if not taken:
        return pop.head(0).assign(quota="", role=role)
    return pd.concat(taken).drop(columns="_order").sort_values(["source", "record_id"]).reset_index(drop=True)


def stratified_sample(
    con: duckdb.DuckDBPyConnection,
    version: str,
    name_only_version: str | None = None,
    seed: int = 20261118,
    plan: Sequence[Quota] = DEFAULT_PLAN,
    exclude: set[tuple[str, str]] | None = None,
) -> pd.DataFrame:
    """One row per drawn (source, record_id) with the stratum it was drawn from."""
    frames = []
    pop = decisions_for(con, version)
    if exclude:
        pop = pop[~pop.set_index(["source", "record_id"]).index.isin(list(exclude))]
    frames.append(draw(pop, plan, seed, "primary"))
    if name_only_version:
        pop2 = decisions_for(con, name_only_version)
        if exclude:
            pop2 = pop2[~pop2.set_index(["source", "record_id"]).index.isin(list(exclude))]
        got = set(zip(frames[0]["source"], frames[0]["record_id"]))
        pop2 = pop2[~pop2.set_index(["source", "record_id"]).index.isin(list(got))]
        frames.append(draw(pop2, plan, seed, "name_only"))
    out = pd.concat(frames, ignore_index=True)
    out["sample_id"] = [sample_id_for(s, r) for s, r in zip(out["source"], out["record_id"])]
    out["tier"] = [tier_of(s) for s in out["source"]]
    return out


# --------------------------------------------------------------------------------------------------
# Evidence for the labeller


def _j(v: Any) -> Any:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return json.loads(v) if isinstance(v, str) else v


def _ref_facts(source: str, payload: dict[str, Any]) -> str:
    p = payload or {}
    keep: dict[str, Any] = {}
    if source == "gleif_l1":
        la = p.get("legal_address") or {}
        hq = p.get("headquarters_address") or {}
        keep = {
            "legal_name": p.get("legal_name"),
            "other_names": [o.get("name") + f" ({o.get('type')})" for o in p.get("other_names") or []],
            "legal_form_code": p.get("legal_form_code"),
            "legal_form_other": p.get("legal_form_other"),
            "jurisdiction": p.get("legal_jurisdiction"),
            "entity_category": p.get("entity_category"),
            "entity_status": p.get("entity_status"),
            "lei_status": p.get("lei_status"),
            "registration_authority": p.get("registration_authority_id"),
            "registration_number": p.get("registration_authority_entity_id"),
            "legal_address": ", ".join(str(x) for x in [la.get("firstaddressline"), la.get("city"),
                                                        la.get("region"), la.get("postalcode"),
                                                        la.get("country")] if x),
            "hq_address": ", ".join(str(x) for x in [hq.get("city"), hq.get("region"), hq.get("country")] if x),
            "created": p.get("entity_creation_date"),
            "withheld/unverified": {k: p[k] for k in ("trustee_acn", "trust_registration_number",
                                                      "unverified_acn", "withheld_registration_number",
                                                      "unverified_arbn", "oric_icn") if p.get(k)},
        }
    elif source in ("asic_afsl", "asic_credit"):
        keep = {k: p.get(k) for k in ("name", "abn_acn_kind", "abn_acn_raw", "identifier_provenance",
                                      "locality", "state", "postcode", "country", "status",
                                      "licence_start", "licence_end", "business_names", "afsl_number",
                                      "family_name", "given_names", "unverified_acn", "unverified_arbn")
                if p.get(k) not in (None, [], {})}
    elif source == "asic_banned_org":
        keep = {k: p.get(k) for k in ("name", "acn_raw", "ban_type", "ban_start", "ban_end", "permanent",
                                      "comment")}
    elif source == "accc_notice":
        keep = {k: p.get(k) for k in ("recipient_as_stated", "title", "trading_as", "identifiers_stated",
                                      "reference_kind", "reference_number", "section", "date_paid", "parties")}
    elif source == "asic_liquidator":
        keep = {k: p.get(k) for k in ("name", "firm", "locality", "state", "status", "liquidator_number")}
    else:
        keep = {k: v for k, v in p.items() if isinstance(v, (str, int, float)) and len(str(v)) < 120}
    return json.dumps({k: v for k, v in keep.items() if v not in (None, [], {}, "")}, ensure_ascii=False)


def _sim(a: str | None, b: str | None) -> float:
    from rapidfuzz import fuzz

    if not a or not b:
        return 0.0
    return float(fuzz.token_set_ratio(a, b))


def gather_evidence(con: duckdb.DuckDBPyConnection, sample: pd.DataFrame, max_blocked: int = 10,
                    versions: Sequence[str] | None = None) -> pd.DataFrame:
    """Blind rows: reference, candidates and register facts, nothing about the decision."""
    keys = sample[["sample_id", "source", "record_id"]].drop_duplicates()
    con.register("ev_keys", keys)
    refs = con.execute(
        """
        SELECT k.sample_id, r.source, r.record_id, r.name_raw, r.name_norm, r.party_type, r.abn, r.acn, r.lei,
               r.licence_no, r.state, r.identifiers, r.payload
        FROM ev_keys k
        JOIN (SELECT * FROM source_record
              QUALIFY row_number() OVER (PARTITION BY source, record_id ORDER BY snapshot_date DESC) = 1) r
          ON r.source = k.source AND r.record_id = k.record_id
        """
    ).df()

    # Candidate keys from four independent routes.
    cand = con.execute(
        """
        WITH ids AS (
            SELECT k.sample_id, unnest(from_json(r.identifiers, '["VARCHAR[]"]')) AS pair
            FROM ev_keys k JOIN source_record r ON r.source = k.source AND r.record_id = k.record_id
        )
        SELECT ids.sample_id, i.canonical_key, 'stated_' || i.scheme AS via
        FROM ids JOIN identifier i ON i.scheme = ids.pair[1] AND i.value = ids.pair[2]
        UNION ALL
        SELECT k.sample_id, p.canonical_key, 'exact_name'
        FROM ev_keys k JOIN source_record r ON r.source = k.source AND r.record_id = k.record_id
        JOIN party_canonical p ON p.name_norm = r.name_norm
        UNION ALL
        SELECT k.sample_id, a.canonical_key, 'exact_alias:' || a.alias_type
        FROM ev_keys k JOIN source_record r ON r.source = k.source AND r.record_id = k.record_id
        JOIN alias a ON a.alias_norm = r.name_norm
        """
    ).df()
    vlist = list(versions) if versions else [v for (v,) in con.execute("SELECT version FROM matcher_version").fetchall()]
    con.register("ev_versions", pd.DataFrame({"v": vlist}))
    blocked = con.execute(
        """
        SELECT DISTINCT k.sample_id, c.canonical_key, 'blocking' AS via
        FROM ev_keys k JOIN candidate c ON c.source = k.source AND c.record_id = k.record_id
        WHERE c.run_id IN (SELECT v FROM ev_versions)
        UNION
        SELECT k.sample_id, l.canonical_key, 'blocking' FROM ev_keys k
        JOIN link l ON l.source = k.source AND l.record_id = k.record_id
        WHERE l.matcher_version IN (SELECT v FROM ev_versions)
        UNION
        SELECT k.sample_id, a.best_candidate, 'blocking' FROM ev_keys k
        JOIN abstention a ON a.source = k.source AND a.record_id = k.record_id
        WHERE a.matcher_version IN (SELECT v FROM ev_versions) AND a.best_candidate IS NOT NULL
        """
    ).df()
    allc = pd.concat([cand, blocked], ignore_index=True)
    con.register("ev_cand", allc[["canonical_key"]].drop_duplicates())
    parties = con.execute(
        """
        SELECT p.canonical_key, p.party_type, p.name, p.name_norm, p.abn, p.acn, p.entity_type_text,
               p.abn_status, p.asic_status, p.asic_type, p.state, p.postcode, p.slice_reason
        FROM party_canonical p JOIN ev_cand c USING (canonical_key)
        """
    ).df().set_index("canonical_key")
    aliases = con.execute(
        """
        SELECT a.canonical_key, string_agg(a.alias || ' [' || a.alias_type || ']', '; ' ORDER BY a.alias, a.alias_type) AS al
        FROM (SELECT DISTINCT canonical_key, alias, alias_type FROM alias
              WHERE canonical_key IN (SELECT canonical_key FROM ev_cand)) a
        GROUP BY a.canonical_key
        """
    ).df().set_index("canonical_key")["al"].to_dict()

    # Register facts: ASIC company register by stated ACN, by stated ABN and by exact name; ABR by ABN.
    reg_acn = con.execute(
        """
        SELECT k.sample_id, c.record_id AS acn, c.name_raw, c.payload
        FROM ev_keys k JOIN source_record r ON r.source = k.source AND r.record_id = k.record_id
        JOIN source_record c ON c.source = 'asic_company'
             AND (c.record_id = r.acn OR c.abn = r.abn)
        ORDER BY k.sample_id, c.record_id
        """
    ).df()
    reg_name = con.execute(
        """
        SELECT k.sample_id, c.record_id AS acn, c.name_raw, c.payload
        FROM ev_keys k JOIN source_record r ON r.source = k.source AND r.record_id = k.record_id
        JOIN source_record c ON c.source = 'asic_company' AND c.name_norm = r.name_norm
        WHERE r.name_norm IS NOT NULL AND length(r.name_norm) > 0
        ORDER BY k.sample_id, c.record_id
        """
    ).df()
    abr_abn = con.execute(
        """
        SELECT k.sample_id, a.record_id AS abn, a.name_raw, a.state, a.payload
        FROM ev_keys k JOIN source_record r ON r.source = k.source AND r.record_id = k.record_id
        JOIN source_record a ON a.source = 'abr' AND (a.record_id = r.abn OR a.acn = r.acn)
        ORDER BY k.sample_id, a.record_id
        """
    ).df()
    acn_holder = con.execute("SELECT value, canonical_key FROM identifier WHERE scheme = 'acn' AND value IN "
                             "(SELECT acn FROM source_record WHERE source='asic_company' AND (record_id IN "
                             "(SELECT acn FROM ev_keys k JOIN source_record r USING (source, record_id)) OR "
                             "name_norm IN (SELECT name_norm FROM ev_keys k JOIN source_record r "
                             "USING (source, record_id)) OR abn IN (SELECT abn FROM ev_keys k JOIN "
                             "source_record r USING (source, record_id))))").df()
    holder = dict(zip(acn_holder["value"], acn_holder["canonical_key"]))
    for t in ("ev_keys", "ev_cand", "ev_versions"):
        con.unregister(t)

    def company_fact(row: pd.Series, why: str) -> str:
        p = _j(row["payload"]) or {}
        dereg = p.get("date_of_deregistration")
        former = p.get("former_names") or []
        return (f"ASIC company register [{why}] ACN {row['acn']} '{row['name_raw']}' type {p.get('type')} "
                f"class {p.get('class')} status {p.get('status')} registered {p.get('date_of_registration')}"
                + (f" deregistered {dereg}" if dereg else "")
                + (f" ABN {p.get('abn')}" if p.get("abn") else "")
                + (f" former names {former}" if former else "")
                + f" -> in graph as {holder.get(row['acn'], 'NOT IN GRAPH')}")

    out = []
    for _, r in refs.iterrows():
        sid = r["sample_id"]
        payload = _j(r["payload"]) or {}
        rows = allc[allc["sample_id"] == sid]
        via: dict[str, set[str]] = {}
        for k, v in zip(rows["canonical_key"], rows["via"]):
            if k is not None and not pd.isna(k):
                via.setdefault(k, set()).add(v)
        scored = []
        for k, vs in via.items():
            if k not in parties.index:
                continue
            p = parties.loc[k]
            sim = max(_sim(r["name_norm"], p["name_norm"]), 0.0)
            scored.append((k, vs, sim, p))
        firm = [x for x in scored if x[1] - {"blocking"}]
        loose = sorted([x for x in scored if not (x[1] - {"blocking"})], key=lambda x: (-x[2], x[0]))
        loose_keys = {x[0] for x in loose[:max_blocked]}
        # Every key the matcher decided on is in `via` as blocking; keep them so a link target is never
        # hidden, without marking which one it was.
        decided = set(sample.loc[sample["sample_id"] == sid, "target"].dropna())
        chosen = firm + [x for x in loose if x[0] in loose_keys or x[0] in decided]
        chosen = sorted(chosen, key=lambda x: (-x[2], x[0]))
        lines = []
        for k, vs, sim, p in chosen:
            al = aliases.get(k, "")
            if len(al) > 300:
                al = al[:300] + "..."
            lines.append(
                f"{k} | {p['name']} | {p['party_type']} | {p['entity_type_text'] or ''} | ABN {p['abn'] or '-'} "
                f"{p['abn_status'] or ''} | ACN {p['acn'] or '-'} {p['asic_status'] or ''} | {p['state'] or '-'} "
                f"{p['postcode'] or ''} | slice {p['slice_reason']} | via {','.join(sorted(vs))} | sim {sim:.0f}"
                + (f" | aliases: {al}" if al else "")
            )
        facts = []
        for _, c in reg_acn[reg_acn["sample_id"] == sid].iterrows():
            facts.append(company_fact(c, "stated ACN/ABN"))
        for _, c in reg_name[reg_name["sample_id"] == sid].head(15).iterrows():
            facts.append(company_fact(c, "same normalised name"))
        for _, a in abr_abn[abr_abn["sample_id"] == sid].iterrows():
            p = _j(a["payload"]) or {}
            facts.append(f"ABR (loaded slice, by stated ABN or ACN) ABN {a['abn']} '{a['name_raw']}' {p.get('entity_type_text')} "
                         f"status {p.get('abn_status')} state {a['state']} ASIC no {p.get('asic_number')}")
        if isinstance(r["abn"], str) and r["abn"] and abr_abn[abr_abn["sample_id"] == sid].empty:
            facts.append(f"ABR: stated ABN {r['abn']} is not in the loaded ABR slice")
        out.append({
            "sample_id": sid, "source": r["source"], "record_id": r["record_id"], "tier": tier_of(r["source"]),
            "ref_name": r["name_raw"], "ref_party_type": r["party_type"], "ref_abn": r["abn"], "ref_acn": r["acn"],
            "ref_lei": r["lei"], "ref_licence_no": r["licence_no"], "ref_state": r["state"],
            "ref_facts": _ref_facts(r["source"], payload),
            "candidates": "\n".join(lines) if lines else "(no candidate found by any route)",
            "register_facts": "\n".join(dict.fromkeys(facts)) if facts else "(none)",
        })
    blind = pd.DataFrame(out, columns=BLIND_COLUMNS)
    return blind.sort_values("sample_id").reset_index(drop=True)


def decisions_table(con: duckdb.DuckDBPyConnection, sample: pd.DataFrame,
                    versions: Sequence[str] | None = None) -> pd.DataFrame:
    """Decisions of every requested version for the sampled records (the file joined after labelling)."""
    vlist = list(versions) if versions else [v for (v,) in con.execute("SELECT version FROM matcher_version").fetchall()]
    keys = sample[["sample_id", "source", "record_id", "role"]].drop_duplicates(["sample_id"])
    frames = []
    for v in vlist:
        d = decisions_for(con, v).merge(keys, on=["source", "record_id"])
        frames.append(d)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=DECISION_COLUMNS)
    return df[DECISION_COLUMNS].sort_values(["sample_id", "version"]).reset_index(drop=True)


def write_sample(con: duckdb.DuckDBPyConnection, version: str, out_dir: Path,
                 name_only_version: str | None = None, seed: int = 20261118,
                 plan: Sequence[Quota] = DEFAULT_PLAN, exclude: set[tuple[str, str]] | None = None
                 ) -> tuple[Path, Path, pd.DataFrame]:
    out_dir.mkdir(parents=True, exist_ok=True)
    sample = stratified_sample(con, version, name_only_version, seed, plan, exclude)
    versions = [version] + ([name_only_version] if name_only_version else [])
    blind = gather_evidence(con, sample, versions=versions)
    dec = decisions_table(con, sample)
    strata = sample[["sample_id", "role", "quota", "stratum"]]
    dec = dec.merge(strata.rename(columns={"stratum": "drawn_stratum", "role": "drawn_role"}),
                    on="sample_id", how="left")
    blind_path = out_dir / f"sample_{version}.csv"
    dec_path = out_dir / f"sample_{version}_decisions.csv"
    blind.to_csv(blind_path, index=False)
    dec.to_csv(dec_path, index=False)
    return blind_path, dec_path, sample
