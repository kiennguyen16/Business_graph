# Demo

A plain Streamlit app over the real store, the real matcher and the published graph. Five pages:

| Page | What it shows | Code it calls |
|---|---|---|
| Resolve | Text box and six example buttons. Decision (resolved or abstained, with the reason), ranked candidates (name, canonical key, match type, score, path, eligibility, why not), and one evidence panel per candidate: scores, the full feature vector, the decision explanation, and the exact SQL each generator ran (`query_text`, literals inlined) | `Matcher.prepare` + `Matcher.match` (same code path as `Matcher.resolve`) |
| Entity | Click-through from any candidate. Identifiers, aliases, quarantine flag and reason, the source records behind the party (with source graph and snapshot), inbound links (which records the matcher linked here, with match type, confidence and explanation), abstentions that named it as best candidate, licences, bans, ACCC notices, parents and subsidiaries (capped, with "N more not shown"), licence history with honest end-date bounds | DuckDB + `TraversalService.entity_view` |
| Traversals | Ultimate-parent chain (CSCAL Nominees in the Citigroup group, Macquarie Energy Japan to Macquarie Group, Macquarie Bank, CBA) with status, cycle / ambiguity / truncation flags, every edge with its rule, and the GLEIF cross-check. `within_hops`. The graph-only question as tables: foreign-controlled licensees, licensed entities sharing a group with a flagged entity, licence concentration by group | `ultimate_parent`, `within_hops`, `group_exposure` |
| Abstentions | Every abstention of the demo matcher version by source and reason, with record name, best candidate, score and explanation, and the full stored evidence for one record. Includes the 13 ACCC abstentions and the 3 banned-organisation abstentions | DuckDB `abstention` |
| Projection | The named specs, including the brief's "ACCC notice AND AFSL cancelled in the last 3 months". The combined result, then each half on its own with its query text, and why the answer is 0 rows | `ProjectionService` |

The header line on every page says what is real and what is reduced.

## What is real, what is stubbed

* Real: DuckDB store (read-only), matcher decisions of the stored version (`m-1465a4ba-e5444596` by default,
  `BIZGRAPH_MATCHER_VERSION` to pick another), live `resolve` under that version's stored threshold policy,
  SPARQL over graphs exported by `RdfExporter`, licence events derived from the archived register files.
* Off by default: the semantic (embedding) path. The hosted app does not load the 0.7 GB model, so names
  are scored by the exact and fuzzy paths only. `BIZGRAPH_EMBEDDER=auto` turns it on where
  sentence-transformers is installed. The stored v2 links contain no NAME_SEMANTIC link, so the stored
  decisions shown are unaffected.
* Live code version: `resolve` runs the code in `src/`; if it has moved on since the stored run the header
  shows both version strings. When the stored resolution index (`res_*` tables) predates that code, the
  app rebuilds it in memory over read-only views of the file (about 10 s for the full store, under 1 s for
  the bundle; the sidebar says which happened). The file is never written.
* Reduced in the hosted bundle: a subset of parties (below), so a query for a name outside it finds fewer
  candidates than the full store. Corpus statistics (name uniqueness, token IDF, block sizes) are copied
  from the full index, so a name shared in the full store never looks unique in the bundle.
* Data limits stated in the app: ACCC notices are the 20-row register extract; a cancelled licence's end
  date is a bound (last snapshot that showed it, first snapshot without it), not a date; no person-level
  director data.
* The 6-hop Citigroup chain (CSCAL NOMINEES to CITIGROUP INC.) needs the transitive-closure GLEIF slice
  described in `outputs/identifier_coverage.md`. The eval snapshot holds the first-foreign-parent slice,
  so the walk stops at CITIBANK OVERSEAS INVESTMENT CORPORATION after 3 hops and the page shows GLEIF's
  own ultimate edge to CITIGROUP INC. as `disagree_off_chain`.

## Run it locally

Two modes, chosen by environment variables.

**A. Full store + your own Fuseki (fast, everything).** Uses `data/eval_snapshot_20261118.duckdb`
read-only.

