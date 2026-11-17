"""DuckDB system of record: schema plus thin repositories.

Every repository takes the shared connection. Bulk writes are set-based:
a batch is turned into a pyarrow table, registered as a view, and merged
with one INSERT ... SELECT (anti-join) plus one UPDATE, never row by row.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
import pyarrow as pa

from bizgraph.domain.models import Identifier, IdScheme, PartyType, SourceRecord

if TYPE_CHECKING:
    from bizgraph.sources.base import LoadStats

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS source_snapshot (
    source            VARCHAR NOT NULL,
    snapshot_date     DATE NOT NULL,
    file_hash         VARCHAR NOT NULL,
    file_path         VARCHAR,
    records_in        BIGINT,
    records_new       BIGINT,
    records_unchanged BIGINT,
    records_rejected  BIGINT,
    rejection_reasons JSON,
    wall_clock_s      DOUBLE,
    loaded_at         TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (source, file_hash)
);

CREATE TABLE IF NOT EXISTS source_record (
    source              VARCHAR NOT NULL,
    record_id           VARCHAR NOT NULL,
    content_hash        VARCHAR NOT NULL,
    snapshot_date       DATE NOT NULL,
    first_seen_snapshot DATE NOT NULL,
    last_seen_snapshot  DATE NOT NULL,
    payload             JSON,
    name_raw            VARCHAR,
    name_norm           VARCHAR,
    party_type          VARCHAR,
    abn                 VARCHAR,
    acn                 VARCHAR,
    lei                 VARCHAR,
    licence_no          VARCHAR,
    state               VARCHAR,
    identifiers         JSON,
    adapter_version     VARCHAR,
    ingested_at         TIMESTAMP,
    load_seq            BIGINT,
    PRIMARY KEY (source, record_id, content_hash)
);

CREATE SEQUENCE IF NOT EXISTS source_record_load_seq;
ALTER TABLE source_record ADD COLUMN IF NOT EXISTS adapter_version VARCHAR;
ALTER TABLE source_record ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMP;
ALTER TABLE source_record ADD COLUMN IF NOT EXISTS load_seq BIGINT;

CREATE TABLE IF NOT EXISTS party_canonical (
    canonical_key VARCHAR PRIMARY KEY,
    party_type    VARCHAR,
    name          VARCHAR,
    name_norm     VARCHAR,
    abn           VARCHAR,
    acn           VARCHAR,
    lei           VARCHAR,
    entity_type   VARCHAR,
    status        VARCHAR,
    state         VARCHAR,
    postcode      VARCHAR,
    anzsic        VARCHAR,
    valid_from    DATE,
    valid_to      DATE,
    source        VARCHAR,
    record_id     VARCHAR
);

CREATE TABLE IF NOT EXISTS identifier (
    canonical_key VARCHAR NOT NULL,
    scheme        VARCHAR NOT NULL,
    value         VARCHAR NOT NULL,
    PRIMARY KEY (scheme, value)
);

CREATE TABLE IF NOT EXISTS quarantine (
    source      VARCHAR NOT NULL,
    record_id   VARCHAR NOT NULL,
    invariant   VARCHAR NOT NULL,
    detail      VARCHAR,
    detected_at TIMESTAMP DEFAULT current_timestamp
);
-- canonical_key: the party the quarantined record belongs to (set by the canonical build).
ALTER TABLE quarantine ADD COLUMN IF NOT EXISTS canonical_key VARCHAR;

-- Canonical-build columns (replace-by-build in bizgraph.pipeline.canonical).
ALTER TABLE party_canonical ADD COLUMN IF NOT EXISTS entity_type_text VARCHAR;
ALTER TABLE party_canonical ADD COLUMN IF NOT EXISTS abn_status VARCHAR;
ALTER TABLE party_canonical ADD COLUMN IF NOT EXISTS abn_status_from DATE;
ALTER TABLE party_canonical ADD COLUMN IF NOT EXISTS asic_status VARCHAR;
ALTER TABLE party_canonical ADD COLUMN IF NOT EXISTS asic_type VARCHAR;
ALTER TABLE party_canonical ADD COLUMN IF NOT EXISTS asic_class VARCHAR;
ALTER TABLE party_canonical ADD COLUMN IF NOT EXISTS asic_record_id VARCHAR;
ALTER TABLE party_canonical ADD COLUMN IF NOT EXISTS slice_reason VARCHAR;
ALTER TABLE party_canonical ADD COLUMN IF NOT EXISTS quarantined BOOLEAN DEFAULT false;

CREATE TABLE IF NOT EXISTS alias (
    canonical_key VARCHAR NOT NULL,
    alias         VARCHAR NOT NULL,
    alias_norm    VARCHAR,
    alias_type    VARCHAR NOT NULL,
    source        VARCHAR NOT NULL,
    record_id     VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate (
    run_id        VARCHAR NOT NULL,
    source        VARCHAR NOT NULL,
    record_id     VARCHAR NOT NULL,
    canonical_key VARCHAR NOT NULL,
    path          VARCHAR NOT NULL DEFAULT '',
    features      JSON,
    score         DOUBLE,
    PRIMARY KEY (run_id, source, record_id, canonical_key, path)
);

CREATE TABLE IF NOT EXISTS matcher_version (
    version    VARCHAR PRIMARY KEY,
    code_hash  VARCHAR,
    policy     JSON,
    created_at TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS link (
    link_id         VARCHAR PRIMARY KEY,
    matcher_version VARCHAR NOT NULL,
    source          VARCHAR NOT NULL,
    record_id       VARCHAR NOT NULL,
    canonical_key   VARCHAR NOT NULL,
    match_type      VARCHAR,
    confidence      DOUBLE,
    evidence        JSON,
    created_at      TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS abstention (
    matcher_version VARCHAR NOT NULL,
    source          VARCHAR NOT NULL,
    record_id       VARCHAR NOT NULL,
    best_candidate  VARCHAR,
    best_score      DOUBLE,
    reason          VARCHAR,
    created_at      TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (matcher_version, source, record_id)
);
-- Why the matcher refused (explanation, best candidate features, query text); written by bizgraph.resolution.
ALTER TABLE abstention ADD COLUMN IF NOT EXISTS evidence JSON;

-- The reference as the matcher saw it, once per (run, source, record) instead of on every
-- candidate row (candidate.features no longer repeats it). Written by bizgraph.resolution.
CREATE TABLE IF NOT EXISTS candidate_ref (
    run_id    VARCHAR NOT NULL,
    source    VARCHAR NOT NULL,
    record_id VARCHAR NOT NULL,
    ref       JSON,
    PRIMARY KEY (run_id, source, record_id)
);

CREATE TABLE IF NOT EXISTS label (
    sample_id     VARCHAR NOT NULL,
    source        VARCHAR NOT NULL,
    record_id     VARCHAR NOT NULL,
    canonical_key VARCHAR,
    is_match      BOOLEAN,
    labeller      VARCHAR,
    notes         VARCHAR,
    created_at    TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (sample_id, source, record_id)
);

"""

