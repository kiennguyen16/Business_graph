# Business_graph: AU/NZ market graph

An ontology, a resolved entity graph and an agent-callable lookup over Australian and New
Zealand business registers. DuckDB is the system of record; Apache Jena Fuseki (TDB2) holds a
derived, rebuildable RDF view; matching runs in DuckDB + Python with two named paths (exact
identifiers, names) and abstains rather than guess.

> Status: work in progress. Sections marked TODO are filled in as the pipeline finishes.

- Demo URL: TODO
- Write-up: [`WRITEUP.md`](WRITEUP.md) (TODO)
- Ontology: [`ontology/schema.ttl`](ontology/schema.ttl), [`ontology/shapes.ttl`](ontology/shapes.ttl), [`ontology/NOTES.md`](ontology/NOTES.md)
- Plan and design: [`PLAN.md`](PLAN.md), [`ARCHITECTURE.md`](ARCHITECTURE.md)

## Run it

### Prerequisites
- Python 3.11+ (developed on 3.12), Git Bash on Windows or any POSIX shell.
- Java 17+ for Jena/Fuseki. `tools/` (git-ignored) holds a portable JDK 21 and Jena/Fuseki 5.5.0;
  `scripts/_java.sh` finds them. A system Java 8 will not work.

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"   # .venv/bin on Linux/macOS
.venv/Scripts/python -m pytest -q                                          # unit + contract tests
```

### Fast path (under 10 minutes): the demo bundle
TODO: download / build the trimmed demo bundle and `streamlit run demo/app.py`.

### Full pipeline (about 45 minutes, about 2 GB download)
TODO: `scripts/run_pipeline.sh` with measured per-step timings. Steps:
1. Download sources into `data/raw/` (URLs in [`outputs/sources.md`](outputs/sources.md)).
2. `bizgraph ingest <source> <path>` per source (ABR uses `--workers N --tier2-allowlist`).
3. `bizgraph build-canonical`
4. Licence history (`src/bizgraph/pipeline/licence_history.py`)
5. `bizgraph match-all`
6. `scripts/fuseki.sh` then `bizgraph publish --all` and `bizgraph validate-shacl`

## Sources

| Source | Tier | Used | Why / notes |
|---|---|---|---|
| ABR bulk extract | 1 | Yes | Identity backbone (ABN, names, entity type, state). **Has no ANZSIC**, despite the brief. |
| ASIC company register | 1 | Yes | ACN, status, former names (one row per name). Foreign bodies carry ARBNs, not ACNs. |
| ASIC AFS licensee | 2 | Yes | 99.5% carry ABN or ACN. Current licences only: cancellations come from snapshot diffs. |
| ASIC credit licensee | 2 | Yes | 98.3% ABN or ACN. |
| ASIC banned and disqualified orgs | 2 | Yes | 15 rows, all with ACN; strict threshold. |
| ASIC liquidators | 2 | Yes | People; never linked on a name alone. Firms kept as unresolved counterparties. |
| GLEIF L1 + L2 | 2 | Yes | LEI, registration numbers, ownership; slice follows foreign parents to the real top. |
| ACCC infringement notices | 3 | Sample (20) | Register blocks automated clients; 20 latest notices collected via a browser, robots.txt respected. |
| TGA ARTG | 3 | No | Licence forbids commercial use without permission. |
| annualreports.com | 3 | No | No reuse licence; robots.txt disallows the PDFs. |
| Wikidata | any | No | Not worth the hour for this slice: TODO justify or use. |

Licence review with quotes: [`outputs/sources.md`](outputs/sources.md). Identifier coverage:
[`outputs/identifier_coverage.md`](outputs/identifier_coverage.md).

## Slice

ABR active ABNs in **WA and TAS** (1,023,265 entities), **plus** every ABR entity referenced by a
valid ABN or ACN in any Tier 2 source, in any state (about 52k; this keeps the brief's
Commonwealth Bank test case in the graph), plus 35 entities pulled in as evidence for ACN
conflicts. Each party records its `slice_reason`. ANZSIC slicing was not possible (see above).

## Known gaps

- `dirty_references.jsonl` (200 rows) was referenced by the brief but not supplied. TODO.
- AFSL history comes from Wayback captures with an 8-month gap (2026-02-24 to 2026-11-02), so most
  "cancelled in the last 3 months" dates are bounds, not days.
- ACCC is a 20-notice sample; the register shows no penalty amounts.
- TODO: anything else broken, named here rather than left for you to find.
