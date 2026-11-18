# Demo

A plain Streamlit app over the real store, the v3 matcher and the published graph. Five pages:

| Page | What it shows | Code it calls |
|---|---|---|
| Resolve | Text box and six example buttons. The decision (resolved or abstained, with the reason), ranked candidates (name, canonical key, match type, score, path, eligibility, why not), and one evidence panel per candidate: a **gate table** (every arbiter rule in order: identifier, person vs organisation, jurisdiction, name-gate R5a to R5g, unique name, state, quarantine, each pass / FAIL with the reference and candidate values), any recorded **disagreement**, the scores, the full feature vector and the exact SQL each generator ran | `Matcher.prepare` + `Matcher.match` (the code path of `Matcher.resolve`) |
| Entity | Click-through from any candidate. Identifiers, aliases, quarantine flag and reason, the source records behind the party (with source graph and snapshot), inbound links (record, match type, confidence, explanation, disagreement), abstentions that named it as best candidate, licences, bans, ACCC notices, parents and subsidiaries (capped, "N more not shown"), licence history with honest end-date bounds | DuckDB + `TraversalService.entity_view` |
| Traversals | Ultimate-parent chains (CSCAL Nominees to Citigroup Inc. in 6 hops, Macquarie Energy Japan to Macquarie Group, Macquarie Bank, CBA) with status, cycle / ambiguity / truncation flags, every edge with the rule that chose it, and the GLEIF cross-check. `within_hops`. The graph-only question as tables: foreign-controlled licensees, licensed entities sharing a group with a flagged entity, licence concentration | `ultimate_parent`, `within_hops`, `group_exposure` |
| Abstentions | Every abstention of the demo matcher version by source and reason (with a glossary of reasons, JURISDICTION_MISMATCH included), record name, best candidate, score, explanation; the stored evidence for one record rendered as the same gate table | DuckDB `abstention` |
| Projection | The named specs, including the brief's "ACCC notice AND AFSL cancelled in the last 3 months": the combined result, each half on its own with its query text, and why the answer is 0 rows | `ProjectionService` |

The header on every page says what is real and what is reduced; the sidebar shows the store, the
matcher version, where `licence_event` came from, how the resolution index was obtained and the
start-up timings.

## What is real, what is stubbed

* Real: the DuckDB store (opened read-only), the stored decisions of matcher **v3**
  `m-94f4f6b2-d37e44c6` (the default; `BIZGRAPH_MATCHER_VERSION` picks another), live `resolve`
  under v3's stored threshold policy, SPARQL over graphs exported by `RdfExporter`, `licence_event`
  from the store.
* The semantic (embedding) path is ON in the hosted Docker demo. The image bakes the CPU
  `all-MiniLM-L6-v2` model and sets `BIZGRAPH_EMBEDDER=auto`; stored decisions are shown as v3 made them.
* Live code version: `resolve` runs the code in `src/`. If the stored resolution index predates that
  code, the app rebuilds the index in memory over read-only views of the file (the file is never
  written) and says so in the sidebar.
* Reduced in the hosted bundle: a subset of parties (below), so a query for a name outside it finds
  fewer candidates than the full store. Corpus statistics (name uniqueness, token IDF, block sizes,
  person vocabulary) are copied from the full index, and on the example queries the bundle gives the
  same decisions, scores and candidate counts as the full store.
* Data limits stated in the app: ACCC notices are the 20-row register extract; a cancelled licence's
  end date is a bound (last snapshot that showed it, first snapshot without it); no person-level
  director data, so "within 2 hops of a banned party" is 0 on real data.

## Run it locally

Store: `data/snap_v3_demo.duckdb` by default (`BIZGRAPH_SNAPSHOT` names another file under `data/`,
`BIZGRAPH_DB` any path). It is only ever opened read-only.

**A. Full v3 store + your own Fuseki (everything live).**

```bash
python demo/export_graphs.py --db data/snap_v3_demo.duckdb --out /tmp/bizgraph_nq --nq   # ~1 min
TDB2_LOC=/tmp/bizgraph_tdb2 LOADER_XMX=3g bash scripts/bulk_load.sh /tmp/bizgraph_nq/*.nq  # ~3 min, 13.6M quads
FUSEKI_PORT=3096 FUSEKI_XMX=3g TDB2_LOC=/tmp/bizgraph_tdb2 bash scripts/fuseki.sh &
FUSEKI_URL=http://localhost:3096 BIZGRAPH_DB=data/snap_v3_demo.duckdb streamlit run demo/app.py
```

**B. The demo bundle (what a free tier runs).**

