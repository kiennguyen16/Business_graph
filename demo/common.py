"""Shared plumbing for the demo: paths, matcher version, licence events, read-only matcher,
SPARQL endpoint selection and the Backend object the Streamlit pages use.

Nothing here writes to a DuckDB file. The app opens its database read-only; the derived
`licence_event` table (not in the eval snapshot) is put in DuckDB's TEMP catalog.
"""

from __future__ import annotations

import contextlib
import gzip
import json
import os
import sys
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

DEMO_DIR = Path(__file__).resolve().parent
BUNDLE_DIR = Path(os.environ.get("BIZGRAPH_BUNDLE_DIR", DEMO_DIR / "bundle"))
BUNDLE_DB = BUNDLE_DIR / "demo.duckdb"
DEFAULT_BUNDLE_URL = (
    "https://github.com/kiennguyen16/Business_graph/releases/download/demo-bundle-v4/demo_bundle.tar.gz"
)
BUNDLE_RDF = BUNDLE_DIR / "rdf"
SNAPSHOT_DB = REPO / "data" / os.environ.get("BIZGRAPH_SNAPSHOT", "snap_v3_demo.duckdb")
DEFAULT_MATCHER_VERSION = "m-b5e50f74-d37e44c6"  # v4
MEMORY_LIMIT = os.environ.get("BIZGRAPH_MEMORY_LIMIT", "2GB")

# Example inputs shared by the app and the precompute step.
CHAIN_EXAMPLES = {
    "CSCAL Nominees (Citigroup group) LEI 5493002Q4UIXQGSO4I28": "5493002Q4UIXQGSO4I28",
    "Macquarie Energy Japan (3 hops to Macquarie Group) LEI 3538003NQP2Z8ZI0KA94": "3538003NQP2Z8ZI0KA94",
    "Macquarie Bank Limited ABN 46008583542": "46008583542",
    "Commonwealth Bank of Australia ABN 48123123124": "48123123124",
}
ENTITY_EXAMPLES = ("urn:abn:48123123124", "urn:abn:48882817243", "urn:abn:94122169279", "urn:abn:46008583542",
                   "urn:abn:88004325080", "urn:abn:52001355906", "urn:abn:30123717680")
HOPS_EXAMPLES = (("urn:abn:94122169279", 2),)
PRECOMPUTED = BUNDLE_DIR / "precomputed.pkl"

TIER23_SOURCES = ("asic_afsl", "asic_credit", "asic_banned_org", "asic_liquidator", "accc_notice")
# Source graphs the services read. abr / asic_company graphs (millions of records, no facts)
# are not needed by any traversal: their records are shown from DuckDB.
GRAPH_SOURCES = ("asic_afsl", "asic_credit", "asic_banned_org", "asic_liquidator", "accc_notice",
                 "gleif_l1", "gleif_l2")


def ensure_bundle() -> str | None:
    """Fetch the demo bundle when it is not on disk and BIZGRAPH_BUNDLE_URL points at a tarball of
    it (`tar -czf bizgraph_demo_bundle.tar.gz -C demo bundle`, published e.g. as a release asset).
    Used on hosts that build from git, where demo/bundle/ is not committed."""
    if BUNDLE_DB.exists():
        return None
    url = os.environ.get("BIZGRAPH_BUNDLE_URL")
    if not url:
        try:  # Streamlit Cloud secrets
            import streamlit as st

            url = st.secrets.get("BIZGRAPH_BUNDLE_URL")
        except Exception:
            url = None
    if not url and not SNAPSHOT_DB.exists():
        url = DEFAULT_BUNDLE_URL  # public release asset; lets a fresh clone run with no setup
    if not url:
        return None
    import tarfile
    import tempfile
    import urllib.request

    BUNDLE_DIR.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "bundle.tar.gz"
        urllib.request.urlretrieve(url, archive)  # noqa: S310 (operator-supplied URL)
        with tarfile.open(archive) as tf:
            tf.extractall(BUNDLE_DIR.parent, filter="data")
    if not BUNDLE_DB.exists():
        raise RuntimeError(f"{url} did not contain bundle/demo.duckdb")
    return f"downloaded from {url}"


def db_path() -> Path:
    env = os.environ.get("BIZGRAPH_DB")
    if env:
        return Path(env)
    return BUNDLE_DB if BUNDLE_DB.exists() else SNAPSHOT_DB


