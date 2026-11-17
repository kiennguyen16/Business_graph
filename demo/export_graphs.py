"""Export the published graphs the demo reads from a DuckDB file, opened read-only.

    python demo/export_graphs.py --db data/eval_snapshot_20261118.duckdb --out <dir> [--nq] [--gzip]

Graphs: ontology, one source graph per GRAPH_SOURCES at its latest snapshot, canonical, the
links graph of the demo matcher version, and the derived licence-history graph (from a TEMP
`licence_event` table when the file has none). Writes manifest.json (file, graph IRI, triples).
Use --nq for scripts/bulk_load.sh (N-Quads carry their graph), --gzip for the demo bundle.
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import GRAPH_SOURCES, connect_ro, ensure_licence_event, matcher_version  # noqa: E402


def export(db: Path, out: Path, nq: bool = False, gz: bool = False, version: str | None = None,
           licence_parquet: Path | None = None) -> dict:
    from bizgraph.rdf.exporter import NamedGraph, RdfExporter

    store = connect_ro(db)
    con = store.con
    origin = ensure_licence_event(con, licence_parquet)
    version = version or matcher_version(con)
    ex = RdfExporter(con)
    graphs = [NamedGraph.ontology()]
    graphs += [g for g in ex.source_graphs() if g.source in GRAPH_SOURCES]
    graphs += [NamedGraph.canonical(), NamedGraph.links(version)]
    derived_from = None
    if ex.has_licence_events():
        graphs.append(NamedGraph.licence_history())
        if origin.startswith("TEMP"):
            # The exporter streams through cursors, which do not see a connection's TEMP table.
            # The derived graph reads only licence_event and the Tier 2 licence records, which the
            # demo bundle holds in full, so it is exported from the bundle instead.
            from common import BUNDLE_DB
            if BUNDLE_DB.exists():
                derived_from = RdfExporter(connect_ro(BUNDLE_DB).con)
            else:
                graphs.pop()
                print("licence_event is TEMP and no demo bundle exists: derived graph skipped", flush=True)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"db": str(db), "matcher_version": version, "licence_event": origin, "graphs": []}
    for g in graphs:
        t0 = time.perf_counter()
        use = derived_from if (derived_from is not None and g.kind == "derived") else ex
        res = use.export(g, out, "nq" if nq else "nt")
        path = res.path
        if gz:
            gz_path = path.with_name(path.name + ".gz")
            with open(path, "rb") as src, gzip.open(gz_path, "wb", compresslevel=6) as dst:
                shutil.copyfileobj(src, dst)
            path.unlink()
            path = gz_path
        manifest["graphs"].append({"file": path.name, "iri": g.iri, "triples": res.triples,
                                   "bytes": path.stat().st_size, "export_s": round(time.perf_counter() - t0, 1)})
        print(f"{g.iri}: {res.triples:,} triples, {path.stat().st_size / 1e6:.1f} MB, "
              f"{time.perf_counter() - t0:.1f} s", flush=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    store.close()
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--nq", action="store_true")
    ap.add_argument("--gzip", action="store_true")
    ap.add_argument("--matcher-version")
    a = ap.parse_args()
    export(a.db, a.out, a.nq, a.gzip, a.matcher_version)


if __name__ == "__main__":
    main()