```bash
# 1. export the published graphs from the snapshot (read-only) and bulk load a TDB2 store
python demo/export_graphs.py --db data/eval_snapshot_20261118.duckdb --out /tmp/bizgraph_nq --nq
TDB2_LOC=/tmp/bizgraph_tdb2 LOADER_XMX=3g bash scripts/bulk_load.sh /tmp/bizgraph_nq/*.nq   # ~4 min, 13.6M quads
# 2. serve it
FUSEKI_PORT=3096 FUSEKI_XMX=3g TDB2_LOC=/tmp/bizgraph_tdb2 bash scripts/fuseki.sh &
# 3. run the app
FUSEKI_URL=http://localhost:3096 BIZGRAPH_DB=data/eval_snapshot_20261118.duckdb streamlit run demo/app.py
```

The snapshot has no `licence_event` table; the app and the exporter put one in DuckDB's TEMP catalog
from `demo/bundle/licence_event.parquet` (or recompute it from `data/raw/asic_*/history`, about 30 s).
The exporter streams through cursors that cannot see a TEMP table, so the derived licence-history graph
is exported from the bundle, which holds the same events and all Tier 2 licence records.

**B. Demo bundle (what a free tier runs).**

```bash
python demo/build_demo_snapshot.py          # ~2 min, writes demo/bundle (about 100 MB)
# precompute the heavy traversals for the no-Java host (needs any Fuseki once, at build time):
FUSEKI_PORT=3096 TDB2_LOC=/tmp/bundle_tdb2 bash scripts/fuseki.sh &
python demo/load_fuseki.py --url http://localhost:3096      # 798k triples, ~15 to 30 s
python demo/precompute.py  --url http://localhost:3096      # ~5 s, writes demo/bundle/precomputed.pkl
# then either, with Fuseki (everything live):
FUSEKI_URL=http://localhost:3096 streamlit run demo/app.py
# or without Java (rdflib LocalEndpoint over demo/bundle/rdf):
streamlit run demo/app.py
```

Without Fuseki the graph queries run on rdflib, which evaluates `VALUES` + `GRAPH ?g` patterns by scanning
(one entity-view query alone takes about 40 s). So in that mode the app uses the precomputed results for
the example chains, entity views, the within-hops example and `group_exposure` (and says so on the
page), computes other ownership chains live (about 20 s), and runs the graph half of any other entity
page only when asked (about a minute, without the same-identifier widening). The store half of every
page (identifiers, records, inbound links, abstentions, licence history) is always live.

Environment variables: `BIZGRAPH_DB` (store file; default the bundle if built, else the snapshot),
`BIZGRAPH_MATCHER_VERSION`, `FUSEKI_URL`, `BIZGRAPH_RDF_DIR`, `BIZGRAPH_MEMORY_LIMIT` (default 2GB),
`BIZGRAPH_THREADS` (default 2), `BIZGRAPH_TEMP_DIR`, `BIZGRAPH_EMBEDDER=auto`, `BIZGRAPH_AS_OF`.

## The demo bundle (`demo/build_demo_snapshot.py`)

The full store is 3.2 GB and will not fit a free tier. The builder opens the snapshot read-only and writes
`demo/bundle/`: a trimmed DuckDB with the same schema, the licence events as parquet, and the published
graphs exported from the trimmed store (so graph and store agree) as gzipped N-Triples plus a manifest.

Parties kept: everything linked from a Tier 2/3 source and the best candidate of every Tier 2/3
abstention; the GLEIF ownership slice (every L1 record on an L2 edge, the parties it links to, parties
sharing its LEI / ABN / ACN); licence-event holders; every candidate the full matcher generates for the
example queries; quarantined parties; a seeded random sample of 5,000 organisations. Links and
abstentions: the demo version only, all Tier 2/3, GLEIF for the slice. `demo_full_counts` keeps the full
store's totals so the Abstentions page can show "bundle n / full n". The resolution indexes are rebuilt
by `NameIndex.ensure`, then `n_keys`, token document frequencies, block sizes and the person-name
vocabulary are taken from the full index. `build_info.json` records what was kept and why.

Measured build (this machine, 120 s): see `demo/bundle/build_info.json`. Result: 18,733 parties, 12,890 links,
2,490 abstentions, 55,616 source records, 2,519 licence events, 797,840 triples; 100 MB on disk
(DuckDB 92 MB, graphs 7.5 MB gzipped, precomputed results 0.2 MB). On the example queries the bundle
gives the same decisions, scores and candidate counts as the full store (checked for nine names).

`*.duckdb` is in `.gitignore`: to publish the bundle add it explicitly (`git add -f demo/bundle/demo.duckdb`,
or track `demo/bundle/**` with Git LFS).

## Hosting (not deployed: steps only)