def connect_ro(path: Path | str):
    """DuckDBStore opened read-only with the memory cap."""
    from bizgraph.store.duckdb_store import DuckDBStore

    store = DuckDBStore(str(path), read_only=True)
    store.con.execute(f"SET memory_limit='{MEMORY_LIMIT}'")
    store.con.execute(f"SET threads={int(os.environ.get('BIZGRAPH_THREADS', '2'))}")
    store.con.execute("SET preserve_insertion_order=false")
    if os.environ.get("BIZGRAPH_TEMP_DIR"):
        store.con.execute(f"SET temp_directory='{os.environ['BIZGRAPH_TEMP_DIR']}'")
    return store


def matcher_version(con: Any) -> str:
    """BIZGRAPH_MATCHER_VERSION, else v3 (DEFAULT_MATCHER_VERSION) when the store has it, else the
    latest full-run 'm-' version (not a strip-identifier experiment, not a redecide)."""
    env = os.environ.get("BIZGRAPH_MATCHER_VERSION")
    if env:
        return env
    if con.execute("SELECT count(*) FROM matcher_version WHERE version = ?", [DEFAULT_MATCHER_VERSION]).fetchall()[0][0]:
        return DEFAULT_MATCHER_VERSION
    rows = con.execute(
        """SELECT version FROM matcher_version
           WHERE version LIKE 'm-%' AND coalesce(json_extract(policy, '$.config.strip_identifiers')::BOOLEAN, false) = false
           ORDER BY created_at DESC"""
    ).fetchall()
    return rows[0][0] if rows else DEFAULT_MATCHER_VERSION


def stored_policy(con: Any, version: str):
    from bizgraph.resolution import ThresholdPolicy

    row = con.execute("SELECT policy FROM matcher_version WHERE version = ?", [version]).fetchall()
    if not row:
        return ThresholdPolicy(), {}
    blob = row[0][0]
    d = json.loads(blob) if isinstance(blob, str) else blob
    return ThresholdPolicy.from_dict(d.get("policy", {})), d.get("config", {})


# --------------------------------------------------------------------------- licence events

def licence_history_files() -> list[Path]:
    files = sorted((REPO / "data/raw/asic_afsl/history").glob("*.csv"))
    files += sorted((REPO / "data/raw/asic_credit/history").glob("*.csv"))
    cur = REPO / "data/raw/asic_credit/credit_lic_202611.csv"
    if cur.exists():
        files.append(cur)
    return files


def compute_licence_events():
    from bizgraph.pipeline.licence_history import events_from_files

    return events_from_files(licence_history_files())


