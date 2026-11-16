"""Source adapter base classes.

`SourceAdapter.run()` is a template method: the pipeline (parse -> map ->
validate -> hash -> store, with rejection accounting) is fixed here, and a
subclass only implements `parse` and `to_record`. A new source is a new
subclass registered in the SourceRegistry; nothing else changes.
"""

from __future__ import annotations

import csv
import time
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from bizgraph.domain.models import SourceRecord
from bizgraph.normalise.names import NameNormaliser

if TYPE_CHECKING:
    from bizgraph.store.duckdb_store import DuckDBStore

RawRow = dict[str, Any]


class RejectRecord(Exception):
    """Raised by `to_record` when a row cannot become a SourceRecord. The message is the reason."""


@dataclass
class LoadStats:
    source: str
    snapshot_date: date
    records_in: int = 0
    records_new: int = 0
    records_unchanged: int = 0
    records_rejected: int = 0
    rejection_reasons: Counter = field(default_factory=Counter)
    wall_clock_s: float = 0.0
    skipped_snapshot: bool = False

    @property
    def top_rejection_reason(self) -> str:
        if not self.rejection_reasons:
            return ""
        reason, count = self.rejection_reasons.most_common(1)[0]
        return f"{reason} ({count})"


class SourceAdapter(ABC):
    source_id: ClassVar[str]
    tier: ClassVar[int]
    licence: ClassVar[str]  # e.g. "CC BY 3.0 AU"
    description: ClassVar[str] = ""

    batch_size: int = 50_000

    def __init__(self, normaliser: NameNormaliser | None = None) -> None:
        self.names = normaliser or NameNormaliser()

    @abstractmethod
    def parse(self, path: Path) -> Iterator[RawRow]:
        """Stream raw rows from the downloaded file. Must not load everything into memory."""

    @abstractmethod
    def to_record(self, row: RawRow, snapshot_date: date) -> SourceRecord:
        """Map one raw row to a SourceRecord, or raise RejectRecord(reason)."""

    def accept(self, record: SourceRecord) -> bool:
        """Slice filter hook (e.g. Tier 1 active-status + state). Default keeps everything."""
        return True

    def run(self, path: Path, snapshot_date: date, store: DuckDBStore) -> LoadStats:
        started = time.perf_counter()
        stats = LoadStats(self.source_id, snapshot_date)

        file_hash = store.snapshots.file_hash(path)
        if store.snapshots.exists(self.source_id, file_hash):
            stats.skipped_snapshot = True
            stats.wall_clock_s = time.perf_counter() - started
            return stats

        batch: list[SourceRecord] = []
        for row in self.parse(path):
            stats.records_in += 1
            try:
                record = self.to_record(row, snapshot_date)
            except RejectRecord as exc:
                stats.records_rejected += 1
                stats.rejection_reasons[str(exc)] += 1
                continue
            if not self.accept(record):
                stats.records_rejected += 1
                stats.rejection_reasons["outside_slice"] += 1
                continue
            batch.append(record)
            if len(batch) >= self.batch_size:
                self._flush(batch, store, stats)
                batch = []
        if batch:
            self._flush(batch, store, stats)

        stats.wall_clock_s = time.perf_counter() - started
        store.snapshots.record(self.source_id, snapshot_date, file_hash, path, stats)
        return stats

    def _flush(self, batch: list[SourceRecord], store: DuckDBStore, stats: LoadStats) -> None:
        new = store.records.upsert(batch, adapter_version=getattr(self, "adapter_version", None))
        stats.records_new += new
        stats.records_unchanged += len(batch) - new


class CsvSourceAdapter(SourceAdapter, ABC):
    """Base for the data.gov.au registers (CSV or TSV)."""

    delimiter: ClassVar[str] = ","
    encoding: ClassVar[str] = "utf-8-sig"

    def parse(self, path: Path) -> Iterator[RawRow]:
        with path.open(newline="", encoding=self.encoding, errors="replace") as fh:
            reader = csv.DictReader(fh, delimiter=self.delimiter)
            for row in reader:
                yield {(k or "").strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
