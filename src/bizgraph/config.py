"""Runtime settings, read from environment variables with local defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value) if value else default


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: _env_path("BIZGRAPH_DATA_DIR", REPO_ROOT / "data"))
    db_path: Path = field(
        default_factory=lambda: _env_path(
            "BIZGRAPH_DB", _env_path("BIZGRAPH_DATA_DIR", REPO_ROOT / "data") / "bizgraph.duckdb"
        )
    )
    fuseki_url: str = field(default_factory=lambda: os.environ.get("FUSEKI_URL", "http://localhost:3030"))
    fuseki_dataset: str = field(default_factory=lambda: os.environ.get("FUSEKI_DATASET", "bizgraph"))
    outputs_dir: Path = field(default_factory=lambda: REPO_ROOT / "outputs")
    ontology_dir: Path = field(default_factory=lambda: REPO_ROOT / "ontology")

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def rdf_dir(self) -> Path:
        return self.data_dir / "rdf"

    @property
    def sparql_query_url(self) -> str:
        return f"{self.fuseki_url}/{self.fuseki_dataset}/query"

    @property
    def sparql_update_url(self) -> str:
        return f"{self.fuseki_url}/{self.fuseki_dataset}/update"

    @property
    def graph_store_url(self) -> str:
        return f"{self.fuseki_url}/{self.fuseki_dataset}/data"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.raw_dir, self.rdf_dir, self.outputs_dir):
            d.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()
