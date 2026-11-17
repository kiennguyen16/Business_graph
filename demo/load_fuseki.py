"""Load the demo bundle's graphs into a running Fuseki (whole-graph PUT per graph).

    python demo/load_fuseki.py --url http://localhost:3030 [--rdf demo/bundle/rdf] [--force]

Waits for the server, skips the load when the dataset already holds the bundle's triple count
(a restarted container keeps its TDB2 volume), otherwise PUTs every graph in manifest.json.
Used by the Docker entrypoint; works against any Fuseki with a `bizgraph` dataset.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BUNDLE_RDF  # noqa: E402


def wait(url: str, timeout_s: float = 180.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            if requests.get(f"{url}/$/ping", timeout=5).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise SystemExit(f"Fuseki not reachable at {url} after {timeout_s:.0f} s")


def count(url: str, dataset: str) -> int:
    r = requests.post(f"{url}/{dataset}/query", data={"query": "SELECT (count(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } }"},
                      headers={"Accept": "application/sparql-results+json"}, timeout=120)
    r.raise_for_status()
    return int(r.json()["results"]["bindings"][0]["n"]["value"])


def load(url: str, rdf: Path, dataset: str = "bizgraph", force: bool = False) -> None:
    url = url.rstrip("/")
    wait(url)
    manifest = json.loads((rdf / "manifest.json").read_text(encoding="utf-8"))
    expected = sum(g["triples"] for g in manifest["graphs"])
    have = count(url, dataset)
    if have >= expected and not force:
        print(f"Fuseki already holds {have:,} triples (bundle {expected:,}); not reloading", flush=True)
        return
    t0 = time.time()
    for g in manifest["graphs"]:
        path = rdf / g["file"]
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rb") as fh:
            body = fh.read()
        r = requests.put(f"{url}/{dataset}/data", params={"graph": g["iri"]}, data=body,
                         headers={"Content-Type": "application/n-triples"}, timeout=600)
        r.raise_for_status()
        print(f"loaded {g['iri']} ({g['triples']:,} triples)", flush=True)
    print(f"loaded {expected:,} triples in {time.time() - t0:.1f} s; dataset now {count(url, dataset):,}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", required=True)
    ap.add_argument("--rdf", type=Path, default=BUNDLE_RDF)
    ap.add_argument("--dataset", default="bizgraph")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    load(a.url, a.rdf, a.dataset, a.force)


if __name__ == "__main__":
    main()