```bash
python demo/build_demo_snapshot.py                     # ~100 s, writes demo/bundle (72 MB)
# precompute the heavy traversals for hosts without Java (any Fuseki, once, at build time):
FUSEKI_PORT=3096 TDB2_LOC=/tmp/bundle_tdb2 bash scripts/fuseki.sh &
python demo/load_fuseki.py --url http://localhost:3096  # 867k triples, ~20 s
python demo/precompute.py  --url http://localhost:3096  # ~5 s, writes demo/bundle/precomputed.pkl
# then, with Fuseki (everything live):
FUSEKI_URL=http://localhost:3096 streamlit run demo/app.py
# or without Java (in-process rdflib LocalEndpoint over demo/bundle/rdf):
streamlit run demo/app.py
```

Without Fuseki the graph queries run on rdflib, which evaluates `VALUES` + `GRAPH ?g` patterns by
scanning (one entity-view query alone takes about 40 s and `group_exposure` does not finish in 20
minutes). In that mode the app uses the precomputed results for the example chains, the example
entity views, the within-hops example and `group_exposure` (and says so on the page), computes
other ownership chains live (about 20 s), and runs the graph half of any other entity page only when
asked (about a minute, without the same-identifier widening). The store half of every page is
always live.

Environment variables: `BIZGRAPH_DB`, `BIZGRAPH_SNAPSHOT`, `BIZGRAPH_MATCHER_VERSION` (default v3),
`FUSEKI_URL`, `BIZGRAPH_BUNDLE_DIR`, `BIZGRAPH_BUNDLE_URL` (download the bundle tarball at start-up
when it is not on disk), `BIZGRAPH_RDF_DIR`, `BIZGRAPH_MEMORY_LIMIT` (default 2GB), `BIZGRAPH_THREADS`
(default 2), `BIZGRAPH_TEMP_DIR`, `BIZGRAPH_EMBEDDER=auto`, `BIZGRAPH_AS_OF`.

## The demo bundle (`demo/build_demo_snapshot.py`)

The full store is 4.8 GB and does not fit a free tier. The builder opens the v3 store read-only and
writes `demo/bundle/`: a trimmed DuckDB with the same schema, `licence_event` as parquet, the published
graphs exported from the trimmed store (so graph and store agree) as gzipped N-Triples with a
manifest, and `build_info.json` recording what was kept and why.

Parties kept (19,405): everything linked from a Tier 2/3 source and the best candidate of every Tier
2/3 abstention; the GLEIF ownership slice (every L1 record on an L2 edge, which with v3 includes the
foreign parents, the parties those records link to, parties sharing their LEI / ABN / ACN);
licence-event holders; every candidate the full matcher generates for the example queries; the
example entities; the best candidate of every GLEIF abstention refused by a gate
(JURISDICTION_MISMATCH, AMBIGUOUS, IDENTIFIER_CONFLICT, PARTY_TYPE_CONFLICT, QUARANTINED_TARGET);
quarantined parties; a seeded random sample of 5,000 organisations.

Links and abstentions (v3 only): all Tier 2/3; for GLEIF, every L1 record in the ownership slice,
every L1 record linked to a kept party, and every gate abstention, each with its source records. So
an entity page lists all of its linked records (checked against the full store for CBA, CSC,
Macquarie Group, Macquarie Bank, Macquarie International Finance, Westpac and the three Citigroup
parties: identical link counts), and the Citigroup (6 hops) and Macquarie chains walk to the same
tops as on the full graph.

| Bundle (v3) | |
|---|---|
| Rows | 19,405 parties, 33,587 identifiers, 30,574 aliases, 15,303 links, 2,653 abstentions, 72,473 source records, 2,532 licence events, 69 quarantine rows |
| Graphs | 867,389 triples |
| Size on disk | 72 MB (DuckDB 64 MB, graphs 8.3 MB gzipped, precomputed results 0.2 MB); 24 MB as a `.tar.gz` |
| Build | 96 s on a Windows laptop; precompute 5 s |

`demo/bundle/` is git-ignored. Publish it as a release asset or inside the Space (below), not in the
main repository:

```bash
tar -czf bizgraph_demo_bundle.tar.gz -C demo bundle     # on Git Bash for Windows add --force-local
```

## Hosting (not deployed: the steps)

**Hugging Face Spaces, Docker SDK (recommended).** The free CPU tier (2 vCPU, 16 GB RAM) runs Java,
so the image serves the bundle through an embedded Fuseki and every page is live.

1. Build the bundle and precompute (mode B above).
2. Create a Space with SDK "Docker".
3. Push to the Space repository: `Dockerfile`, `.dockerignore`, `pyproject.toml`, `README.md`,
   `src/`, `ontology/`, `demo/` including `demo/bundle/`. The Space repository is separate from the
   main one, so the bundle can live there; track it with LFS first:
   `git lfs install && git lfs track "demo/bundle/**"` (files over 10 MB must go through LFS).
