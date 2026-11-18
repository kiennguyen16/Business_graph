"""Independent contract tests for the DuckDB store, derived from the spec.

Spec anchors:
- Requirement.md "Make the load idempotent ... Running it twice should not double anything".
- Requirement.md "A merge you cannot undo is a merge you should not have made" (source records never deleted).
- ARCHITECTURE.md 1.4 (PKs), 2.1 (file hash short-circuit, content hash diff), 3.4.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import duckdb
import pytest

from bizgraph.domain.models import Identifier, IdScheme, PartyType, SourceRecord
from bizgraph.sources.base import CsvSourceAdapter, RejectRecord
from bizgraph.store.duckdb_store import DuckDBStore

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable

D1 = date(2026, 1, 5)
D2 = date(2026, 1, 12)
D3 = date(2026, 1, 19)


@pytest.fixture()
def store(tmp_path: Path):
    s = DuckDBStore(tmp_path / "t.duckdb")
    s.init_schema()
    yield s
    s.close()


def rec(rid: str = "1", payload: dict | None = None, d: date = D1, source: str = "src", **kw) -> SourceRecord:
    return SourceRecord(
        source=source,
        record_id=rid,
        snapshot_date=d,
        payload=payload if payload is not None else {"name": f"N{rid}"},
        **kw,
    )


# ---------------------------------------------------------------- idempotency


def test_same_batch_twice_does_not_double(store: DuckDBStore) -> None:
    batch = [rec(str(i)) for i in range(50)]
    assert store.records.upsert(batch) == 50
    assert store.records.upsert(batch) == 0
    assert store.records.count() == 50


def test_same_record_twice_in_one_batch(store: DuckDBStore) -> None:
    r = rec("1")
    assert store.records.upsert([r, r, r]) == 1
    assert store.records.count() == 1


def test_changed_payload_keeps_old_version(store: DuckDBStore) -> None:
    store.records.upsert([rec("1", {"name": "Old"}, D1)])
    assert store.records.upsert([rec("1", {"name": "New"}, D2)]) == 1
    assert store.records.count() == 2  # never deleted
    all_versions = list(store.records.by_source("src", latest_only=False))
    assert [r.payload["name"] for r in all_versions] == ["Old", "New"]
    latest = list(store.records.by_source("src"))
    assert len(latest) == 1 and latest[0].payload["name"] == "New"
    assert store.records.get("src", "1").payload["name"] == "New"


def test_revert_to_old_payload_becomes_latest_again(store: DuckDBStore) -> None:
    store.records.upsert([rec("1", {"name": "A"}, D1)])
    store.records.upsert([rec("1", {"name": "B"}, D2)])
    assert store.records.upsert([rec("1", {"name": "A"}, D3)]) == 0
    assert store.records.count() == 2
    assert store.records.get("src", "1").payload["name"] == "A"
    latest = list(store.records.by_source("src"))
    assert [r.payload["name"] for r in latest] == ["A"]


def test_last_seen_bumped_and_first_seen_kept(store: DuckDBStore) -> None:
    store.records.upsert([rec("1", d=D1)])
    store.records.upsert([rec("1", d=D2)])
    row = store.query("SELECT first_seen_snapshot, last_seen_snapshot, snapshot_date FROM source_record")[0]
    assert row["first_seen_snapshot"] == D1
    assert row["last_seen_snapshot"] == D2


def test_backfill_older_snapshot_moves_first_seen(store: DuckDBStore) -> None:
    """Loading an older snapshot after a newer one: the record existed earlier, first_seen should say so."""
    store.records.upsert([rec("1", d=D2)])
    store.records.upsert([rec("1", d=D1)])
    row = store.query("SELECT first_seen_snapshot, last_seen_snapshot FROM source_record")[0]
    assert row["last_seen_snapshot"] == D2
    assert row["first_seen_snapshot"] == D1


def test_two_versions_same_snapshot_date_latest_is_deterministic(store: DuckDBStore) -> None:
    """A corrected file re-ingested with the same snapshot date: the later upsert should win."""
    store.records.upsert([rec("1", {"name": "first"}, D1)])
    store.records.upsert([rec("1", {"name": "second"}, D1)])
    got = {store.records.get("src", "1").payload["name"] for _ in range(5)}
    latest = [r.payload["name"] for r in store.records.by_source("src")]
    assert got == {"second"}, f"get() returned {got}"
    assert latest == ["second"], f"by_source() returned {latest}"


def test_same_record_two_payloads_in_one_batch(store: DuckDBStore) -> None:
    """Two different versions of one record_id inside a single batch both land; latest must be defined."""
    n = store.records.upsert([rec("1", {"name": "a"}, D1), rec("1", {"name": "b"}, D1)])
    assert n == 2
    assert len(list(store.records.by_source("src"))) == 1


def test_same_key_different_dates_in_one_batch_uses_max_date(store: DuckDBStore) -> None:
    store.records.upsert([rec("1", d=D1), rec("1", d=D3)])
    row = store.query("SELECT first_seen_snapshot, last_seen_snapshot FROM source_record")[0]
    assert row["last_seen_snapshot"] == D3, row


class _TinyCsv(CsvSourceAdapter):
    source_id = "tiny"
    tier = 2
    licence = "test"
    batch_size = 3

    def to_record(self, row, snapshot_date):
        if not row.get("id"):
            raise RejectRecord("missing_id")
        ids = (Identifier(IdScheme.ABN, row["abn"]),) if row.get("abn") else ()
        return SourceRecord(
            source=self.source_id,
            record_id=row["id"],
            snapshot_date=snapshot_date,
            payload=dict(row),
            name_raw=row["name"],
            name_norm=row["name"].lower(),
            party_type=PartyType.ORGANISATION,
            identifiers=ids,
        )


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["id", "name", "abn", "state"])
        w.writeheader()
        w.writerows(rows)


def test_adapter_run_twice_skips_second_snapshot(store: DuckDBStore, tmp_path: Path) -> None:
    f = tmp_path / "a.csv"
    rows = [{"id": str(i), "name": f"Co {i}", "abn": "", "state": "nsw"} for i in range(10)]
    rows.append({"id": "", "name": "bad", "abn": "", "state": ""})
    _write_csv(f, rows)
    a = _TinyCsv()
    s1 = a.run(f, D1, store)
    assert (s1.records_in, s1.records_new, s1.records_rejected) == (11, 10, 1)
    s2 = a.run(f, D2, store)
    assert s2.skipped_snapshot
    assert store.records.count() == 10
    assert len(store.snapshots.list("tiny")) == 1
    assert store.query("SELECT DISTINCT state FROM source_record") == [{"state": "NSW"}]


def test_adapter_changed_file_inserts_only_changed(store: DuckDBStore, tmp_path: Path) -> None:
    f1, f2 = tmp_path / "a.csv", tmp_path / "b.csv"
    rows = [{"id": str(i), "name": f"Co {i}", "abn": "", "state": "VIC"} for i in range(10)]
    _write_csv(f1, rows)
    rows[3]["name"] = "Renamed"
    _write_csv(f2, rows)
    a = _TinyCsv()
    a.run(f1, D1, store)
    s2 = a.run(f2, D2, store)
    assert (s2.records_new, s2.records_unchanged) == (1, 9)
    assert store.records.count() == 11
    assert len(store.snapshots.list("tiny")) == 2


def test_unchanged_file_new_week_does_not_advance_last_seen(store: DuckDBStore, tmp_path: Path) -> None:
    """Spec ambiguity probe: the file hash short-circuit means last_seen never advances when a weekly file is
    byte-identical. Documented behaviour, not a contract (records are still current)."""
    f = tmp_path / "a.csv"
    _write_csv(f, [{"id": "1", "name": "Co", "abn": "", "state": "VIC"}])
    a = _TinyCsv()
    a.run(f, D1, store)
    a.run(f, D2, store)
    row = store.query("SELECT last_seen_snapshot FROM source_record")[0]
    assert row["last_seen_snapshot"] == D1


# ---------------------------------------------------------------- round trip


def test_round_trip_fidelity(store: DuckDBStore) -> None:
    r = SourceRecord(
        source="src",
        record_id="X-1",
        snapshot_date=D2,
        payload={"name": "Café Pty Ltd", "nested": [1, [2, None], {"k": None}], "none": None, "n": 1.5, "b": True},
        name_raw="Café Pty Ltd",
        name_norm="cafe",
        party_type=PartyType.PERSON,
        identifiers=(Identifier(IdScheme.ACN, "000000019"), Identifier(IdScheme.ABN, "51824753556")),
    )
    store.records.upsert([r])
    assert store.records.get("src", "X-1") == r
    assert list(store.records.by_source("src")) == [r]
    got = store.records.get("src", "X-1")
    assert got.identifiers[0].scheme is IdScheme.ACN
    assert got.party_type is PartyType.PERSON
    assert got.content_hash == r.content_hash


def test_round_trip_long_and_unicode_names(store: DuckDBStore) -> None:
    long = "Ä" * 20_000 + " 株式会社 ​ Ltd 🦘"
    r = rec("1", {"name": long}, name_raw=long, name_norm=long.lower())
    store.records.upsert([r])
    assert store.records.get("src", "1") == r


def test_round_trip_none_names_and_empty_payload(store: DuckDBStore) -> None:
    r = rec("1", {})
    store.records.upsert([r])
    assert store.records.get("src", "1") == r


def test_round_trip_payload_with_date_value_is_lossy(store: DuckDBStore) -> None:
    """Documented: payload is stored as JSON (default=str), so a date comes back as its ISO string."""
    r = rec("1", {"reg": date(2020, 1, 1)})
    store.records.upsert([r])
    got = store.records.get("src", "1")
    assert got.payload == {"reg": "2020-01-01"}, f"got {got.payload!r}"


def test_round_trip_party_type_plain_string(store: DuckDBStore) -> None:
    r = rec("1", party_type="organisation")  # type: ignore[arg-type]
    store.records.upsert([r])
    assert store.records.get("src", "1").party_type is PartyType.ORGANISATION


def test_identifier_columns_projected(store: DuckDBStore) -> None:
    r = rec(
        "1",
        identifiers=(
            Identifier(IdScheme.ABN, "51824753556"),
            Identifier(IdScheme.LEI, "5493001KJTIIGC8Y1R12"),
            Identifier(IdScheme.ACL, "123"),
            Identifier(IdScheme.AFSL, "456"),
        ),
    )
    store.records.upsert([r])
    row = store.query("SELECT abn, acn, lei, licence_no FROM source_record")[0]
    # licence_no = first licence identifier in record order (design decision: ACL listed first wins)
    assert row == {"abn": "51824753556", "acn": None, "lei": "5493001KJTIIGC8Y1R12", "licence_no": "123"}


# ---------------------------------------------------------------- content hash


def test_content_hash_key_order_independent() -> None:
    a = rec("1", {"a": 1, "b": {"x": 1, "y": 2}})
    b = rec("1", {"b": {"y": 2, "x": 1}, "a": 1})
    assert a.content_hash == b.content_hash


def test_content_hash_stable_across_processes() -> None:
    code = (
        "from datetime import date;from bizgraph.domain.models import SourceRecord as S;"
        "print(S('s','1',date(2026,1,1),{'n':'Café','l':[1,None]}).content_hash)"
    )
    env = {**os.environ, "PYTHONHASHSEED": "random"}
    outs = {
        subprocess.run([PY, "-c", code], capture_output=True, text=True, env=env, check=True).stdout.strip()
        for _ in range(3)
    }
    assert len(outs) == 1
    assert outs == {rec("1", {"n": "Café", "l": [1, None]}).content_hash}


def test_content_hash_ignores_snapshot_date_and_names() -> None:
    a = rec("1", {"n": 1}, D1, name_norm="a")
    b = rec("1", {"n": 1}, D2, name_norm="b")
    assert a.content_hash == b.content_hash


def test_name_norm_change_with_same_payload_is_not_stored(store: DuckDBStore) -> None:
    """If the normaliser improves, re-ingesting the same payload keeps the stale name_norm (hash is payload-only)."""
    store.records.upsert([rec("1", {"n": "X"}, D1, name_norm="old norm")])
    store.records.upsert([rec("1", {"n": "X"}, D2, name_norm="new norm")])
    assert store.records.get("src", "1").name_norm == "new norm"


def test_content_hash_type_collisions() -> None:
    """Documented: the hash uses the stored JSON serialisation (default=str), so a date and its ISO
    string are the same assertion and hash identically."""
    assert rec("1", {"d": date(2020, 1, 1)}).content_hash == rec("1", {"d": "2020-01-01"}).content_hash


# ---------------------------------------------------------------- edge cases


def test_empty_batch(store: DuckDBStore) -> None:
    assert store.records.upsert([]) == 0
    assert list(store.records.by_source("src")) == []
    assert store.records.get("src", "nope") is None


def test_records_without_identifiers(store: DuckDBStore) -> None:
    store.records.upsert([rec("1")])
    row = store.query("SELECT identifiers, abn FROM source_record")[0]
    assert row == {"identifiers": None, "abn": None}
    assert store.records.get("src", "1").identifiers == ()


def test_two_sources_same_record_id(store: DuckDBStore) -> None:
    store.records.upsert([rec("1", {"n": "a"}, source="s1"), rec("1", {"n": "b"}, source="s2")])
    assert store.records.counts_by_source() == {"s1": 1, "s2": 1}
    assert store.records.get("s1", "1").payload == {"n": "a"}
    assert [r.payload for r in store.records.by_source("s2")] == [{"n": "b"}]


def test_init_schema_twice(store: DuckDBStore) -> None:
    store.records.upsert([rec("1")])
    store.init_schema()
    assert store.records.count() == 1


def test_upsert_inside_caller_transaction(store: DuckDBStore) -> None:
    """upsert issues its own BEGIN; inside a caller transaction it fails and its ROLLBACK discards caller work."""
    store.execute("BEGIN TRANSACTION")
    store.quarantine.add("src", "q1", "inv")
    try:
        store.records.upsert([rec("1")])
    except duckdb.Error:
        pass
    try:
        store.execute("COMMIT")
    except duckdb.Error:
        pass
    assert store.query("SELECT count(*) AS n FROM quarantine")[0]["n"] == 1, "caller's work silently rolled back"


def test_by_source_partial_iteration_then_write(store: DuckDBStore) -> None:
    store.records.upsert([rec(str(i)) for i in range(30)])
    it = store.records.by_source("src", batch_size=5)
    next(it)
    store.records.upsert([rec("new")])  # writer while a reader cursor is still open
    assert store.records.count() == 31


def test_read_only_open_while_writer_open_same_process(tmp_path: Path) -> None:
    """Documents behaviour: DuckDB refuses a second connection with different config in one process."""
    p = tmp_path / "rw.duckdb"
    w = DuckDBStore(p)
    w.init_schema()
    try:
        with pytest.raises(duckdb.Error):
            DuckDBStore(p, read_only=True)
    finally:
        w.close()


def test_read_only_open_while_writer_open_other_process(tmp_path: Path) -> None:
    """Documents behaviour: another process cannot open the file even read-only while a writer holds it."""
    p = tmp_path / "rw2.duckdb"
    w = DuckDBStore(p)
    w.init_schema()
    try:
        code = (
            "import sys;from bizgraph.store.duckdb_store import DuckDBStore as S\n"
            "try:\n S(sys.argv[1], read_only=True); print('OPENED')\n"
            "except Exception as e: print('LOCKED', type(e).__name__)"
        )
        out = subprocess.run([PY, "-c", code, str(p)], capture_output=True, text=True, check=True).stdout
        assert "LOCKED" in out
    finally:
        w.close()


# ---------------------------------------------------------------- scale


@pytest.mark.slow
def test_scale_100k(store: DuckDBStore, capsys) -> None:
    recs = [
        rec(
            str(i),
            {"name": f"Company {i} Pty Ltd", "state": "NSW", "abn": f"{i:011d}"},
            name_raw=f"Company {i} Pty Ltd",
            name_norm=f"company {i}",
            identifiers=(Identifier(IdScheme.ABN, f"{i:011d}"),),
        )
        for i in range(100_000)
    ]
    t0 = time.perf_counter()
    for k in range(0, len(recs), 20_000):
        store.records.upsert(recs[k : k + 20_000])
    t1 = time.perf_counter()
    new = sum(store.records.upsert(recs[k : k + 20_000]) for k in range(0, len(recs), 20_000))
    t2 = time.perf_counter()
    n = sum(1 for _ in store.records.by_source("src"))
    t3 = time.perf_counter()
    assert store.records.count() == 100_000 and new == 0 and n == 100_000
    with capsys.disabled():
        print(f"\n[scale] first load {t1 - t0:.2f}s, rerun {t2 - t1:.2f}s, stream back {t3 - t2:.2f}s")


# ---------------------------------------------------------------- other repositories


def test_snapshot_record_and_exists(store: DuckDBStore, tmp_path: Path) -> None:
    from bizgraph.sources.base import LoadStats

    f = tmp_path / "x.bin"
    f.write_bytes(b"abc" * 1000)
    h = store.snapshots.file_hash(f)
    assert not store.snapshots.exists("s", h)
    st = LoadStats("s", D1, records_in=3)
    st.rejection_reasons["bad"] += 2
    store.snapshots.record("s", D1, h, f, st)
    store.snapshots.record("s", D1, h, f, st)
    assert store.snapshots.exists("s", h)
    rows = store.snapshots.list("s")
    assert len(rows) == 1 and json.loads(rows[0]["rejection_reasons"]) == {"bad": 2}


def test_link_save_and_duplicate(store: DuckDBStore) -> None:
    L = store.links
    L.save("l1", "v1", "src", "1", "abn:1", "exact", 1.0, {"why": ["abn"]})
    L.save("l1", "v1", "src", "1", "abn:1", "exact", 1.0, {"why": ["abn"]})
    assert len(L.for_record("src", "1")) == 1
    assert L.for_party("abn:1")[0]["link_id"] == "l1"
    assert json.loads(L.by_version("v1")[0]["evidence"]) == {"why": ["abn"]}


def test_link_resave_preserves_created_at(store: DuckDBStore) -> None:
    store.links.save("l1", "v1", "src", "1", "abn:1", "exact", 1.0)
    c1 = store.links.for_record("src", "1")[0]["created_at"]
    time.sleep(0.05)
    store.links.save("l1", "v1", "src", "1", "abn:2", "fuzzy", 0.5)
    rows = store.links.for_record("src", "1")
    assert rows[0]["created_at"] == c1, "INSERT OR REPLACE rewrote history of an existing link"


def test_link_same_record_two_versions_both_kept(store: DuckDBStore) -> None:
    store.links.save("v1:src:1", "v1", "src", "1", "abn:1", "exact", 1.0)
    store.links.save("v2:src:1", "v2", "src", "1", "abn:2", "fuzzy", 0.8)
    assert len(store.links.for_record("src", "1")) == 2


def test_abstention_pk(store: DuckDBStore) -> None:
    A = store.abstentions
    A.save("v1", "src", "1", "low_margin", "abn:1", 0.5)
    A.save("v1", "src", "1", "no_candidate")
    rows = A.by_version("v1")
    assert len(rows) == 1 and rows[0]["reason"] == "no_candidate" and rows[0]["best_candidate"] is None
    A.save("v2", "src", "1", "x")
    assert len(A.by_version("v2")) == 1


def test_label_pk_and_null_match(store: DuckDBStore) -> None:
    L = store.labels
    L.save("s1", "src", "1", "abn:1", True, "me")
    L.save("s1", "src", "1", None, None, "me", "unsure")
    rows = L.by_sample("s1")
    assert len(rows) == 1 and rows[0]["is_match"] is None and rows[0]["notes"] == "unsure"
    assert len(L.all()) == 1


def test_candidates_save_and_read(store: DuckDBStore) -> None:
    C = store.candidates
    n = C.save_many(
        [
            {"run_id": "r1", "source": "src", "record_id": "1", "canonical_key": "a", "path": "fuzzy",
             "features": {"jw": 0.9, "tok": [1, 2]}, "score": 0.9},
            {"run_id": "r1", "source": "src", "record_id": "1", "canonical_key": "b", "path": "fuzzy",
             "features": None, "score": 0.4},
        ]
    )
    assert n == 2
    rows = C.for_record("src", "1")
    assert [r["canonical_key"] for r in rows] == ["a", "b"]
    assert json.loads(rows[0]["features"]) == {"jw": 0.9, "tok": [1, 2]}
    assert C.save_many([]) == 0


def test_candidates_duplicate_save_doubles(store: DuckDBStore) -> None:
    """No PK on candidate: re-running the same run_id appends duplicates (rerun is not idempotent)."""
    row = {"run_id": "r1", "source": "src", "record_id": "1", "canonical_key": "a", "features": {}, "score": 1}
    store.candidates.save_many([row])
    store.candidates.save_many([row])
    assert len(store.candidates.for_record("src", "1")) == 1


def test_candidates_all_null_optional_columns(store: DuckDBStore) -> None:
    n = store.candidates.save_many(
        [{"run_id": "r", "source": "s", "record_id": "1", "canonical_key": "k"} for _ in range(3)]
    )
    assert n == 3


def test_candidates_int_score_and_list_features(store: DuckDBStore) -> None:
    store.candidates.save_many(
        [{"run_id": "r", "source": "s", "record_id": "1", "canonical_key": "k", "features": [1, 2], "score": 1},
         {"run_id": "r", "source": "s", "record_id": "1", "canonical_key": "k2", "features": [3], "score": 0.5}]
    )
    rows = store.candidates.for_record("s", "1", run_id="r")
    assert [r["score"] for r in rows] == [1.0, 0.5]


def test_matcher_version_latest(store: DuckDBStore) -> None:
    M = store.matcher_versions
    M.save("v1", "h1", {"t": 0.9})
    time.sleep(0.01)
    M.save("v2", "h2", {"t": 0.8})
    assert M.latest()["version"] == "v2"
    assert json.loads(M.get("v1")["policy"]) == {"t": 0.9}
    assert M.get("nope") is None


def test_matcher_version_resave_keeps_identity(store: DuckDBStore) -> None:
    """Re-saving an existing version with a different code hash silently overwrites what produced old links."""
    store.matcher_versions.save("v1", "h1", {"t": 0.9})
    store.matcher_versions.save("v1", "h1", {"t": 0.9})  # identical resave is a no-op
    with pytest.raises(ValueError):
        store.matcher_versions.save("v1", "DIFFERENT", {"t": 0.1})
    assert store.matcher_versions.get("v1")["code_hash"] == "h1"


def test_quarantine_add_list(store: DuckDBStore) -> None:
    store.quarantine.add("s", "1", "acn_two_names", "x")
    store.quarantine.add("t", "2", "inv")
    assert len(store.quarantine.list()) == 2 and len(store.quarantine.list("s")) == 1


def test_table_counts_and_query(store: DuckDBStore) -> None:
    counts = store.table_counts()
    assert set(counts) >= {"source_record", "link", "label"} and all(v == 0 for v in counts.values())


# ---------------------------------------------------------------- CLI


def _cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "BIZGRAPH_DB": str(tmp_path / "cli.duckdb"),
        "BIZGRAPH_DATA_DIR": str(tmp_path / "data"),
        "FUSEKI_URL": "http://127.0.0.1:1",  # nothing listens
    }
    return subprocess.run([PY, "-m", "bizgraph.cli", *args], capture_output=True, text=True, env=env, cwd=tmp_path)


def test_cli_init_db_and_stats(tmp_path: Path) -> None:
    r = _cli(tmp_path, "init-db")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "cli.duckdb").exists()
    r = _cli(tmp_path, "stats")
    assert r.returncode == 0, r.stderr
    assert "source_record" in r.stdout


def test_cli_db_flag_overrides_env(tmp_path: Path) -> None:
    other = tmp_path / "other.duckdb"
    r = _cli(tmp_path, "--db", str(other), "init-db")
    assert r.returncode == 0 and other.exists()


def test_cli_stats_after_ingest_counts(tmp_path: Path) -> None:
    s = DuckDBStore(tmp_path / "cli.duckdb")
    s.init_schema()
    s.records.upsert([rec("1"), rec("2", source="other")])
    s.close()
    r = _cli(tmp_path, "stats")
    assert r.returncode == 0
    assert "other" in r.stdout and "src" in r.stdout


def test_cli_fuseki_ping_unreachable(tmp_path: Path) -> None:
    r = _cli(tmp_path, "fuseki-ping")
    assert r.returncode == 1
    assert "not reachable" in r.stderr


def test_cli_init_db_does_not_write_into_repo(tmp_path: Path) -> None:
    """init-db with every path overridden should not create dirs in the repo (outputs/ is not overridable)."""
    out = REPO / "outputs"
    existed = out.exists()
    _cli(tmp_path, "init-db")
    if not existed:
        created = out.exists()
        if created:
            try:
                out.rmdir()
            except OSError:
                pass
        assert not created, "init-db created <repo>/outputs despite BIZGRAPH_DATA_DIR override"
