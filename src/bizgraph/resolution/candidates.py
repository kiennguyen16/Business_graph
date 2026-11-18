"""Candidate generation: the exact path (identifier and unique-name joins) and blocking.

All generators read three derived tables that `NameIndex.ensure` builds once from
`party_canonical`, `identifier` and `alias` (and rebuilds when those change):

* ``res_party_identifier(scheme, value, canonical_key)``: the `identifier` table plus
  the ABN / ACN / LEI columns of every party, *including* values the canonical build
  refused to put in `identifier` because two parties carry them. The exact path must
  see those (and then abstain), not silently miss them.
* ``res_name_index(canonical_key, name_norm, name_raw, kind, block_token, state,
  party_type, n_keys)``: one row per party name and alias; n_keys = how many parties
  carry that normalised name (NAME_NORMALISED_EXACT needs exactly one).
* ``res_name_token(token, canonical_key)`` + ``res_token_df(token, df, idf)``: an
  inverted index on distinctive tokens, the full-text blocker (IDF-weighted token
  retrieval; no FTS extension needed, so it also works offline).
* ``res_foreign_reg(canonical_key)``: parties that are the Australian registration of a
  foreign body (ABR OIE, ASIC FNOS / RACN, ARBN): the only name targets a non-AU entity may have.
* ``res_block_size(block_token, n)``: block sizes, so oversized blocks are skipped.
* ``res_person_vocab(role, token, n)``: frequent given names / surnames of person parties
  (first / last token, 20+ parties), used to recognise person-shaped references.

Every generated candidate carries the `path` that found it and the exact SQL text
(`query_text`) that returns it for that reference, with literals inlined.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import duckdb

from bizgraph.normalise.names import GENERIC_TOKENS
from bizgraph.resolution.decision import PATH_EMBEDDING, PATH_EXACT_ID, PATH_FTS, PATH_NAME_EXACT, PATH_TOKEN_STATE
from bizgraph.resolution.reference import LICENCE_SCHEMES, PARTY_SCHEMES, Reference

if TYPE_CHECKING:
    from bizgraph.resolution.features import Embedder

JOINABLE_SCHEMES: frozenset[str] = PARTY_SCHEMES | LICENCE_SCHEMES


def sql_lit(v: Any) -> str:
    if v is None:
        return "NULL"
    return "'" + str(v).replace("'", "''") + "'"


@dataclass(frozen=True)
class GeneratedCandidate:
    canonical_key: str
    path: str
    query_text: str


# --------------------------------------------------------------------------- index


class NameIndex:
    """Builds and refreshes the derived resolution tables (see module docstring)."""

    INDEX_VERSION = "v5"  # bump when the derived table definitions change

    def __init__(self, con: duckdb.DuckDBPyConnection) -> None:
        self.con = con

    def _register_norms(self) -> None:
        """Normalise every party name and alias with the CURRENT NameNormaliser.

        `party_canonical.name_norm` comes from the ingest-time `source_record.name_norm`, so a
        normaliser change would otherwise need a re-ingest of every Tier 1 record before the
        index saw it. References are normalised with the current code; the index must agree.
        """
        import pyarrow as pa

        from bizgraph.normalise.names import NameNormaliser

        names = NameNormaliser()
        keys: list[str] = []
        raws: list[str] = []
        kinds: list[str] = []
        norms: list[str | None] = []
        cur = self.con.cursor()
        cur.execute(
            """SELECT canonical_key, name, 'name', party_type FROM party_canonical WHERE name IS NOT NULL
               UNION ALL
               SELECT a.canonical_key, a.alias, a.alias_type, p.party_type FROM alias a
               JOIN party_canonical p USING (canonical_key) WHERE a.alias IS NOT NULL"""
        )
        cache: dict[tuple[str, bool], str | None] = {}
        while rows := cur.fetchmany(100_000):
            for key, raw, kind, ptype in rows:
                person = ptype == "person" and kind not in ("business_name", "trading_name")
                ck = (raw, person)
                if ck not in cache:
                    n = names.normalise_person(raw) if person else names.normalise(raw)
                    cache[ck] = n.norm if n else None
                keys.append(key)
                raws.append(raw)
                kinds.append(kind)
                norms.append(cache[ck])
            if len(cache) > 300_000:
                cache.clear()
        cur.close()
        self.con.register("_res_norms", pa.table({
            "canonical_key": pa.array(keys, pa.string()),
            "name_raw": pa.array(raws, pa.string()),
            "kind": pa.array(kinds, pa.string()),
            "name_norm": pa.array(norms, pa.string()),
        }))

    def _fingerprint(self) -> str:
        row = self.con.execute(
            """SELECT (SELECT count(*) FROM party_canonical) || ':' ||
                      (SELECT coalesce(sum(hash(canonical_key, name_norm, abn, acn, lei, state,
                                                 party_type, coalesce(quarantined, false))), 0)
                       FROM party_canonical) || ':' ||
                      (SELECT count(*) FROM alias) || ':' ||
                      (SELECT coalesce(sum(hash(canonical_key, alias, alias_type)), 0) FROM alias) || ':' ||
                      (SELECT coalesce(sum(hash(record_id, content_hash, last_seen_snapshot, load_seq)), 0)
                       FROM source_record WHERE source = 'asic_company') || ':' ||
                      (SELECT coalesce(sum(hash(canonical_key, scheme, value)), 0) FROM identifier)"""
        ).fetchall()
        import hashlib
        from pathlib import Path

        import bizgraph.normalise.names as names_mod

        normaliser = hashlib.sha256(Path(names_mod.__file__).read_bytes()).hexdigest()[:12]
        return f"{self.INDEX_VERSION}:{normaliser}:{row[0][0]}"

    def ensure(self, force: bool = False) -> dict[str, Any]:
        """Build the index unless it is current. Returns build stats (built False when skipped)."""
        con = self.con
        fp = self._fingerprint()
        has_meta = con.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE table_name = 'res_index_meta'"
        ).fetchall()[0][0]
        if has_meta and not force:  # a current index needs no write (works on a read-only store)
            cur = con.execute("SELECT fingerprint FROM res_index_meta").fetchall()
            if cur and cur[0][0] == fp:
                return {"built": False, "fingerprint": fp}
        con.execute("CREATE TABLE IF NOT EXISTS res_index_meta (fingerprint VARCHAR, built_at TIMESTAMP, build_s DOUBLE)")
        t0 = time.perf_counter()
        self._register_norms()
        generic = ", ".join(sql_lit(t) for t in sorted(GENERIC_TOKENS))
        con.execute(
            """CREATE OR REPLACE TABLE res_party_identifier AS
               SELECT DISTINCT scheme, value, canonical_key FROM (
                   SELECT lower(scheme) AS scheme, value, canonical_key FROM identifier
                   UNION ALL SELECT 'abn', abn, canonical_key FROM party_canonical WHERE abn IS NOT NULL
                   UNION ALL SELECT 'acn', acn, canonical_key FROM party_canonical WHERE acn IS NOT NULL
                   UNION ALL SELECT 'lei', lei, canonical_key FROM party_canonical WHERE lei IS NOT NULL)
               ORDER BY scheme, value"""
        )
        con.execute(
            f"""CREATE OR REPLACE TABLE res_name_index AS
                WITH names AS (
                    SELECT DISTINCT canonical_key, name_norm, name_raw, kind FROM _res_norms
                    WHERE name_norm IS NOT NULL AND name_norm <> ''),
                tok AS (
                    SELECT n.*, string_split(n.name_norm, ' ') AS toks FROM names n),
                dist AS (
                    SELECT t.*, list_filter(toks, lambda x: length(x) > 1 AND NOT list_contains([{generic}], x)) AS dtoks
                    FROM tok t)
                SELECT d.canonical_key, d.name_norm, d.name_raw, d.kind,
                       coalesce(d.dtoks[1], d.toks[1]) AS block_token,
                       d.dtoks AS distinctive,
                       upper(p.state) AS state, p.party_type,
                       count(DISTINCT d.canonical_key) OVER (PARTITION BY d.name_norm) AS n_keys
                FROM dist d JOIN party_canonical p USING (canonical_key)
                ORDER BY block_token, d.canonical_key"""
        )
        self._index_former_names()
        # Australian registrations of foreign bodies: ABR "Other Incorporated Entity", ASIC type
        # FNOS / RACN (also through the ASIC record of the party's ACN), or an ARBN.
        has_asic = con.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE table_name = 'source_record'").fetchall()[0][0]
        asic_foreign = (
            """UNION SELECT p.canonical_key FROM party_canonical p
               JOIN (SELECT DISTINCT record_id FROM source_record WHERE source = 'asic_company'
                     AND payload->>'type' IN ('FNOS', 'RACN')) s ON s.record_id = p.acn"""
            if has_asic else ""
        )
        con.execute(
            f"""CREATE OR REPLACE TABLE res_foreign_reg AS
                SELECT canonical_key FROM party_canonical
                WHERE entity_type = 'OIE' OR asic_type IN ('FNOS', 'RACN')
                UNION SELECT canonical_key FROM res_party_identifier WHERE scheme = 'arbn'
                {asic_foreign}"""
        )
        con.execute(
            """CREATE OR REPLACE TABLE res_person_vocab AS
               WITH t AS (SELECT string_split(name_norm, ' ') AS toks FROM party_canonical
                          WHERE party_type = 'person' AND name_norm IS NOT NULL)
               SELECT 'given' AS role, toks[1] AS token, count(*) AS n FROM t
               WHERE len(toks) >= 2 AND length(toks[1]) > 1 GROUP BY 2 HAVING count(*) >= 20
               UNION ALL
               SELECT 'surname', toks[len(toks)], count(*) FROM t
               WHERE len(toks) >= 2 AND length(toks[len(toks)]) > 1 GROUP BY 2 HAVING count(*) >= 20"""
        )
        con.execute(
            """CREATE OR REPLACE TABLE res_block_size AS
               SELECT block_token, count(*) AS n FROM res_name_index GROUP BY block_token"""
        )
        con.execute(
            """CREATE OR REPLACE TABLE res_name_token AS
               SELECT DISTINCT unnest(list_distinct(distinctive)) AS token, canonical_key
               FROM res_name_index ORDER BY token, canonical_key"""
        )
        con.execute(
            """CREATE OR REPLACE TABLE res_token_df AS
               WITH n AS (SELECT count(DISTINCT canonical_key) AS n FROM res_name_index)
               SELECT token, count(*) AS df, ln(1 + (SELECT n FROM n) / count(*)) AS idf
               FROM res_name_token GROUP BY token"""
        )
        con.unregister("_res_norms")
        build_s = time.perf_counter() - t0
        con.execute("DELETE FROM res_index_meta")
        con.execute("INSERT INTO res_index_meta VALUES (?, current_timestamp, ?)", [fp, build_s])
        n = con.execute("SELECT count(*) FROM res_name_index").fetchall()[0][0]
        return {"built": True, "fingerprint": fp, "names": n, "build_s": round(build_s, 2)}

    def _index_former_names(self) -> None:
        """Count holders of compared former names, including companies outside the graph."""
        import pyarrow as pa

        from bizgraph.normalise.names import NameNormaliser
        from bizgraph.pipeline.canonical import _LATEST

        con = self.con
        relevant = {row[0] for row in con.execute(
            "SELECT DISTINCT name_norm FROM res_name_index WHERE kind = 'former_name'"
        ).fetchall()}
        names = NameNormaliser()
        holders: set[tuple[str, str, bool]] = set()
        if relevant:
            cur = con.cursor()
            try:
                cur.execute(f"""WITH latest AS (
                    SELECT record_id, name_raw, payload->'former_names' AS former_names
                    FROM source_record WHERE source = 'asic_company'
                    QUALIFY row_number() OVER (PARTITION BY record_id ORDER BY {_LATEST}) = 1)
                    SELECT coalesce(p.canonical_key, 'asic_company:' || s.record_id),
                           s.name_raw, s.former_names::VARCHAR[]
                    FROM latest s LEFT JOIN party_canonical p ON p.asic_record_id = s.record_id""")
                while rows := cur.fetchmany(50_000):
                    for holder, raw, former in rows:
                        for name in [raw, *(former or ())]:
                            norm = names.normalise(name)
                            if norm and norm.norm in relevant:
                                holders.add((norm.norm, holder, name == raw))
            finally:
                cur.close()
        con.register("_asic_name_holders", pa.table({
            "name_norm": pa.array([h[0] for h in holders], pa.string()),
            "holder": pa.array([h[1] for h in holders], pa.string()),
            "is_current": pa.array([h[2] for h in holders], pa.bool_()),
        }))
        try:
            con.execute("""CREATE OR REPLACE TABLE res_former_name AS
                WITH relevant AS (
                    SELECT DISTINCT name_norm FROM res_name_index WHERE kind = 'former_name'),
                holders AS (
                    SELECT i.name_norm, i.canonical_key AS holder, i.kind <> 'former_name' AS is_current
                    FROM res_name_index i JOIN relevant USING (name_norm)
                    WHERE i.kind IN ('name', 'register_name', 'former_name')
                    UNION ALL SELECT * FROM _asic_name_holders)
                SELECT name_norm, list(DISTINCT holder) FILTER (WHERE is_current) AS current_holders,
                       count(DISTINCT holder) FILTER (WHERE NOT is_current) AS n_former
                FROM holders GROUP BY name_norm""")
        finally:
            con.unregister("_asic_name_holders")


# --------------------------------------------------------------------------- generators


class CandidateGenerator(ABC):
    path_name: str

    @abstractmethod
    def generate(self, ref: Reference, con: duckdb.DuckDBPyConnection) -> list[GeneratedCandidate]: ...


class ExactIdentifierGenerator(CandidateGenerator):
    """Exact path: identifier equality, then normalised-name equality.

    Name equality returns every party carrying the name; whether it may be labelled
    NAME_NORMALISED_EXACT (exactly one party has it) is decided from `n_keys`.
    """

    path_name = PATH_EXACT_ID

    @staticmethod
    def id_sql(scheme: str, value: str) -> str:
        return (
            "SELECT canonical_key FROM res_party_identifier "
            f"WHERE scheme = {sql_lit(scheme)} AND value = {sql_lit(value)}"
        )

    @staticmethod
    def name_sql(name_norm: str) -> str:
        return f"SELECT DISTINCT canonical_key, n_keys FROM res_name_index WHERE name_norm = {sql_lit(name_norm)}"

    def generate_ids(self, ref: Reference, con: duckdb.DuckDBPyConnection) -> list[GeneratedCandidate]:
        out: list[GeneratedCandidate] = []
        for ident in ref.identifiers:
            if ident.scheme.value not in JOINABLE_SCHEMES:
                continue
            sql = self.id_sql(ident.scheme.value, ident.value)
            for (key,) in con.execute(sql).fetchall():
                out.append(GeneratedCandidate(key, PATH_EXACT_ID, sql))
        return out

    def generate_name(self, ref: Reference, con: duckdb.DuckDBPyConnection) -> list[GeneratedCandidate]:
        if not ref.name_norm:
            return []
        sql = self.name_sql(ref.name_norm)
        return [GeneratedCandidate(k, PATH_NAME_EXACT, sql) for k, _ in con.execute(sql).fetchall()]

    def generate(self, ref: Reference, con: duckdb.DuckDBPyConnection) -> list[GeneratedCandidate]:
        return self.generate_ids(ref, con) + self.generate_name(ref, con)


class Blocker(ABC):
    path_name: str
    k: int = 20

    @abstractmethod
    def sql(self, ref: Reference) -> str | None:
        """Per-reference SQL returning (canonical_key, block_score), or None if not applicable."""

    def block(self, ref: Reference, con: duckdb.DuckDBPyConnection) -> list[GeneratedCandidate]:
        sql = self.sql(ref)
        if not sql:
            return []
        return [GeneratedCandidate(k, self.path_name, sql) for k, _ in con.execute(sql).fetchall()]

    def describe(self) -> str:
        return f"{self.path_name}(k={self.k})"

    # Set-based form for the batch path: `refs` is a registered table with columns
    # (record_id, name_norm, block_token, state); `ref_tokens` (record_id, token).
    @abstractmethod
    def batch_sql(self) -> str | None: ...


class TokenStateBlocker(Blocker):
    """Same first distinctive token and same state (state ignored when either side lacks it).
    Inside the block, the top k by Jaro-Winkler on the normalised name."""

    path_name = PATH_TOKEN_STATE

    def __init__(self, k: int = 20, max_block: int = 20_000) -> None:
        self.k = k
        self.max_block = max_block  # blocks larger than this are skipped (recall cost, measured)

    def describe(self) -> str:
        return f"{self.path_name}(k={self.k},max_block={self.max_block})"

    def sql(self, ref: Reference) -> str | None:
        if not ref.block_token or not ref.name_norm:
            return None
        state = (
            f"AND (state IS NULL OR state = {sql_lit(ref.state)}) " if ref.state else ""
        )
        return (
            "SELECT canonical_key, max(jaro_winkler_similarity(name_norm, "
            f"{sql_lit(ref.name_norm)})) AS s FROM res_name_index "
            f"WHERE block_token = {sql_lit(ref.block_token)} {state}"
            f"AND (SELECT n FROM res_block_size WHERE block_token = {sql_lit(ref.block_token)}) <= {self.max_block} "
            f"GROUP BY canonical_key ORDER BY s DESC, canonical_key LIMIT {self.k}"
        )

    def batch_sql(self) -> str:
        return f"""
            SELECT r.record_id, i.canonical_key, max(jaro_winkler_similarity(i.name_norm, r.name_norm)) AS s
            FROM _res_refs r JOIN res_block_size b ON b.block_token = r.block_token AND b.n <= {self.max_block}
            JOIN res_name_index i ON i.block_token = r.block_token
            WHERE r.state IS NULL OR i.state IS NULL OR i.state = r.state
            GROUP BY r.record_id, i.canonical_key
            QUALIFY row_number() OVER (PARTITION BY r.record_id ORDER BY s DESC, i.canonical_key) <= {self.k}"""


class FtsBlocker(Blocker):
    """IDF-weighted retrieval over the distinctive-token inverted index (top k)."""

    path_name = PATH_FTS

    def __init__(self, k: int = 20, max_df: int = 5_000) -> None:
        self.k = k
        self.max_df = max_df  # tokens in more names than this are too common to retrieve on

    def describe(self) -> str:
        return f"{self.path_name}(k={self.k},max_df={self.max_df})"

    def sql(self, ref: Reference) -> str | None:
        toks = sorted(ref.distinctive)
        if not toks:
            return None
        lits = ", ".join(sql_lit(t) for t in toks)
        return (
            "SELECT t.canonical_key, sum(d.idf) AS s FROM res_name_token t JOIN res_token_df d USING (token) "
            f"WHERE t.token IN ({lits}) AND d.df <= {self.max_df} "
            f"GROUP BY t.canonical_key ORDER BY s DESC, t.canonical_key LIMIT {self.k}"
        )

    def batch_sql(self) -> str:
        return f"""
            SELECT rt.record_id, t.canonical_key, sum(d.idf) AS s
            FROM _res_ref_tokens rt JOIN res_name_token t ON t.token = rt.token
            JOIN res_token_df d ON d.token = rt.token
            WHERE d.df <= {self.max_df}
            GROUP BY rt.record_id, t.canonical_key
            QUALIFY row_number() OVER (PARTITION BY rt.record_id ORDER BY s DESC, t.canonical_key) <= {self.k}"""


class EmbeddingBlocker(Blocker):
    """Nearest names by embedding cosine (optional; needs sentence-transformers).

    The vector matrix over `res_name_index` is built in memory on first use, which
    costs minutes at a million names on CPU, so it is opt-in. `query_text` names
    the model and k rather than SQL.
    """

    path_name = PATH_EMBEDDING

    def __init__(self, embedder: Embedder, con: duckdb.DuckDBPyConnection, k: int = 20) -> None:
        self.embedder = embedder
        self.k = k
        rows = con.execute("SELECT DISTINCT name_norm FROM res_name_index ORDER BY name_norm").fetchall()
        self.names = [r[0] for r in rows]
        import numpy as np

        self._np = np
        self.matrix = np.asarray(embedder.model.encode(
            self.names, batch_size=512, normalize_embeddings=True, show_progress_bar=False))
        self._con = con

    def sql(self, ref: Reference) -> str | None:  # not SQL-backed
        return None

    def batch_sql(self) -> None:
        return None

    def block(self, ref: Reference, con: duckdb.DuckDBPyConnection) -> list[GeneratedCandidate]:
        if not ref.name_norm or not self.names:
            return []
        np = self._np
        q = self.embedder.encode([ref.name_norm])[0]
        sims = self.matrix @ q
        top = np.argsort(-sims)[: self.k]
        out: list[GeneratedCandidate] = []
        for i in top:
            name = self.names[int(i)]
            qt = (f"vector top-{self.k} cosine({self.embedder.model_name}) over res_name_index.name_norm "
                  f"for {sql_lit(ref.name_norm)} -> {sql_lit(name)} ({float(sims[i]):.4f}); then "
                  f"SELECT canonical_key FROM res_name_index WHERE name_norm = {sql_lit(name)}")
            for (key,) in con.execute(
                "SELECT DISTINCT canonical_key FROM res_name_index WHERE name_norm = ?", [name]
            ).fetchall():
                out.append(GeneratedCandidate(key, self.path_name, qt))
        return out


class BlockingGenerator(CandidateGenerator):
    path_name = "blocking"

    def __init__(self, blockers: list[Blocker]) -> None:
        self.blockers = blockers

    def generate(self, ref: Reference, con: duckdb.DuckDBPyConnection) -> list[GeneratedCandidate]:
        out: list[GeneratedCandidate] = []
        for b in self.blockers:
            out.extend(b.block(ref, con))
        return out

    def describe(self) -> list[str]:
        return [b.describe() for b in self.blockers]