TABLES = (
    "source_snapshot",
    "source_record",
    "party_canonical",
    "identifier",
    "alias",
    "quarantine",
    "candidate",
    "candidate_ref",
    "matcher_version",
    "link",
    "abstention",
    "label",
)

_LICENCE_SCHEMES = (IdScheme.AFSL, IdScheme.ACL)
_STATE_KEYS = ("state", "State", "STATE", "state_code", "State_Code", "MainBusinessLocation_State")


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, default=str)


def _rows(cur: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _in_transaction(con: duckdb.DuckDBPyConnection) -> bool:
    """True if the caller has an explicit transaction open (autocommit gives a new txid per statement)."""
    a = con.execute("SELECT txid_current()").fetchall()[0][0]
    b = con.execute("SELECT txid_current()").fetchall()[0][0]
    return a == b


class _Repo:
    def __init__(self, con: duckdb.DuckDBPyConnection) -> None:
        self.con = con


class SnapshotRepository(_Repo):
    CHUNK = 8 * 1024 * 1024  # 8 MB

    @classmethod
    def file_hash(cls, path: Path) -> str:
        """SHA-256 of a file; for a directory, of its sorted relative member names and member hashes.

        A directory hash changes when any member is added, removed, renamed or edited,
        so `run()` on e.g. ``data/raw/abr/`` skips only a byte-identical rerun.
        """
        path = Path(path)
        if path.is_dir():
            h = hashlib.sha256()
            members = sorted(p for p in path.rglob("*") if p.is_file())
            for m in members:
                rel = m.relative_to(path).as_posix()
                h.update(rel.encode("utf-8") + b"|" + cls.file_hash(m).encode("ascii") + b";")
            return h.hexdigest()
        h = hashlib.sha256()
        with path.open("rb") as fh:
            while chunk := fh.read(cls.CHUNK):
                h.update(chunk)
        return h.hexdigest()

    def exists(self, source: str, file_hash: str) -> bool:
        row = self.con.execute(
            "SELECT 1 FROM source_snapshot WHERE source = ? AND file_hash = ?", [source, file_hash]
        ).fetchall()
        return bool(row)

    def record(self, source: str, snapshot_date: date, file_hash: str, path: Path, stats: LoadStats) -> None:
        self.con.execute(
            """INSERT OR REPLACE INTO source_snapshot
               (source, snapshot_date, file_hash, file_path, records_in, records_new,
                records_unchanged, records_rejected, rejection_reasons, wall_clock_s)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                source,
                snapshot_date,
                file_hash,
                str(path),
                stats.records_in,
                stats.records_new,
                stats.records_unchanged,
                stats.records_rejected,
                _json(dict(stats.rejection_reasons)),
                stats.wall_clock_s,
            ],
        )

    def list(self, source: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM source_snapshot"
        params: list[Any] = []
        if source:
            sql += " WHERE source = ?"
            params.append(source)
        return _rows(self.con.execute(sql + " ORDER BY loaded_at", params))


class SourceRecordRepository(_Repo):
    """Immutable source assertions keyed by (source, record_id, content_hash).

    content_hash covers the payload only (it identifies what the source asserted).
    Payloads are stored as JSON with `default=str`, the same serialisation the hash
    uses, so non-JSON values (dates, Decimals) come back as strings.
    Derived columns (name_norm, party_type, identifiers, abn/acn/lei/licence_no,
    state, adapter_version) are refreshed whenever an existing key is seen again,
    so a normaliser upgrade takes effect on the next load without new rows.
    """

    _SCHEMA = pa.schema(
        [
            ("source", pa.string()),
            ("record_id", pa.string()),
            ("content_hash", pa.string()),
            ("first_seen", pa.date32()),
            ("last_seen", pa.date32()),
            ("payload", pa.string()),
            ("name_raw", pa.string()),
            ("name_norm", pa.string()),
            ("party_type", pa.string()),
            ("abn", pa.string()),
            ("acn", pa.string()),
            ("lei", pa.string()),
            ("licence_no", pa.string()),
            ("state", pa.string()),
            ("identifiers", pa.string()),
            ("adapter_version", pa.string()),
        ]
    )
    _COLS = "source, record_id, snapshot_date, payload, name_raw, name_norm, party_type, identifiers"
    _LATEST_ORDER = "last_seen_snapshot DESC, load_seq DESC NULLS LAST, snapshot_date DESC"

    @staticmethod
    def _state(payload: dict[str, Any]) -> str | None:
        for k in _STATE_KEYS:
            v = payload.get(k)
            if v:
                return str(v).strip().upper() or None
        return None

    def _to_arrow(self, records: list[SourceRecord], adapter_version: str | None) -> pa.Table:
        # Collapse duplicates inside the batch: min date -> first_seen, max date -> last_seen,
        # derived fields from the latest occurrence (ties: the later one in the batch).
        merged: dict[tuple[str, str, str], list[Any]] = {}
        for r in records:
            key = (r.source, r.record_id, r.content_hash)
            cur = merged.get(key)
            if cur is None:
                merged[key] = [r.snapshot_date, r.snapshot_date, r]
            else:
                cur[0] = min(cur[0], r.snapshot_date)
                if r.snapshot_date >= cur[1]:
                    cur[1], cur[2] = r.snapshot_date, r
        cols: dict[str, list[Any]] = {name: [] for name in self._SCHEMA.names}
        for (source, record_id, ch), (first, last, r) in merged.items():
            ids = {i.scheme: i.value for i in r.identifiers}
            # first licence identifier in the record's own order (credit records list ACL first)
            licence = next((i.value for i in r.identifiers if i.scheme in _LICENCE_SCHEMES), None)
            cols["source"].append(source)
            cols["record_id"].append(record_id)
            cols["content_hash"].append(ch)
            cols["first_seen"].append(first)
            cols["last_seen"].append(last)
            cols["payload"].append(_json(r.payload))
            cols["name_raw"].append(r.name_raw)
            cols["name_norm"].append(r.name_norm)
            cols["party_type"].append(str(r.party_type))
            cols["abn"].append(ids.get(IdScheme.ABN))
            cols["acn"].append(ids.get(IdScheme.ACN))
            cols["lei"].append(ids.get(IdScheme.LEI))
            cols["licence_no"].append(licence)
            cols["state"].append(self._state(r.payload))
            cols["identifiers"].append(
                _json([[i.scheme.value, i.value] for i in r.identifiers]) if r.identifiers else None
            )
            cols["adapter_version"].append(adapter_version)
        return pa.Table.from_pydict(cols, schema=self._SCHEMA)

    def upsert(self, records: list[SourceRecord], adapter_version: str | None = None) -> int:
        """Insert unseen (source, record_id, content_hash) rows; refresh existing ones.

        Existing keys get first_seen = least(..), last_seen = greatest(..), refreshed
        derived columns and a new load_seq (so the latest load wins date ties).
        Returns the number of NEW rows. Joins a caller's open transaction if there is one.
        """
        if not records:
            return 0
        batch = self._to_arrow(records, adapter_version)
        con = self.con
        own_tx = not _in_transaction(con)
        con.register("_sr_batch", batch)
        try:
            if own_tx:
                con.execute("BEGIN TRANSACTION")
            con.execute(
                """UPDATE source_record AS t
                   SET first_seen_snapshot = least(t.first_seen_snapshot, b.first_seen),
                       last_seen_snapshot  = greatest(t.last_seen_snapshot, b.last_seen),
                       name_raw = b.name_raw, name_norm = b.name_norm, party_type = b.party_type,
                       abn = b.abn, acn = b.acn, lei = b.lei, licence_no = b.licence_no,
                       state = b.state, identifiers = b.identifiers::JSON,
                       adapter_version = coalesce(b.adapter_version, t.adapter_version),
                       ingested_at = current_timestamp,
                       load_seq = nextval('source_record_load_seq')
                   FROM _sr_batch AS b
                   WHERE t.source = b.source AND t.record_id = b.record_id
                     AND t.content_hash = b.content_hash"""
            )
            new = con.execute(
                """INSERT INTO source_record
                       (source, record_id, content_hash, snapshot_date, first_seen_snapshot,
                        last_seen_snapshot, payload, name_raw, name_norm, party_type, abn, acn, lei,
                        licence_no, state, identifiers, adapter_version, ingested_at, load_seq)
                   SELECT b.source, b.record_id, b.content_hash, b.first_seen, b.first_seen, b.last_seen,
                          b.payload::JSON, b.name_raw, b.name_norm, b.party_type, b.abn, b.acn, b.lei,
                          b.licence_no, b.state, b.identifiers::JSON, b.adapter_version,
                          current_timestamp, nextval('source_record_load_seq')
                   FROM _sr_batch AS b
                   ANTI JOIN source_record AS t
                     ON t.source = b.source AND t.record_id = b.record_id
                    AND t.content_hash = b.content_hash"""
            ).fetchall()[0][0]
            if own_tx:
                con.execute("COMMIT")
        except Exception:
            if own_tx:
                con.execute("ROLLBACK")
            raise
        finally:
            con.unregister("_sr_batch")
        return int(new)

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> SourceRecord:
        source, record_id, snapshot_date, payload, name_raw, name_norm, party_type, identifiers = row
        ids = tuple(Identifier(IdScheme(s), v) for s, v in json.loads(identifiers)) if identifiers else ()
        return SourceRecord(
            source=source,
            record_id=record_id,
            snapshot_date=snapshot_date,
            payload=json.loads(payload) if payload else {},
            name_raw=name_raw,
            name_norm=name_norm,
            party_type=PartyType(party_type) if party_type else PartyType.UNKNOWN,
            identifiers=ids,
        )

    def by_source(self, source: str, latest_only: bool = True, batch_size: int = 10_000) -> Iterator[SourceRecord]:
        """Stream records of a source. latest_only keeps one version per record_id:
        highest last_seen_snapshot, then most recently loaded."""
        if latest_only:
            sql = f"""SELECT {self._COLS} FROM source_record WHERE source = ?
                      QUALIFY row_number() OVER (PARTITION BY record_id ORDER BY {self._LATEST_ORDER}) = 1
                      ORDER BY record_id"""
        else:
            sql = (
                f"SELECT {self._COLS} FROM source_record WHERE source = ? "
                "ORDER BY record_id, snapshot_date, load_seq"
            )
        cur = self.con.cursor()
        cur.execute(sql, [source])
        while rows := cur.fetchmany(batch_size):
            for row in rows:
                yield self._from_row(row)
        cur.close()

    def get(self, source: str, record_id: str) -> SourceRecord | None:
        row = self.con.execute(
            f"""SELECT {self._COLS} FROM source_record WHERE source = ? AND record_id = ?
                ORDER BY {self._LATEST_ORDER} LIMIT 1""",
            [source, record_id],
        ).fetchall()
        return self._from_row(row[0]) if row else None

    def count(self, source: str | None = None) -> int:
        if source is None:
            return self.con.execute("SELECT count(*) FROM source_record").fetchall()[0][0]
        return self.con.execute("SELECT count(*) FROM source_record WHERE source = ?", [source]).fetchall()[0][0]

    def counts_by_source(self) -> dict[str, int]:
        return dict(self.con.execute("SELECT source, count(*) FROM source_record GROUP BY 1 ORDER BY 1").fetchall())


class QuarantineRepository(_Repo):
    def add(self, source: str, record_id: str, invariant: str, detail: str | None = None) -> None:
        self.con.execute(
            "INSERT INTO quarantine (source, record_id, invariant, detail) VALUES (?, ?, ?, ?)",
            [source, record_id, invariant, detail],
        )

    def list(self, source: str | None = None) -> list[dict[str, Any]]:
        if source:
            return _rows(self.con.execute("SELECT * FROM quarantine WHERE source = ?", [source]))
        return _rows(self.con.execute("SELECT * FROM quarantine"))


class PartyRepository(_Repo):
    """Read access to the canonical parties built by `bizgraph.pipeline.canonical.CanonicalBuilder`.

    Rows come back as dicts. `by_identifier` resolves through the `identifier` table,
    which only holds values that belong to exactly one party (conflicting values are
    quarantined, not assigned), so it never returns an arbitrary pick among several.
    """

    def get(self, canonical_key: str) -> dict[str, Any] | None:
        rows = _rows(self.con.execute("SELECT * FROM party_canonical WHERE canonical_key = ?", [canonical_key]))
        return rows[0] if rows else None

    def by_identifier(self, scheme: IdScheme | str, value: str) -> dict[str, Any] | None:
        scheme = scheme.value if isinstance(scheme, IdScheme) else str(scheme).lower()
        rows = _rows(
            self.con.execute(
                """SELECT p.* FROM identifier AS i JOIN party_canonical AS p USING (canonical_key)
                   WHERE i.scheme = ? AND i.value = ?""",
                [scheme, value],
            )
        )
        return rows[0] if rows else None

    def by_name_norm(self, name_norm: str) -> list[dict[str, Any]]:
        return _rows(
            self.con.execute(
                "SELECT * FROM party_canonical WHERE name_norm = ? ORDER BY canonical_key", [name_norm]
            )
        )

    def aliases(self, canonical_key: str) -> list[dict[str, Any]]:
        return _rows(
            self.con.execute(
                "SELECT * FROM alias WHERE canonical_key = ? ORDER BY alias_type, alias, source, record_id",
                [canonical_key],
            )
        )

    def count(self) -> int:
        return self.con.execute("SELECT count(*) FROM party_canonical").fetchall()[0][0]


class CandidateRepository(_Repo):
    COLS = ("run_id", "source", "record_id", "canonical_key", "path", "features", "score")

    KEY = ("run_id", "source", "record_id", "canonical_key", "path")

    def save_many(self, rows: Iterable[dict[str, Any]]) -> int:
        """rows: dicts with keys in COLS; `features` may be a dict (stored as JSON).

        Idempotent: PK (run_id, source, record_id, canonical_key, path); re-saving replaces.
        A missing path is stored as ''. Returns the number of input rows processed
        (duplicates of one key inside the call collapse to a single stored row, last wins).
        """
        dedup: dict[tuple[Any, ...], dict[str, Any]] = {}
        seen = 0
        for r in rows:
            seen += 1
            row = {c: r.get(c) for c in self.COLS}
            row["path"] = row["path"] or ""
            f = row["features"]
            row["features"] = f if isinstance(f, (str, type(None))) else _json(f)
            row["score"] = None if row["score"] is None else float(row["score"])
            dedup[tuple(row[k] for k in self.KEY)] = row  # last one wins
        if not dedup:
            return 0
        data = {c: [row[c] for row in dedup.values()] for c in self.COLS}
        tbl = pa.Table.from_pydict(data, schema=pa.schema(
            [(c, pa.float64() if c == "score" else pa.string()) for c in self.COLS]
        ))
        n = seen
        self.con.register("_cand_batch", tbl)
        try:
            self.con.execute(
                "INSERT OR REPLACE INTO candidate SELECT run_id, source, record_id, canonical_key, path, "
                "features::JSON, score FROM _cand_batch"
            )
        finally:
            self.con.unregister("_cand_batch")
        return n

    def for_record(self, source: str, record_id: str, run_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM candidate WHERE source = ? AND record_id = ?"
        params: list[Any] = [source, record_id]
        if run_id:
            sql += " AND run_id = ?"
            params.append(run_id)
        return _rows(self.con.execute(sql + " ORDER BY score DESC", params))


class MatcherVersionRepository(_Repo):
    def save(self, version: str, code_hash: str, policy: dict[str, Any]) -> None:
        """Versions are immutable: re-saving identical content is a no-op, different content raises."""
        existing = self.get(version)
        if existing is not None:
            old_policy = existing["policy"]
            old_policy = json.loads(old_policy) if isinstance(old_policy, str) else old_policy
            if existing["code_hash"] == code_hash and old_policy == json.loads(_json(policy)):
                return
            raise ValueError(f"matcher_version {version!r} already exists with different code_hash/policy")
        self.con.execute(
            "INSERT INTO matcher_version (version, code_hash, policy) VALUES (?, ?, ?)",
            [version, code_hash, _json(policy)],
        )

    def get(self, version: str) -> dict[str, Any] | None:
        rows = _rows(self.con.execute("SELECT * FROM matcher_version WHERE version = ?", [version]))
        return rows[0] if rows else None

    def latest(self) -> dict[str, Any] | None:
        rows = _rows(self.con.execute("SELECT * FROM matcher_version ORDER BY created_at DESC LIMIT 1"))
        return rows[0] if rows else None


class LinkRepository(_Repo):
    def save(
        self,
        link_id: str,
        matcher_version: str,
        source: str,
        record_id: str,
        canonical_key: str,
        match_type: str,
        confidence: float,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        self.con.execute(
            """INSERT OR REPLACE INTO link (link_id, matcher_version, source, record_id, canonical_key,
                                            match_type, confidence, evidence)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [link_id, matcher_version, source, record_id, canonical_key, match_type, confidence, _json(evidence)],
        )

    def for_record(self, source: str, record_id: str) -> list[dict[str, Any]]:
        return _rows(
            self.con.execute("SELECT * FROM link WHERE source = ? AND record_id = ?", [source, record_id])
        )

    def for_party(self, canonical_key: str) -> list[dict[str, Any]]:
        return _rows(self.con.execute("SELECT * FROM link WHERE canonical_key = ?", [canonical_key]))

    def by_version(self, matcher_version: str) -> list[dict[str, Any]]:
        return _rows(self.con.execute("SELECT * FROM link WHERE matcher_version = ?", [matcher_version]))


class AbstentionRepository(_Repo):
    def save(
        self,
        matcher_version: str,
        source: str,
        record_id: str,
        reason: str,
        best_candidate: str | None = None,
        best_score: float | None = None,
    ) -> None:
        self.con.execute(
            """INSERT OR REPLACE INTO abstention (matcher_version, source, record_id, best_candidate,
                                                  best_score, reason)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [matcher_version, source, record_id, best_candidate, best_score, reason],
        )

    def by_version(self, matcher_version: str) -> list[dict[str, Any]]:
        return _rows(self.con.execute("SELECT * FROM abstention WHERE matcher_version = ?", [matcher_version]))


class LabelRepository(_Repo):
    def save(
        self,
        sample_id: str,
        source: str,
        record_id: str,
        canonical_key: str | None,
        is_match: bool | None,
        labeller: str = "",
        notes: str = "",
    ) -> None:
        self.con.execute(
            """INSERT OR REPLACE INTO label (sample_id, source, record_id, canonical_key, is_match,
                                             labeller, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [sample_id, source, record_id, canonical_key, is_match, labeller, notes],
        )

    def by_sample(self, sample_id: str) -> list[dict[str, Any]]:
        return _rows(self.con.execute("SELECT * FROM label WHERE sample_id = ?", [sample_id]))

    def all(self) -> list[dict[str, Any]]:
        return _rows(self.con.execute("SELECT * FROM label"))


class DuckDBStore:
    """Owns the DuckDB connection and exposes one repository per table group."""

    def __init__(self, path: Path | str = ":memory:", read_only: bool = False) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(self.path, read_only=read_only)
        self.snapshots = SnapshotRepository(self.con)
        self.records = SourceRecordRepository(self.con)
        self.quarantine = QuarantineRepository(self.con)
        self.parties = PartyRepository(self.con)
        self.candidates = CandidateRepository(self.con)
        self.matcher_versions = MatcherVersionRepository(self.con)
        self.links = LinkRepository(self.con)
        self.abstentions = AbstentionRepository(self.con)
        self.labels = LabelRepository(self.con)
        if not read_only:
            self.init_schema()  # idempotent; a fresh store is always usable

    def init_schema(self) -> None:
        self._migrate_candidate()
        self.con.execute(SCHEMA_SQL)

    def _migrate_candidate(self) -> None:
        """Older files had candidate without a PK; recreate it (copying rows, deduped) if so."""
        has_table = self.con.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE table_name = 'candidate'"
        ).fetchall()[0][0]
        if not has_table:
            return
        has_pk = self.con.execute(
            "SELECT count(*) FROM duckdb_constraints() "
            "WHERE table_name = 'candidate' AND constraint_type = 'PRIMARY KEY'"
        ).fetchall()[0][0]
        if has_pk:
            return
        self.con.execute("ALTER TABLE candidate RENAME TO candidate_old")
        self.con.execute(SCHEMA_SQL)
        self.con.execute(
            """INSERT INTO candidate SELECT run_id, source, record_id, canonical_key, coalesce(path, ''),
                      features, score FROM candidate_old
               QUALIFY row_number() OVER (PARTITION BY run_id, source, record_id, canonical_key,
                                          coalesce(path, '')) = 1"""
        )
        self.con.execute("DROP TABLE candidate_old")

    def execute(self, sql: str, params: list[Any] | None = None) -> duckdb.DuckDBPyConnection:
        return self.con.execute(sql, params or [])

    def query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        return _rows(self.con.execute(sql, params or []))

    def table_counts(self) -> dict[str, int]:
        return {t: self.con.execute(f"SELECT count(*) FROM {t}").fetchall()[0][0] for t in TABLES}

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> DuckDBStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
