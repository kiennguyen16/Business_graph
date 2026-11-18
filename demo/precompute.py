"""Precompute the heavy graph traversals for the example inputs, for hosts without Java.

    python demo/precompute.py --url http://localhost:3096

The URL must be a Fuseki holding exactly the bundle's graphs (`demo/load_fuseki.py` loads
them). Writes demo/bundle/precomputed.pkl: group_exposure, the example ownership chains,
entity views and the within-hops example. The app uses them only when it runs on the bundle
without FUSEKI_URL (rdflib), and says so on the page; with Fuseki everything is live.
"""

from __future__ import annotations

import argparse
import os
import pickle
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=None)
    a = ap.parse_args()
    if a.url:
        os.environ["FUSEKI_URL"] = a.url
    else:
        os.environ.pop("FUSEKI_URL", None)
    from common import (BUNDLE_DB, CHAIN_EXAMPLES, ENTITY_EXAMPLES, HOPS_EXAMPLES, PRECOMPUTED,  # noqa: E402
                        Backend)
    os.environ["BIZGRAPH_DB"] = str(BUNDLE_DB)
    b = Backend()
    out: dict[tuple, object] = {("built_at",): date.today().isoformat()}
    t0 = time.perf_counter()
    out[("group_exposure",)] = b.traversal.group_exposure()
    for start in CHAIN_EXAMPLES.values():
        out[("chain", start, 10)] = b.traversal.ultimate_parent(start, max_depth=10)
    for key in ENTITY_EXAMPLES:
        iri = b.party_iri(key)
        out[("entity", iri)] = b.traversal.entity_view(iri)
    for key, hops in HOPS_EXAMPLES:
        out[("hops", key, hops)] = b.traversal.within_hops(key, hops)
    with open(PRECOMPUTED, "wb") as fh:
        pickle.dump(out, fh)
    print(f"{len(out) - 1} results in {time.perf_counter() - t0:.1f} s -> {PRECOMPUTED} "
          f"({PRECOMPUTED.stat().st_size / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()