4. Put this front matter at the top of the Space's `README.md`:
   ```yaml
   ---
   title: AU/NZ business graph
   sdk: docker
   app_port: 7860
   ---
   ```
5. In the Space settings add the variable `EMBEDDED_FUSEKI=1` (optional `FUSEKI_XMX=1g`). On start
   the entrypoint starts Fuseki inside the container, loads the bundle's graphs (about 20 s the first
   time), then starts Streamlit on port 7860.

**Streamlit Community Cloud (no Java).**

1. Publish the bundle tarball somewhere public (for example a GitHub release asset).
2. New app from the GitHub repository; main file `demo/app.py`. Dependencies come from
   `demo/requirements.txt`; Python 3.12.
3. In the app's secrets / environment set `BIZGRAPH_BUNDLE_URL` to the tarball URL: the app downloads
   and unpacks it on first start (24 MB).
4. Expect about 40 s to start and a peak of about 2.0 GB of memory (rdflib holds the graphs); check the
   tier's current memory limit. Example traversals come from the precomputed results; other graph
   views are slow (mode B).

See [STREAMLIT_CLOUD.md](STREAMLIT_CLOUD.md) for exact Streamlit Cloud setup. Docker Spaces are paid; use Streamlit Cloud or docker compose. See [HUGGINGFACE.md](HUGGINGFACE.md) for the Docker setup, bundle options, environment
variables, timings, and troubleshooting. The hosted Docker demo has the semantic path ON.

## Docker (fallback to hosting)

```bash
python demo/build_demo_snapshot.py && <precompute as in mode B>   # the image serves demo/bundle
docker compose up                                                # Fuseki service + app on http://localhost:7860
# or one container, Fuseki inside:
docker build -t bizgraph-demo . && docker run -p 7860:7860 -e EMBEDDED_FUSEKI=1 bizgraph-demo
```

The image is python:3.12-slim + OpenJDK 17 + Fuseki 5.5.0 (downloaded from the Apache archive at build
time); the repository's `.dockerignore` keeps `data/` and `tools/` out of the build context. The
compose file runs Fuseki as its own service with a named volume; the app loads the bundle's graphs
into it on first start and skips the load when the volume already has them.

Not verified here: the Docker daemon was not running on the build machine, so the image build and
`docker compose up` are untested. What they run (`load_fuseki.py`, the bundle, the app against a
Fuseki holding only the bundle, the bundle download) was tested outside Docker.

## Measured page timings (v3, 2026-11-18)

Wall clock per Streamlit run (`streamlit.testing.v1.AppTest`, one script run per action, a Windows laptop,
DuckDB memory_limit 2 GB, 2 threads). Every page ran without an exception in all three modes.

| Action | Full v3 + Fuseki (13.6M quads) | Bundle + Fuseki (HF Spaces setup) | Bundle + rdflib (no Java) |
|---|---|---|---|
| Cold start (first page, builds the backend) | 2.4 s | 3.7 s | 38 s (rdflib parse; peak 2.0 GB) |
| Resolve, one example | 0.3 to 0.8 s | 0.06 to 0.24 s | 0.06 to 0.38 s |
| Entity page (CBA / Macquarie Group / CSCAL / Westpac) | 0.30 / 0.28 / 0.20 / 0.27 s | 0.12 / 0.32 / 0.26 / 0.18 s | 0.12 / 0.13 / 0.12 s (precomputed); Westpac store half 0.26 s, graph half on request |
| Click-through Resolve to Entity | 0.50 s | 0.34 s | 0.25 s |
| Ultimate parent, CSCAL (6 hops) / Macquarie (3) | 0.44 / 0.32 s | 0.53 / 0.22 s | 0.07 / 0.06 s (precomputed; about 20 s live) |
| within_hops(Macquarie Group, 2): 49 nodes | 0.39 s | 0.79 s | 0.14 s (precomputed) |
| group_exposure (3,258 members, 1,023 groups) | 1.9 s first run, cached after | 1.8 s | 0.19 s (precomputed) |
| Projection page (spec + both halves) | 1.9 s | 0.24 s | 0.70 s |
| Abstentions page / one record's evidence | 0.12 to 0.41 s / 0.12 s | 0.08 to 0.18 s / 0.13 s | 0.06 to 0.12 s / 0.07 s |

The three modes return the same answers: CSCAL to Citigroup Inc. in 6 hops (GLEIF agrees), 128
foreign-controlled licensees (3 of them EQT, wrongly placed in GI by the GLEIF country field), 5
licensed entities sharing a group with a flagged entity (TP ICAP and Citigroup groups), 1 ownership
chain ending in CYCLE (left out of every group, see `outputs/graph_queries.md`), 49 neighbours of
Macquarie Group at 2 hops, and 0 projection rows (ACCC half 5 parties, AFSL-cancelled half 198, none
in common).