def has_table(con: Any, name: str) -> bool:
    return bool(con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = ?", [name]).fetchall()[0][0])


def ensure_licence_event(con: Any, parquet: Path | None = None) -> str:
    """Make `licence_event` visible on a read-only connection (TEMP table). Source: the table in
    the file, else the bundle parquet, else recomputed from the archived register files."""
    if has_table(con, "licence_event"):
        return "table in database"
    from bizgraph.pipeline import licence_history as lh

    ddl = lh.LICENCE_EVENT_DDL.replace("CREATE TABLE IF NOT EXISTS", "CREATE TEMP TABLE IF NOT EXISTS")
    con.execute(ddl)
    parquet = parquet or (BUNDLE_DIR / "licence_event.parquet")
    if parquet.exists():
        cols = ", ".join(lh._COLUMNS)
        con.execute(f"INSERT INTO temp.licence_event ({cols}) SELECT {cols} FROM read_parquet(?)", [str(parquet)])
        return f"TEMP table from {parquet.name}"
    events = compute_licence_events()
    ph = ", ".join("?" for _ in lh._COLUMNS)
    con.executemany(f"INSERT INTO temp.licence_event ({', '.join(lh._COLUMNS)}) VALUES ({ph})",
                    [e.row() for e in events])
    return "TEMP table recomputed from data/raw history files"


# --------------------------------------------------------------------------- matcher

@contextlib.contextmanager
def _read_only_name_index():
    """Matcher.__init__ calls NameIndex.ensure(), which issues CREATE statements. On a read-only
    file the index must already be current: check the fingerprint, never write."""
    import bizgraph.resolution.matcher as mm
    from bizgraph.resolution.candidates import NameIndex

    class ReadOnlyNameIndex(NameIndex):
        def ensure(self, force: bool = False) -> dict[str, Any]:
            fp = self._fingerprint()
            cur = self.con.execute("SELECT fingerprint FROM res_index_meta").fetchall()
            return {"built": False, "fingerprint": fp, "current": bool(cur and cur[0][0] == fp),
                    "read_only": True}

    orig = mm.NameIndex
    mm.NameIndex = ReadOnlyNameIndex
    try:
        yield
    finally:
        mm.NameIndex = orig


def index_is_current(con: Any) -> bool:
    from bizgraph.resolution.candidates import NameIndex

    if not has_table(con, "res_index_meta"):
        return False
    cur = con.execute("SELECT fingerprint FROM res_index_meta").fetchall()
    return bool(cur and cur[0][0] == NameIndex(con)._fingerprint())


def overlay_connection(path: Path | str):
    """In-memory DuckDB whose main schema has a view over every table of the read-only file
    except the derived res_* index tables, so `NameIndex.ensure` can build a fresh index for
    the code in src/ without writing the file."""
    import duckdb

    con = duckdb.connect()
    con.execute(f"SET memory_limit='{MEMORY_LIMIT}'")
    con.execute(f"SET threads={int(os.environ.get('BIZGRAPH_THREADS', '2'))}")
    con.execute(f"ATTACH '{Path(path).as_posix()}' AS snap (READ_ONLY)")
    for (t,) in con.execute("SELECT table_name FROM duckdb_tables() WHERE database_name = 'snap'").fetchall():
        if not t.startswith("res_"):
            con.execute(f'CREATE VIEW main."{t}" AS SELECT * FROM snap.main."{t}"')
    # an empty meta table in memory, so the index is (re)built here, never looked up in the file
    con.execute("CREATE TABLE main.res_index_meta (fingerprint VARCHAR, built_at TIMESTAMP, build_s DOUBLE)")
    return con


def make_matcher(store: Any, policy: Any, embedder: Any = None) -> tuple[Any, str]:
    """(Matcher, how its index was obtained). Uses the file's index when it is current for the
    code in src/; otherwise rebuilds it in an in-memory overlay (the file is never written)."""
    import types

    from bizgraph.resolution import Matcher

    if index_is_current(store.con):
        with _read_only_name_index():
            return Matcher(store, policy=policy, embedder=embedder), "stored index (current for this code)"
    t0 = time.perf_counter()
    ov = types.SimpleNamespace(con=overlay_connection(store.path))
    m = Matcher(ov, policy=policy, embedder=embedder)  # NameIndex.ensure builds into memory
    return m, (f"index rebuilt in memory in {time.perf_counter() - t0:.1f} s: the stored one predates "
               f"the resolution code in src/")


# --------------------------------------------------------------------------- SPARQL endpoint

def load_local_endpoint(rdf_dir: Path):
    """LocalEndpoint (rdflib) over the bundle's graphs listed in rdf/manifest.json."""
    from bizgraph.services.endpoint import LocalEndpoint

    ep = LocalEndpoint()
    manifest = json.loads((rdf_dir / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["graphs"]:
        path = rdf_dir / entry["file"]
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as fh:
            ep.add_ntriples(entry["iri"], fh.read())
    return ep, manifest


def fuseki_endpoint(url: str):
    from bizgraph.config import Settings
    from bizgraph.store.fuseki import FusekiClient

    import dataclasses

    settings = dataclasses.replace(Settings(), fuseki_url=url.rstrip("/"))
    return FusekiClient(settings)


# --------------------------------------------------------------------------- backend

class Backend:
    """Everything the pages need, built once per process."""

    def __init__(self) -> None:
        timings: dict[str, float] = {}
        t0 = time.perf_counter()
        self.bundle_origin = ensure_bundle()
        self.db_path = db_path()
        self.is_bundle = self.db_path.resolve() == BUNDLE_DB.resolve() if BUNDLE_DB.exists() else False
        self.store = connect_ro(self.db_path)
        self.con = self.store.con
        self._lock = threading.RLock()
        timings["open_duckdb"] = time.perf_counter() - t0

        t = time.perf_counter()
        self.licence_event_origin = ensure_licence_event(self.con)
        timings["licence_event"] = time.perf_counter() - t

        self.matcher_version = matcher_version(self.con)
        self.policy, self.stored_config = stored_policy(self.con, self.matcher_version)
        t = time.perf_counter()
        embedder = None
        if os.environ.get("BIZGRAPH_EMBEDDER", "").lower() == "auto":
            from bizgraph.resolution import Embedder
            embedder = Embedder.load()
        self.matcher, self.index_origin = make_matcher(self.store, self.policy, embedder)
        timings["matcher_init"] = time.perf_counter() - t

        t = time.perf_counter()
        self.fuseki_url = os.environ.get("FUSEKI_URL")
        self.rdf_manifest: dict[str, Any] = {}
        if self.fuseki_url:
            self.endpoint = fuseki_endpoint(self.fuseki_url)
            self.endpoint_desc = f"Fuseki at {self.fuseki_url}"
        else:
            rdf_dir = Path(os.environ.get("BIZGRAPH_RDF_DIR", BUNDLE_RDF))
            self.endpoint = None
            self._rdf_dir = rdf_dir
            self.rdf_manifest = json.loads((rdf_dir / "manifest.json").read_text(encoding="utf-8"))
            n = sum(g.get("triples", 0) for g in self.rdf_manifest.get("graphs", []))
            self.endpoint_desc = f"lazy rdflib LocalEndpoint over {rdf_dir.name}/ ({n:,} triples)"
        timings["sparql_endpoint"] = time.perf_counter() - t

        from bizgraph.services.projection import ProjectionService
        from bizgraph.services.traversal import TraversalService

        t = time.perf_counter()
        self._TraversalService = TraversalService
        self._ProjectionService = ProjectionService
        self._traversal = None
        self._projection = None
        timings["services"] = time.perf_counter() - t
        # Heavy traversal results computed at bundle build time against the same graphs served by
        # Fuseki; used only when this process has no Fuseki (rdflib is far slower on them).
        self.precomputed: dict[tuple, Any] = {}
        if not self.fuseki_url and self.is_bundle and PRECOMPUTED.exists():
            import pickle
            with open(PRECOMPUTED, "rb") as fh:
                self.precomputed = pickle.load(fh)
        timings["total"] = time.perf_counter() - t0
        self.startup_timings = {k: round(v, 2) for k, v in timings.items()}
        self.live_version = self.matcher.version.version

    def _ensure_endpoint(self):
        if self.endpoint is None:
            self.endpoint, self.rdf_manifest = load_local_endpoint(self._rdf_dir)
        return self.endpoint

    @property
    def traversal(self):
        if self._traversal is None:
            self._traversal = self._TraversalService(self._ensure_endpoint(), self.store, matcher_version=self.matcher_version)
        return self._traversal

    @property
    def projection(self):
        if self._projection is None:
            self._projection = self._ProjectionService(self._ensure_endpoint(), self.store, matcher_version=self.matcher_version)
        return self._projection

    # ------------------------------------------------------------------ helpers

    def q(self, sql: str, params: Any = None):
        # The main connection, not a cursor: a cursor does not see the TEMP licence_event table.
        with self._lock:
            return self.con.execute(sql, params or []).df()

    def party_iri(self, key: str) -> str:
        from bizgraph.rdf.vocab import IriFactory

        row = self.con.execute("SELECT abn, acn, lei FROM party_canonical WHERE canonical_key = ?", [key]).fetchall()
        if not row:
            return key
        return IriFactory.party(row[0][0], row[0][1], row[0][2], key) or key

    def key_for_iri(self, iri: str) -> str | None:
        """Graph party IRI -> canonical_key (they coincide for most parties)."""
        row = self.con.execute(
            """SELECT canonical_key FROM party_canonical WHERE canonical_key = ?
               UNION ALL SELECT canonical_key FROM party_canonical WHERE ? LIKE 'urn:abn:%' AND abn = substr(?, 9)
               UNION ALL SELECT canonical_key FROM party_canonical
                         WHERE ? LIKE 'urn:acn:%' AND abn IS NULL AND acn = substr(?, 9)
               LIMIT 1""", [iri, iri, iri, iri, iri]).fetchall()
        return row[0][0] if row else None


def today() -> date:
    return date.fromisoformat(os.environ["BIZGRAPH_AS_OF"]) if os.environ.get("BIZGRAPH_AS_OF") else date.today()
