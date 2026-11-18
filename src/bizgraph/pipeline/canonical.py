"""Tier 1 canonical parties: `party_canonical`, `identifier`, `alias` and conflict quarantine.

Built set-based in DuckDB SQL from the latest version of every `abr` and
`asic_company` source record. The build is replace-by-build: every run deletes
and rewrites the derived tables (and its own quarantine invariants) inside one
transaction, ordered by key, so a rerun on the same records yields identical
tables (T2.5 idempotency).

Who becomes a party
-------------------
* every ABR record in the store (the ABR slice: active WA + TAS, plus every ABN
  referenced by a Tier 2 source);
* every ASIC company whose ACN a Tier 2 source references and that no ABR party
  represents;
* the ASIC side of every identity conflict below, flagged ``quarantined``
  and preserved as evidence.

The key registry preserves the earliest key attached to a party's identifiers.
New parties mint a key from the first available identifier in ABN, ACN, LEI order.

ASIC enriches an ABR party (ACN, status, type, class, registration dates as
validity, former names as aliases) only through a *clean* pair:

* basis ``acn``: ABR's ACN for the ABN is the ASIC record's ACN, or
* basis ``asic_abn``: ABR gives no ACN for the ABN and exactly one ASIC record
  gives that ABN;

and the pair breaks none of the invariants (NOTES.md section 4, shapes.ttl):

``ACN_MULTIPLE_ABN``   an ACN appears under two or more ABR ABNs.
``ABN_ACN_DISAGREE``   ABR's ACN for an ABN disagrees with ASIC's ABN for that ACN
                       (either direction).
``ABN_MULTIPLE_ACN``   ABR gives no ACN, and two or more ASIC ACNs claim the ABN.
``NAME_MISMATCH``      identifiers agree but ABR's name and ASIC's current name are
                       clearly different (low similarity, and neither is a former
                       name / registered alias of the other).

On a violation every involved record gets a `quarantine` row (with the party it
belongs to), every involved party is flagged ``quarantined``, the conflicting
value is withheld from the `identifier` table (which therefore only holds values
that belong to exactly one party) and nothing is merged.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import duckdb
import pyarrow as pa

from bizgraph.normalise.identifiers import AbnValidator, AcnValidator
from bizgraph.normalise.names import NameNormaliser
from bizgraph.sources.adapters.tier1 import AbrAdapter
from bizgraph.store.duckdb_store import DuckDBStore

TIER1_SOURCES = ("abr", "asic_company")
INVARIANTS = ("ACN_MULTIPLE_ABN", "ABN_ACN_DISAGREE", "ABN_MULTIPLE_ACN", "NAME_MISMATCH")

ABR_ALIAS_TYPES = {
    "BN": "business_name",
    "TRD": "trading_name",
    "OTN": "other_name",
    "DGR": "dgr_name",
}

_LATEST = "last_seen_snapshot DESC, load_seq DESC NULLS LAST, snapshot_date DESC, content_hash"


def _tier2_sources() -> list[str]:
    import bizgraph.sources.adapters  # noqa: F401  (registers adapters)
    from bizgraph.sources.registry import registry

    return [a.source_id for a in registry.all() if a.tier == 2]


def tier2_reference_ids(
    con: duckdb.DuckDBPyConnection, sources: Iterable[str] | None = None
) -> tuple[set[str], set[str]]:
    """ABNs and ACNs referenced by Tier 2 source records (latest versions).

    ACNs: the `acn` column plus GLEIF's ``trustee_acn`` / ``general_partner_acn``
    payload fields (check-digit validated here). ABNs: the `abn` column plus the
    ASIC register's ABN for every referenced ACN, so an ABR record that does not
    carry its own ACN is still pulled into the slice.
    """
    sources = list(sources) if sources is not None else _tier2_sources()
    if not sources:
        return set(), set()
    marks = ", ".join("?" for _ in sources)
    rows = con.execute(
        f"""WITH latest AS (
                SELECT abn, acn, payload->>'trustee_acn' AS trustee_acn,
                       payload->>'general_partner_acn' AS gp_acn
                FROM source_record WHERE source IN ({marks})
                QUALIFY row_number() OVER (PARTITION BY source, record_id ORDER BY {_LATEST}) = 1)
            SELECT 'abn', abn FROM latest WHERE abn IS NOT NULL
            UNION SELECT 'acn', acn FROM latest WHERE acn IS NOT NULL
            UNION SELECT 'xacn', trustee_acn FROM latest WHERE trustee_acn IS NOT NULL
            UNION SELECT 'xacn', gp_acn FROM latest WHERE gp_acn IS NOT NULL""",
        sources,
    ).fetchall()
    abns = {v for k, v in rows if k == "abn"}
    acns = {v for k, v in rows if k == "acn"}
    acn_v = AcnValidator()
    for k, v in rows:
        if k == "xacn" and (ident := acn_v.parse(v)) is not None:
            acns.add(ident.value)
    if acns:
        tbl = pa.table({"acn": sorted(acns)})
        con.register("_t2_acn_in", tbl)
        try:
            extra = con.execute(
                f"""SELECT DISTINCT s.abn FROM (
                        SELECT record_id, abn FROM source_record WHERE source = 'asic_company'
                        QUALIFY row_number() OVER (PARTITION BY record_id ORDER BY {_LATEST}) = 1) s
                    JOIN _t2_acn_in t ON t.acn = s.record_id WHERE s.abn IS NOT NULL"""
            ).fetchall()
        finally:
            con.unregister("_t2_acn_in")
        abns.update(r[0] for r in extra)
    abn_v = AbnValidator()
    abns = {a for a in abns if abn_v.parse(a) is not None}
    return abns, acns


@dataclass
class BuildStats:
    parties: int = 0
    by_party_type: dict[str, int] = field(default_factory=dict)
    by_slice_reason: dict[str, int] = field(default_factory=dict)
    by_origin: dict[str, int] = field(default_factory=dict)
    identifiers: dict[str, int] = field(default_factory=dict)
    aliases: dict[str, int] = field(default_factory=dict)
    quarantine: dict[str, int] = field(default_factory=dict)
    quarantined_parties: int = 0
    asic_enriched: int = 0
    wall_clock_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class CanonicalBuilder:
    """Builds the canonical party tables from Tier 1 source records. See module docstring."""

    # Names are "clearly different" only when every one of these fails.
    JW_MIN = 0.85  # Jaro-Winkler on normalised names
    TOKEN_OVERLAP_MIN = 0.5  # |A n B| / min(|A|, |B|) on normalised name tokens

    def __init__(
        self,
        store: DuckDBStore,
        states: Iterable[str] | str | None = None,
        statuses: Iterable[str] | str | None = None,
        tier2_sources: Iterable[str] | None = None,
        normaliser: NameNormaliser | None = None,
    ) -> None:
        self.store = store
        self.con = store.con
        # Same slice definition (and env defaults) as the ABR adapter.
        slice_def = AbrAdapter(states=states, statuses=statuses)
        self.states = slice_def.states
        self.statuses = slice_def.statuses
        self.tier2_sources = list(tier2_sources) if tier2_sources is not None else None
        self.names = normaliser or NameNormaliser()

    # ------------------------------------------------------------------ helpers

    def _x(self, sql: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        return self.con.execute(sql, params or []).fetchall()

    def _register_set(self, name: str, column: str, values: Iterable[str]) -> None:
        self.con.register(name, pa.table({column: pa.array(sorted(values), pa.string())}))

    def _state_slice_sql(self) -> str:
        conds = []
        if self.statuses is not None:
            conds.append("upper(coalesce(abn_status, '')) IN (" + ", ".join(f"'{s}'" for s in sorted(self.statuses)) + ")")
        if self.states is not None:
            conds.append("upper(coalesce(state, '')) IN (" + ", ".join(f"'{s}'" for s in sorted(self.states)) + ")")
        return " AND ".join(conds) if conds else "true"

    # ------------------------------------------------------------------ build

    def build(self) -> BuildStats:
        started = time.perf_counter()
        con = self.con
        t2_abn, t2_acn = tier2_reference_ids(con, self.tier2_sources)
        self._register_set("_t2_abn", "abn", t2_abn)
        self._register_set("_t2_acn", "acn", t2_acn)
        try:
            self._stage_inputs()
            self._stage_names()
            self._stage_pairs_and_conflicts()
            con.execute("BEGIN TRANSACTION")
            try:
                self._stage_parties()
                self._write()
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        finally:
            for v in ("_t2_abn", "_t2_acn"):
                con.unregister(v)
            for t in ("_abr", "_asic", "_names", "_abr_alias", "_asic_alias", "_pair", "_conflict",
                      "_idclean", "_named", "_mismatch", "_clean", "_party", "_qrow", "_party_ids", "_party_keys"):
                con.execute(f"DROP TABLE IF EXISTS {t}")
        stats = self.stats()
        stats.wall_clock_s = time.perf_counter() - started
        return stats

    def _stage_inputs(self) -> None:
        con = self.con
        con.execute(
            f"""CREATE OR REPLACE TEMP TABLE _abr AS
                SELECT record_id AS abn,
                       -- A trust, partnership, fund or individual cannot own an ACN: the number on
                       -- such an ABR record is the trustee's / general partner's, so it is not
                       -- used to pair or assign (it stays in the source record).
                       CASE WHEN payload->>'entity_type_code' IN ('IND', 'PTR', 'LPT')
                                 OR regexp_matches(coalesce(payload->>'entity_type_text', ''),
                                                   '(?i)trust|partnership|fund|individual')
                            THEN NULL ELSE acn END AS acn,
                       name_raw, name_norm,
                       coalesce(party_type, 'organisation') AS party_type,
                       payload->>'abn_status' AS abn_status,
                       TRY_CAST(payload->>'abn_status_from' AS DATE) AS abn_status_from,
                       payload->>'entity_type_code' AS entity_type,
                       payload->>'entity_type_text' AS entity_type_text,
                       nullif(upper(trim(payload->>'state')), '') AS state,
                       nullif(trim(payload->>'postcode'), '') AS postcode,
                       payload->'other_names' AS other_names,
                       payload->'dgr' AS dgr,
                       last_seen_snapshot, identifiers
                FROM source_record WHERE source = 'abr'
                QUALIFY row_number() OVER (PARTITION BY record_id ORDER BY {_LATEST}) = 1"""
        )
        # ASIC records in scope: joinable to the ABR slice by ACN or ABN, or Tier 2 referenced.
        con.execute(
            f"""CREATE OR REPLACE TEMP TABLE _asic AS
                WITH latest AS (
                    -- ACN-scheme records only: an ARBN body (FNOS / RACN) has acn NULL.
                    SELECT * FROM (
                        SELECT record_id AS acn, acn AS acn_col, abn, name_raw, name_norm, payload,
                               last_seen_snapshot, identifiers
                        FROM source_record WHERE source = 'asic_company'
                        QUALIFY row_number() OVER (PARTITION BY record_id ORDER BY {_LATEST}) = 1)
                    WHERE acn_col IS NOT NULL),
                abn_claims AS (SELECT abn, count(*) AS n_acn FROM latest WHERE abn IS NOT NULL GROUP BY abn)
                SELECT l.acn, l.abn, l.name_raw, l.name_norm,
                       l.payload->>'status' AS asic_status, l.payload->>'type' AS asic_type,
                       l.payload->>'class' AS asic_class,
                       TRY_CAST(l.payload->>'date_of_registration' AS DATE) AS reg_date,
                       TRY_CAST(l.payload->>'date_of_deregistration' AS DATE) AS dereg_date,
                       l.payload->'former_names' AS former_names,
                       coalesce(c.n_acn, 0) AS abn_n_acn,
                       l.acn IN (SELECT acn FROM _t2_acn) AS t2_ref,
                       l.last_seen_snapshot, l.identifiers
                FROM latest l LEFT JOIN abn_claims c USING (abn)
                WHERE l.acn IN (SELECT acn FROM _abr WHERE acn IS NOT NULL)
                   OR l.abn IN (SELECT abn FROM _abr)
                   OR l.acn IN (SELECT acn FROM _t2_acn)"""
        )

    def _stage_names(self) -> None:
        """Alias candidates, normalised in Python (once per distinct raw string)."""
        con = self.con
        con.execute(
            """CREATE OR REPLACE TEMP TABLE _abr_alias AS
               SELECT DISTINCT abn, alias, alias_type FROM (
                   SELECT a.abn, trim(o->>'name') AS alias,
                          CASE o->>'type' WHEN 'BN' THEN 'business_name' WHEN 'TRD' THEN 'trading_name'
                                          WHEN 'OTN' THEN 'other_name' WHEN 'DGR' THEN 'dgr_name'
                                          ELSE 'other_name' END AS alias_type
                   FROM _abr a, unnest(CAST(a.other_names AS JSON[])) AS t(o)
                   UNION ALL
                   SELECT a.abn, trim(d->>'name'), 'dgr_name'
                   FROM _abr a, unnest(CAST(a.dgr AS JSON[])) AS t(d))
               WHERE alias IS NOT NULL AND alias <> ''"""
        )
        con.execute(
            """CREATE OR REPLACE TEMP TABLE _asic_alias AS
               SELECT DISTINCT s.acn, trim(f) AS alias, 'former_name' AS alias_type
               FROM _asic s, unnest(CAST(s.former_names AS VARCHAR[])) AS t(f)
               WHERE f IS NOT NULL AND trim(f) <> ''"""
        )
        raws = [r[0] for r in self._x(
            "SELECT alias FROM _abr_alias UNION SELECT alias FROM _asic_alias ORDER BY 1"
        )]
        norms = []
        for raw in raws:
            n = self.names.normalise(raw)
            norms.append(n.norm if n and n.norm else None)
        con.register("_names_in", pa.table({"alias": pa.array(raws, pa.string()),
                                             "alias_norm": pa.array(norms, pa.string())}))
        try:
            con.execute("CREATE OR REPLACE TEMP TABLE _names AS SELECT * FROM _names_in")
        finally:
            con.unregister("_names_in")

    def _stage_pairs_and_conflicts(self) -> None:
        con = self.con
        jw, tok = self.JW_MIN, self.TOKEN_OVERLAP_MIN
        con.execute(
            """CREATE OR REPLACE TEMP TABLE _pair AS
               SELECT a.abn AS abr_abn, s.acn AS asic_acn, 'acn' AS basis
               FROM _abr a JOIN _asic s ON s.acn = a.acn
               UNION ALL
               SELECT a.abn, s.acn, 'asic_abn'
               FROM _abr a JOIN _asic s ON s.abn = a.abn
               WHERE a.acn IS NULL"""
        )
        # Identifier invariants. One row per (invariant, involved record): abr_abn or
        # asic_acn says which record; conflict_acn is the ACN whose ownership is in doubt.
        con.execute(
            """CREATE OR REPLACE TEMP TABLE _conflict AS
            WITH multi AS (
                SELECT acn, list(abn || ':' || coalesce(abn_status, '?') ORDER BY abn) AS abns
                FROM _abr WHERE acn IS NOT NULL GROUP BY acn HAVING count(*) > 1),
            fwd AS (  -- ABR: ABN X has ACN Y.  ASIC: ACN Y has ABN Z <> X.
                SELECT a.abn AS x, a.acn AS y, s.abn AS z
                FROM _abr a JOIN _asic s ON s.acn = a.acn
                WHERE s.abn IS NOT NULL AND s.abn <> a.abn),
            fwd_rec AS (  -- both X and (when it is an ABR party) Z are involved
                SELECT x AS rec, x, y, z FROM fwd
                UNION ALL SELECT z, x, y, z FROM fwd WHERE z IN (SELECT abn FROM _abr)),
            rev AS (  -- ASIC: ACN Y2 has ABN X.  ABR: ABN X has ACN Y <> Y2.
                SELECT a.abn AS x, a.acn AS y, s.acn AS y2
                FROM _abr a JOIN _asic s ON s.abn = a.abn
                WHERE a.acn IS NOT NULL AND s.acn <> a.acn),
            multi_abn AS (  -- ABR gives no ACN for X; several ASIC ACNs claim X.
                SELECT a.abn AS x, list(s.acn ORDER BY s.acn) AS acns
                FROM _abr a JOIN _asic s ON s.abn = a.abn
                WHERE a.acn IS NULL GROUP BY a.abn HAVING count(*) > 1)
            SELECT DISTINCT invariant, abr_abn, asic_acn, conflict_acn, detail::VARCHAR AS detail FROM (
                SELECT 'ACN_MULTIPLE_ABN' AS invariant, a.abn AS abr_abn, NULL::VARCHAR AS asic_acn,
                       m.acn AS conflict_acn,
                       json_object('acn', m.acn, 'abr_abns', m.abns, 'asic_abn', s.abn) AS detail
                FROM multi m JOIN _abr a ON a.acn = m.acn LEFT JOIN _asic s ON s.acn = m.acn
                UNION ALL
                SELECT 'ACN_MULTIPLE_ABN', NULL, s.acn, m.acn,
                       json_object('acn', m.acn, 'abr_abns', m.abns, 'asic_abn', s.abn)
                FROM multi m JOIN _asic s ON s.acn = m.acn
                UNION ALL
                SELECT 'ABN_ACN_DISAGREE', rec, NULL, y,
                       json_object('direction', 'abr_acn_vs_asic_abn', 'abr_abn', x, 'abr_acn', y,
                                   'asic_acn', y, 'asic_abn', z)
                FROM fwd_rec
                UNION ALL
                SELECT 'ABN_ACN_DISAGREE', NULL, y, y,
                       json_object('direction', 'abr_acn_vs_asic_abn', 'abr_abn', x, 'abr_acn', y,
                                   'asic_acn', y, 'asic_abn', z)
                FROM fwd
                UNION ALL  -- the ABR side has a consistent ACN here; only the ASIC claim is in doubt
                SELECT 'ABN_ACN_DISAGREE', NULL, y2, y2,
                       json_object('direction', 'asic_abn_vs_abr_acn', 'abr_abn', x, 'abr_acn', y,
                                   'asic_acn', y2, 'asic_abn', x)
                FROM rev
                UNION ALL
                SELECT 'ABN_MULTIPLE_ACN', x, NULL, NULL, json_object('abn', x, 'asic_acns', acns)
                FROM multi_abn
                UNION ALL
                SELECT 'ABN_MULTIPLE_ACN', NULL, acn, acn, json_object('abn', x, 'asic_acns', acns)
                FROM (SELECT x, acns, unnest(acns) AS acn FROM multi_abn))"""
        )
        con.execute(
            """CREATE OR REPLACE TEMP TABLE _idclean AS
               SELECT p.* FROM _pair p
               WHERE p.asic_acn NOT IN (SELECT conflict_acn FROM _conflict WHERE conflict_acn IS NOT NULL)
                 AND NOT (p.basis = 'asic_abn' AND p.abr_abn IN (
                          SELECT abr_abn FROM _conflict
                          WHERE invariant = 'ABN_MULTIPLE_ACN' AND abr_abn IS NOT NULL))"""
        )
        # Name test on identifier-clean pairs. "Clearly different" = every similarity test fails.
        con.execute(
            """CREATE OR REPLACE TEMP TABLE _named AS
            WITH n AS (
                SELECT p.abr_abn, p.asic_acn, p.basis, a.name_norm AS abr_norm, s.name_norm AS asic_norm,
                       a.name_raw AS abr_name, s.name_raw AS asic_name,
                       list_distinct(string_split(coalesce(a.name_norm, ''), ' ')) AS atok,
                       list_distinct(string_split(coalesce(s.name_norm, ''), ' ')) AS stok
                FROM _idclean p JOIN _abr a ON a.abn = p.abr_abn JOIN _asic s ON s.acn = p.asic_acn)
            SELECT abr_abn, asic_acn, basis, abr_norm, asic_norm, abr_name, asic_name,
                   coalesce(jaro_winkler_similarity(coalesce(abr_norm, ''), coalesce(asic_norm, '')), 0) AS jw,
                   len(list_intersect(atok, stok)) / greatest(least(len(atok), len(stok)), 1) AS tok
            FROM n"""
        )
        con.execute(
            f"""CREATE OR REPLACE TEMP TABLE _mismatch AS
            SELECT n.* FROM _named n
            WHERE coalesce(n.abr_norm, '') <> coalesce(n.asic_norm, '')
              AND n.jw < {jw} AND n.tok < {tok}
              -- ABR's name is not one of ASIC's former names ...
              AND NOT EXISTS (
                  SELECT 1 FROM _asic_alias f JOIN _names nm USING (alias)
                  WHERE f.acn = n.asic_acn
                    AND jaro_winkler_similarity(coalesce(nm.alias_norm, ''), coalesce(n.abr_norm, '')) >= {jw})
              -- ... and ASIC's name is not one of ABR's business / trading / other names.
              AND NOT EXISTS (
                  SELECT 1 FROM _abr_alias o JOIN _names nm USING (alias)
                  WHERE o.abn = n.abr_abn
                    AND jaro_winkler_similarity(coalesce(nm.alias_norm, ''), coalesce(n.asic_norm, '')) >= {jw})"""
        )
        con.execute(
            """INSERT INTO _conflict
               SELECT DISTINCT 'NAME_MISMATCH', r.abr_abn, r.asic_acn, m.asic_acn,
                      json_object('abr_abn', m.abr_abn, 'asic_acn', m.asic_acn, 'basis', m.basis,
                                  'abr_name', m.abr_name, 'asic_name', m.asic_name,
                                  'jaro_winkler', round(m.jw, 3), 'token_overlap', round(m.tok, 3))::VARCHAR
               FROM _mismatch m JOIN (
                    SELECT abr_abn, NULL::VARCHAR AS asic_acn, abr_abn AS k_abn, asic_acn AS k_acn FROM _mismatch
                    UNION ALL SELECT NULL, asic_acn, abr_abn, asic_acn FROM _mismatch) r
                 ON r.k_abn = m.abr_abn AND r.k_acn = m.asic_acn"""
        )
        con.execute(
            """CREATE OR REPLACE TEMP TABLE _clean AS
               SELECT p.* FROM _idclean p
               ANTI JOIN _mismatch m ON m.abr_abn = p.abr_abn AND m.asic_acn = p.asic_acn"""
        )

    def _stage_parties(self) -> None:
        con = self.con
        state_slice = self._state_slice_sql()
        con.execute(
            f"""CREATE OR REPLACE TEMP TABLE _party AS
            WITH abr_p AS (
                SELECT 'urn:abn:' || a.abn AS canonical_key, a.party_type,
                       a.name_raw AS name, a.name_norm, a.abn,
                       CASE WHEN c.asic_acn IS NOT NULL THEN c.asic_acn
                            WHEN a.acn IS NOT NULL
                                 AND a.acn NOT IN (SELECT conflict_acn FROM _conflict WHERE conflict_acn IS NOT NULL)
                                 AND a.acn NOT IN (SELECT acn FROM _asic)
                            THEN a.acn END AS acn,
                       a.entity_type, a.entity_type_text, a.abn_status, a.abn_status_from,
                       s.asic_status, s.asic_type, s.asic_class, s.acn AS asic_record_id,
                       a.state, a.postcode,
                       -- Validity: ASIC registration / deregistration when joined (the company's
                       -- life), else the ABN's status-from date (start if active, end if cancelled).
                       CASE WHEN s.acn IS NOT NULL AND s.reg_date IS NOT NULL THEN s.reg_date
                            WHEN a.abn_status = 'ACT' THEN a.abn_status_from END AS valid_from,
                       CASE WHEN s.acn IS NOT NULL THEN s.dereg_date
                            WHEN a.abn_status = 'CAN' THEN a.abn_status_from END AS valid_to,
                       CASE WHEN a.abn_status = 'ACT' THEN 'ACTIVE'
                            WHEN a.abn_status = 'CAN' THEN 'CANCELLED'
                            ELSE a.abn_status END AS status,
                       'abr' AS source, a.abn AS record_id,
                       CASE WHEN {state_slice} THEN 'state_slice'
                            WHEN a.abn IN (SELECT abn FROM _t2_abn) OR a.acn IN (SELECT acn FROM _t2_acn)
                            THEN 'tier2_reference'
                            -- loaded only as the other side of an ACN shared by two ABNs
                            ELSE 'acn_conflict_evidence' END AS slice_reason,
                       'abr' AS origin
                FROM _abr a LEFT JOIN _clean c ON c.abr_abn = a.abn LEFT JOIN _asic s ON s.acn = c.asic_acn),
            conflict_asic AS (  -- ASIC side of a conflict: kept as its own (quarantined) party
                SELECT DISTINCT acn FROM (
                    SELECT asic_acn AS acn FROM _conflict WHERE asic_acn IS NOT NULL
                    UNION SELECT conflict_acn FROM _conflict WHERE conflict_acn IN (SELECT acn FROM _asic))
                WHERE acn NOT IN (SELECT asic_acn FROM _clean)),
            asic_keys AS (
                SELECT acn, 'conflict' AS origin FROM conflict_asic
                UNION ALL
                SELECT s.acn, 'asic_tier2' FROM _asic s
                WHERE s.t2_ref AND s.acn NOT IN (SELECT asic_acn FROM _pair)
                  AND s.acn NOT IN (SELECT acn FROM conflict_asic)),
            -- slice_reason of a conflict-side ASIC party: inherited from the ABR parties it
            -- conflicts with ('state_slice' wins), 'tier2_reference' if Tier 2 references it.
            inherited AS (
                SELECT k.conflict_acn AS acn, min(p.slice_reason) AS slice_reason
                FROM _conflict k JOIN abr_p p
                  ON p.abn IN (k.abr_abn, k.detail->>'abr_abn', k.detail->>'abn')
                GROUP BY 1),
            asic_p AS (
                SELECT 'urn:acn:' || s.acn AS canonical_key, 'organisation' AS party_type,
                       s.name_raw AS name, s.name_norm,
                       CASE WHEN s.abn IS NOT NULL AND s.abn NOT IN (SELECT abn FROM _abr)
                                 AND s.abn_n_acn = 1 THEN s.abn END AS abn,
                       s.acn, s.asic_type AS entity_type, NULL AS entity_type_text,
                       NULL AS abn_status, NULL::DATE AS abn_status_from,
                       s.asic_status, s.asic_type, s.asic_class, s.acn AS asic_record_id,
                       NULL AS state, NULL AS postcode,
                       s.reg_date AS valid_from, s.dereg_date AS valid_to,
                       CASE s.asic_status WHEN 'REGD' THEN 'ACTIVE' WHEN 'DRGD' THEN 'DEREGISTERED'
                            ELSE s.asic_status END AS status,
                       'asic_company' AS source, s.acn AS record_id,
                       CASE WHEN s.t2_ref THEN 'tier2_reference'
                            ELSE coalesce(i.slice_reason, 'tier2_reference') END AS slice_reason,
                       k.origin
                FROM asic_keys k JOIN _asic s ON s.acn = k.acn LEFT JOIN inherited i ON i.acn = s.acn)
            SELECT * FROM abr_p UNION ALL BY NAME SELECT * FROM asic_p"""
        )
        self._assign_keys()
        # Quarantine rows: one per (invariant, involved record), with the party it belongs to.
        con.execute(
            """CREATE OR REPLACE TEMP TABLE _qrow AS
               WITH r AS (
                   SELECT CASE WHEN k.abr_abn IS NOT NULL THEN 'abr' ELSE 'asic_company' END AS source,
                          coalesce(k.abr_abn, k.asic_acn) AS record_id, k.invariant, k.detail,
                          CASE WHEN k.abr_abn IS NOT NULL THEN
                                    (SELECT p.canonical_key FROM _party p WHERE p.source = 'abr' AND p.abn = k.abr_abn)
                               ELSE (SELECT p.canonical_key FROM _party p WHERE p.asic_record_id = k.asic_acn
                                     ORDER BY p.source DESC LIMIT 1) END AS canonical_key
                   FROM _conflict k)
               -- One row per (invariant, involved record, conflict). A conflict involves several
               -- records (e.g. two ABR claimants and the ASIC record): each gets its own row, and
               -- the detail names the record the row is about, so no two rows read the same.
               SELECT source, record_id, invariant,
                      json_merge_patch(detail::JSON,
                                       json_object('record', source || ':' || record_id))::VARCHAR AS detail,
                      min(canonical_key) AS canonical_key
               FROM r GROUP BY source, record_id, invariant, detail"""
        )

    def _assign_keys(self) -> None:
        con = self.con
        # Seed existing databases before replacing the canonical tables.
        if not self._x("SELECT 1 FROM party_key_registry LIMIT 1"):
            con.execute(
                """INSERT INTO party_key_registry (scheme, value, canonical_key)
                   WITH fields AS (
                       SELECT scheme, value, canonical_key FROM (
                           UNPIVOT party_canonical ON abn, acn, lei INTO NAME scheme VALUE value)
                       QUALIFY count(*) OVER (PARTITION BY scheme, value) = 1),
                   registered AS (
                       SELECT i.scheme, i.value, i.canonical_key
                       FROM identifier i JOIN party_canonical p USING (canonical_key)
                       WHERE i.scheme IN ('abn', 'acn', 'arbn', 'arsn', 'lei'))
                   SELECT * FROM registered
                   UNION ALL SELECT * FROM fields ANTI JOIN registered USING (scheme, value)"""
            )
        con.execute(
            """CREATE OR REPLACE TEMP TABLE _party_ids AS
               SELECT source, record_id, scheme, value FROM (
                   SELECT source, record_id, scheme, value FROM (
                       UNPIVOT _party ON abn, acn INTO NAME scheme VALUE value)
                   UNION
                   SELECT p.source, p.record_id, j.value->>0, j.value->>1
                   FROM _party p
                   LEFT JOIN _abr a ON p.source = 'abr' AND a.abn = p.record_id
                   LEFT JOIN _asic s ON s.acn = p.asic_record_id,
                   LATERAL json_each(list_concat(a.identifiers::JSON[], s.identifiers::JSON[])::JSON) j
                   WHERE j.value->>0 IN ('arbn', 'arsn', 'lei') AND j.value->>1 IS NOT NULL)
               QUALIFY count(*) OVER (PARTITION BY scheme, value) = 1"""
        )
        con.execute(
            """CREATE OR REPLACE TEMP TABLE _party_keys AS
               WITH preferred AS (
                   SELECT p.source, p.record_id, p.canonical_key AS source_key,
                          coalesce(r.canonical_key, 'urn:' || i.scheme || ':' || i.value) AS preferred_key
                   FROM _party p JOIN _party_ids i USING (source, record_id)
                   LEFT JOIN party_key_registry r USING (scheme, value)
                   QUALIFY row_number() OVER (PARTITION BY p.source, p.record_id
                       ORDER BY r.minted_at NULLS LAST,
                                CASE i.scheme WHEN 'abn' THEN 1 WHEN 'acn' THEN 2
                                     WHEN 'lei' THEN 3 ELSE 4 END, i.scheme, i.value) = 1)
               SELECT source, record_id, preferred_key,
                      CASE WHEN row_number() OVER (PARTITION BY preferred_key
                              ORDER BY source_key <> preferred_key, source_key) = 1
                           THEN preferred_key ELSE source_key END AS canonical_key
               FROM preferred"""
        )
        con.execute(
            """UPDATE _party p SET canonical_key = k.canonical_key FROM _party_keys k
               WHERE p.source = k.source AND p.record_id = k.record_id AND p.canonical_key <> k.canonical_key"""
        )
        # A newly quarantined split can expose two parties that used to share a key.
        # Its original identifier retains the key; the separated identifiers get their own.
        con.execute(
            """UPDATE party_key_registry r SET canonical_key = k.canonical_key, minted_at = current_timestamp
               FROM _party_ids i JOIN _party_keys k USING (source, record_id)
               WHERE k.preferred_key <> k.canonical_key AND r.canonical_key = k.preferred_key
                 AND r.scheme = i.scheme AND r.value = i.value"""
        )
        con.execute(
            """INSERT INTO party_key_registry (scheme, value, canonical_key)
               SELECT i.scheme, i.value, p.canonical_key
               FROM _party_ids i ANTI JOIN party_key_registry USING (scheme, value)
               JOIN _party p USING (source, record_id)"""
        )

    def _write(self) -> None:
        con = self.con
        detected = self._x(
            "SELECT coalesce(max(last_seen_snapshot), DATE '1970-01-01')::TIMESTAMP FROM "
            "(SELECT last_seen_snapshot FROM _abr UNION ALL SELECT last_seen_snapshot FROM _asic)"
        )[0][0]
        con.execute("DELETE FROM party_canonical")
        con.execute(
            """INSERT INTO party_canonical (canonical_key, party_type, name, name_norm, abn, acn, lei,
                   entity_type, entity_type_text, status, state, postcode, anzsic, valid_from, valid_to,
                   source, record_id, abn_status, abn_status_from, asic_status, asic_type, asic_class,
                   asic_record_id, slice_reason, quarantined)
               SELECT p.canonical_key, p.party_type, p.name, p.name_norm, p.abn, p.acn, i.value,
                      p.entity_type, p.entity_type_text, p.status, p.state, p.postcode, NULL,
                      p.valid_from, p.valid_to, p.source, p.record_id, p.abn_status, p.abn_status_from,
                      p.asic_status, p.asic_type, p.asic_class, p.asic_record_id, p.slice_reason,
                      p.canonical_key IN (SELECT canonical_key FROM _qrow WHERE canonical_key IS NOT NULL)
               FROM _party p LEFT JOIN (
                   SELECT source, record_id, min(value) AS value FROM _party_ids WHERE scheme = 'lei'
                   GROUP BY source, record_id) i USING (source, record_id)
               ORDER BY p.canonical_key"""
        )
        con.execute("DELETE FROM identifier")
        # Only values that belong to exactly one party.
        con.execute(
            """INSERT INTO identifier (canonical_key, scheme, value)
               SELECT p.canonical_key, i.scheme, i.value
               FROM _party_ids i JOIN _party p USING (source, record_id)
               ORDER BY i.scheme, i.value"""
        )
        con.execute("DELETE FROM alias")
        con.execute(
            """INSERT INTO alias (canonical_key, alias, alias_norm, alias_type, source, record_id)
               SELECT DISTINCT * FROM (
                   SELECT p.canonical_key, o.alias, n.alias_norm, o.alias_type, 'abr', o.abn
                   FROM _abr_alias o JOIN _party p ON p.source = 'abr' AND p.abn = o.abn
                   LEFT JOIN _names n USING (alias)
                   UNION ALL
                   SELECT p.canonical_key, f.alias, n.alias_norm, f.alias_type, 'asic_company', f.acn
                   FROM _asic_alias f JOIN _party p ON p.asic_record_id = f.acn
                   LEFT JOIN _names n USING (alias)
                   UNION ALL  -- ASIC's current name on a merged ABR party, when it differs
                   SELECT p.canonical_key, s.name_raw, s.name_norm, 'register_name', 'asic_company', s.acn
                   FROM _party p JOIN _asic s ON s.acn = p.asic_record_id
                   WHERE p.source = 'abr' AND coalesce(s.name_norm, '') <> coalesce(p.name_norm, ''))
               ORDER BY 1, 4, 2, 5, 6"""
        )
        marks = ", ".join("?" for _ in INVARIANTS)
        con.execute(f"DELETE FROM quarantine WHERE invariant IN ({marks})", list(INVARIANTS))
        con.execute(
            """INSERT INTO quarantine (source, record_id, invariant, detail, detected_at, canonical_key)
               SELECT source, record_id, invariant, detail, ?, canonical_key FROM _qrow
               ORDER BY invariant, source, record_id, detail""",
            [detected],
        )

    # ------------------------------------------------------------------ reporting

    def stats(self) -> BuildStats:
        s = BuildStats()
        s.parties = self._x("SELECT count(*) FROM party_canonical")[0][0]
        s.by_party_type = dict(self._x("SELECT party_type, count(*) FROM party_canonical GROUP BY 1 ORDER BY 1"))
        s.by_slice_reason = dict(self._x("SELECT slice_reason, count(*) FROM party_canonical GROUP BY 1 ORDER BY 1"))
        s.by_origin = dict(self._x(
            "SELECT CASE WHEN source = 'abr' THEN 'abr' WHEN quarantined THEN 'asic_conflict_side' "
            "ELSE 'asic_tier2_only' END, count(*) FROM party_canonical GROUP BY 1 ORDER BY 1"
        ))
        s.identifiers = dict(self._x("SELECT scheme, count(*) FROM identifier GROUP BY 1 ORDER BY 1"))
        s.aliases = dict(self._x("SELECT alias_type, count(*) FROM alias GROUP BY 1 ORDER BY 1"))
        marks = ", ".join("?" for _ in INVARIANTS)
        s.quarantine = dict(self._x(
            f"SELECT invariant, count(*) FROM quarantine WHERE invariant IN ({marks}) GROUP BY 1 ORDER BY 1",
            list(INVARIANTS),
        ))
        s.quarantined_parties = self._x("SELECT count(*) FROM party_canonical WHERE quarantined")[0][0]
        s.asic_enriched = self._x(
            "SELECT count(*) FROM party_canonical WHERE source = 'abr' AND asic_record_id IS NOT NULL"
        )[0][0]
        return s


def build_canonical(store: DuckDBStore, **kwargs: Any) -> BuildStats:
    return CanonicalBuilder(store, **kwargs).build()


__all__ = ["INVARIANTS", "BuildStats", "CanonicalBuilder", "build_canonical", "tier2_reference_ids"]
