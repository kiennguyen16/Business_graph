from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from bizgraph.domain.models import Identifier, IdScheme, PartyType, SourceRecord
from bizgraph.sources.base import CsvSourceAdapter, RejectRecord
from bizgraph.store.duckdb_store import TABLES, DuckDBStore

D1 = date(2026, 11, 1)
D2 = date(2026, 11, 8)


@pytest.fixture
def store(tmp_path: Path) -> DuckDBStore:
    s = DuckDBStore(tmp_path / "t.duckdb")
    s.init_schema()
    yield s
    s.close()


def rec(i: int, snap: date = D1, name: str | None = None, state: str = "NSW") -> SourceRecord:
    name = name or f"Acme {i} Pty Ltd"
    return SourceRecord(
        source="test",
        record_id=f"r{i}",
        snapshot_date=snap,
        payload={"name": name, "state": state, "i": i},
        name_raw=name,
        name_norm=name.lower(),
        party_type=PartyType.ORGANISATION,
        identifiers=(
            Identifier(IdScheme.ABN, f"{i:011d}"),
            Identifier(IdScheme.ACN, f"{i:09d}"),
            Identifier(IdScheme.AFSL, str(100000 + i)),
        ),
    )


def test_schema_creates_all_tables(store: DuckDBStore) -> None:
    names = {r[0] for r in store.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    assert set(TABLES) <= names
    store.init_schema()  # idempotent
    assert all(n == 0 for n in store.table_counts().values())


def test_upsert_idempotent(store: DuckDBStore) -> None:
    batch = [rec(i) for i in range(100)]
    assert store.records.upsert(batch) == 100
    assert store.records.upsert(batch) == 0
    assert store.records.count() == 100
    assert store.records.count("test") == 100
    assert store.records.count("other") == 0


def test_upsert_dedupes_within_batch(store: DuckDBStore) -> None:
    assert store.records.upsert([rec(1), rec(1)]) == 1
    assert store.records.count() == 1


def test_identifier_columns_extracted(store: DuckDBStore) -> None:
    store.records.upsert([rec(7)])
    row = store.query("SELECT abn, acn, lei, licence_no, state, party_type FROM source_record")[0]
    assert row == {
        "abn": "00000000007",
        "acn": "000000007",
        "lei": None,
        "licence_no": "100007",
        "state": "NSW",
        "party_type": "organisation",
    }


def test_licence_no_is_first_licence_identifier(store: DuckDBStore) -> None:
    r = SourceRecord(
        source="credit", record_id="c1", snapshot_date=D1, payload={"n": 1},
        identifiers=(Identifier(IdScheme.ACL, "222"), Identifier(IdScheme.AFSL, "111")),
    )
    store.records.upsert([r])
    assert store.query("SELECT licence_no FROM source_record")[0]["licence_no"] == "222"


def test_fresh_store_is_usable_without_init_schema(tmp_path: Path) -> None:
    with DuckDBStore(tmp_path / "fresh.duckdb") as s:
        assert s.records.upsert([rec(1)]) == 1
        s.init_schema()  # still callable, idempotent
        assert s.records.count() == 1
    with DuckDBStore(tmp_path / "fresh.duckdb", read_only=True) as ro:
        assert ro.records.count() == 1


def test_unchanged_record_bumps_last_seen(store: DuckDBStore) -> None:
    store.records.upsert([rec(1, D1)])
    assert store.records.upsert([rec(1, D2)]) == 0
    row = store.query("SELECT first_seen_snapshot, last_seen_snapshot FROM source_record")[0]
    assert row["first_seen_snapshot"] == D1
    assert row["last_seen_snapshot"] == D2


def test_changed_payload_adds_new_row(store: DuckDBStore) -> None:
    store.records.upsert([rec(1, D1)])
    assert store.records.upsert([rec(1, D2, name="Acme Renamed Pty Ltd")]) == 1
    assert store.records.count() == 2
    latest = list(store.records.by_source("test"))
    assert len(latest) == 1 and latest[0].name_raw == "Acme Renamed Pty Ltd"
    assert len(list(store.records.by_source("test", latest_only=False))) == 2


def test_by_source_round_trip(store: DuckDBStore) -> None:
    originals = [rec(i) for i in range(5)]
    store.records.upsert(originals)
    back = sorted(store.records.by_source("test"), key=lambda r: r.record_id)
    assert back == sorted(originals, key=lambda r: r.record_id)
    assert back[0].content_hash == originals[0].content_hash
    assert store.records.get("test", "r3") == originals[3]


class _TinyAdapter(CsvSourceAdapter):
    source_id = "tiny"
    tier = 9
    licence = "test"

    def to_record(self, row, snapshot_date):
        if not row.get("name"):
            raise RejectRecord("missing_name")
        return SourceRecord(
            source=self.source_id,
            record_id=row["id"],
            snapshot_date=snapshot_date,
            payload=row,
            name_raw=row["name"],
            name_norm=row["name"].lower(),
        )


def test_snapshot_skip(store: DuckDBStore, tmp_path: Path) -> None:
    f = tmp_path / "tiny.csv"
    f.write_text("id,name\n1,Alpha\n2,Beta\n3,\n", encoding="utf-8")
    h = store.snapshots.file_hash(f)
    assert not store.snapshots.exists("tiny", h)

    s1 = _TinyAdapter().run(f, D1, store)
    assert (s1.records_in, s1.records_new, s1.records_rejected) == (3, 2, 1)
    assert store.snapshots.exists("tiny", h)
    assert store.snapshots.list("tiny")[0]["records_new"] == 2

    s2 = _TinyAdapter().run(f, D2, store)
    assert s2.skipped_snapshot and s2.records_in == 0
    assert store.records.count("tiny") == 2


def test_quarantine_and_thin_repos(store: DuckDBStore) -> None:
    store.quarantine.add("test", "r1", "acn_two_names", "ACN 1 under A and B")
    assert store.quarantine.list("test")[0]["invariant"] == "acn_two_names"

    store.matcher_versions.save("v1", "abc", {"accept": 0.9})
    assert store.matcher_versions.get("v1")["code_hash"] == "abc"

    store.candidates.save_many(
        [
            {"run_id": "run1", "source": "test", "record_id": "r1", "canonical_key": "k1",
             "path": "exact", "features": {"abn": 1}, "score": 0.99},
            {"run_id": "run1", "source": "test", "record_id": "r1", "canonical_key": "k2",
             "path": "fuzzy", "features": {"abn": 0}, "score": 0.4},
        ]
    )
    cands = store.candidates.for_record("test", "r1")
    assert [c["canonical_key"] for c in cands] == ["k1", "k2"]

    store.links.save("L1", "v1", "test", "r1", "k1", "exact_abn", 0.99, {"abn": "1"})
    store.links.save("L1", "v1", "test", "r1", "k1", "exact_abn", 0.98, {"abn": "1"})  # replace
    links = store.links.for_record("test", "r1")
    assert len(links) == 1 and links[0]["confidence"] == 0.98
    assert store.links.for_party("k1")[0]["link_id"] == "L1"

    store.abstentions.save("v1", "test", "r2", "low_margin", "k2", 0.6)
    assert store.abstentions.by_version("v1")[0]["reason"] == "low_margin"

    store.labels.save("s1", "test", "r1", "k1", True, "kien", "")
    assert store.labels.by_sample("s1")[0]["is_match"] is True
