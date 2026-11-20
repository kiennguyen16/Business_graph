# Business graph

AU/NZ business entity graph. DuckDB is the system of record and Jena TDB2 is a rebuildable RDF view. Final matcher: `m-b5e50f74-d37e44c6`.

Demo: https://kien-nguyen-graph.streamlit.app/ (Streamlit Community Cloud free tier sleeps; first load about 60 seconds). 

## Demo Video



https://github.com/user-attachments/assets/9a2d056b-9240-425e-9bc4-a2508310d6d4



## Run it

From the repository root, create and activate a Python 3.11+ virtual environment.

Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Windows Git Bash

```bash
python -m venv .venv
source .venv/Scripts/activate
```

Linux and macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Then install the project, fetch the 24 MB demo bundle, and run a lookup.

```bash
pip install -e ".[dev]"
bizgraph fetch-bundle
bizgraph resolve "Commonwealth Bank of Australia"
```

The lookup prints `RESOLVED: urn:abn:48123123124`. Try a refusal too:
`bizgraph resolve "Rio Tinto plc"` prints `ABSTAINED: JURISDICTION_MISMATCH` (a UK plc is not Rio Tinto Limited).

For optional semantic matching, install `pip install -e ".[semantic]"` before
starting the app. The first start with that extra downloads the embedding model
and takes about one minute.

```bash
streamlit run demo/app.py
```

Open [the demo](http://localhost:8501).

Run the health check in a second terminal. It should print `ok`. In Windows
PowerShell, use `curl.exe`.

```bash
curl -s http://localhost:8501/_stcore/health
```

Run the quick test suite from the activated environment. A clean checkout
had 403 passed and 21 skipped in about 1 minute 25 seconds. Tests that require
a local service or optional tools skip when those prerequisites are absent.

```bash
pytest -q -m "not slow"
```

Run the full review suite separately. A clean checkout had 446 passed and
79 skipped in about 2 minutes 20 seconds. With local raw data and tools,
allow about 3 to 4 minutes.

```bash
pytest -q tests --ignore=tests/independent/test_resolution_contract.py
```

## Full pipeline
Run `scripts/run_pipeline.sh`. Measured timings in [`outputs/performance.md`](outputs/performance.md): ABR 376.44 s, ASIC company 448.95 s, canonical build 135.08 s, match-all 211.25 s, export 93.74 s, TDB2 load 348.35 s.

## Sources and slice
ABR and ASIC company are the tier 1 backbone. Used tier 2 sources are ASIC AFS, credit, banned organisations, liquidators, and GLEIF L1/L2; ACCC is a 20-notice tier 3 sample. TGA and annualreports.com were skipped because commercial reuse is not permitted or licensed. Wikidata was not used; it was not worth the hour given the gates. The slice is active ABRs in WA and TAS (1,023,265), plus Tier 2/3 references and required GLEIF relationships.

## Final results
V4 has 59,577 links and 12,332 abstentions. On 463 labels it made 0 wrong links: 100% precision (95% CI 98.7 to 100) and 92.5% recall (285/308 in-graph records). The previous version (v3) had one wrong link (a reused former name); v4 removed it. The rehearsal sets were 100% precision with recall 79.8% (150/188) and 80.9% (152/188). The labels were made by an AI labeller; I hand-checked 50 of them against ABN Lookup, ASIC and GLEIF: all 37 checked links were correct, 2 of 13 abstentions should have linked (renamed companies), and my verdicts agreed with the labels on all 50 rows (`outputs/evaluation.md` N1a, `labels/hand_check_m-b5e50f74-d37e44c6.csv`).

## Outputs
[`links.jsonl`](outputs/links.jsonl), [`abstentions.jsonl`](outputs/abstentions.jsonl), [`evaluation.md`](outputs/evaluation.md), [`resolve_results.jsonl`](outputs/resolve_results.jsonl), [`load_report.csv`](outputs/load_report.csv), [`graph_queries.md`](outputs/graph_queries.md), [`performance.md`](outputs/performance.md), [`sources.md`](outputs/sources.md), [`identifier_coverage.md`](outputs/identifier_coverage.md), and [`rehearsal/REHEARSAL.md`](outputs/rehearsal/REHEARSAL.md).

## Known gaps
`dirty_references.jsonl` was not supplied, so `resolve_results.jsonl` is from my 200-row rehearsal set. AFSL history has an 8-month Wayback gap. ACCC is a 20-notice sample with no penalty amounts on the register. GLEIF foreign branches linked to the AU head company is a modelling choice. Recall on messy free text is about 80%.