**Hugging Face Spaces, Docker SDK (recommended).** Free CPU tier (2 vCPU, 16 GB RAM) runs Java, so the
same image serves the bundle through an embedded Fuseki and graph pages answer in well under a second.

1. Build the bundle (`python demo/build_demo_snapshot.py`).
2. Create a Space with SDK "Docker". In the Space repo put `Dockerfile`, `pyproject.toml`, `README.md`
   (with the Space header below), `src/`, `ontology/`, `demo/` (including `demo/bundle/`, tracked with
   Git LFS: `git lfs track "demo/bundle/**"`).
3. Space README front matter:
   ```yaml
   ---
   title: AU/NZ business graph
   sdk: docker
   app_port: 7860
   ---
   ```
4. Space variable `EMBEDDED_FUSEKI=1` (the entrypoint starts Fuseki inside the container and loads the
   bundle's graphs into it, 15 to 30 s on first start). Optional `FUSEKI_XMX=1g`. Every page is then live.

**Streamlit Community Cloud (no Java).** Main file `demo/app.py`; dependencies from
`demo/requirements.txt`; the bundle must be in the repository (the DuckDB file is 92 MB, under GitHub's
100 MB per-file limit). Graph queries then run in-process on rdflib (see mode B): about 35 s to start, peak memory about
1.6 GB, examples instant from the precomputed results, other graph views slow. Check the tier's current
memory limit before choosing it.

## Docker (fallback)

```bash
cp demo/docker/dockerignore .dockerignore     # keep data/ (10 GB) and tools/ out of the build context
python demo/build_demo_snapshot.py            # the image serves demo/bundle
docker compose up                             # Fuseki service + app; open http://localhost:7860
# or one container:
docker build -t bizgraph-demo . && docker run -p 7860:7860 -e EMBEDDED_FUSEKI=1 bizgraph-demo
# or, without a .dockerignore, send only the paths the image needs as the build context:
tar -c Dockerfile pyproject.toml README.md src ontology demo | docker build -t bizgraph-demo -
```

Not verified here: the Docker daemon was not running on the build machine, so the image build and
`docker compose up` are untested. The pieces they run (`load_fuseki.py`, the bundle, the app against a
Fuseki holding only the bundle) were tested outside Docker.

The image is python:3.12-slim + OpenJDK 17 + Fuseki 5.5.0 (downloaded from the Apache archive at build
time). The compose file runs Fuseki as its own service with a named volume; the app loads the bundle's
graphs into it on first start and skips the load when the volume already has them.

## Measured page timings

Wall clock per Streamlit run (`streamlit.testing.v1.AppTest`, one script run per action, a Windows laptop,
DuckDB memory_limit 2 GB, 2 threads). "Cold start" includes building the backend (store, matcher, endpoint).

| Action | Full snapshot + Fuseki (13.6M quads) | Bundle + Fuseki (HF Spaces setup) | Bundle + rdflib (no Java) |
|---|---|---|---|
| Cold start (first page) | 13.3 s (10.1 s of it the in-memory index rebuild) | 1.6 s | 33.9 s (rdflib parse) |
| Resolve, one example | 0.2 to 0.6 s | 0.2 s | 0.2 s |
| Entity page (CBA / Macquarie Group / Westpac) | 0.18 / 0.29 / 0.26 s | 0.15 / 0.26 / 0.18 s | 0.10 / 0.15 s (precomputed), Westpac store half 0.11 s, graph half on request ~45 s |
| Click-through Resolve to Entity | 0.41 s | 0.23 s | 0.18 s |
| Ultimate parent (CSCAL) | 0.81 s | 0.26 s | 0.05 s precomputed (20 s live) |
| within_hops(Macquarie Group, 2): 49 nodes | 0.61 s | 0.43 s | 0.06 s precomputed |
| group_exposure (3,118 members, 1,064 groups) | 5.7 s first run, cached after | 1.4 s | 0.06 s precomputed (did not finish in 20 min live) |
| Projection page (spec + both halves) | 2.9 s | 0.2 s | 0.5 s |
| Abstentions page | 0.12 s | 0.10 s | 0.08 s |

Results agree across the three modes: 121 foreign-controlled licensees, 2 licensed entities sharing a
group with a flagged entity, 2 ownership chains ending in CYCLE (left out of every group), 49 neighbours
of Macquarie Group at 2 hops, projection 0 rows (ACCC half 5 parties, AFSL-cancelled half 42, none in
common).
