# Business graph

AU/NZ business entity graph. DuckDB is the system of record and Jena TDB2 is a rebuildable RDF view. Final matcher: `m-b5e50f74-d37e44c6`.

Demo: https://kien-nguyen-graph.streamlit.app/ (Streamlit Community Cloud free tier sleeps; first load about 60 seconds). The two-minute narrated walkthrough is attached to the submission email and linked from the release, not in git.

## Fast path
```bash
pip install -e ".[dev]"
streamlit run demo/app.py
```
The app downloads the 24 MB demo bundle release automatically. `bizgraph resolve "<text>"` runs on the bundle. Tests use `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests --ignore=tests/independent/test_resolution_contract.py`.

## Full pipeline
Run `scripts/run_pipeline.sh`. Measured timings in [`outputs/performance.md`](outputs/performance.md): ABR 376.44 s, ASIC company 448.95 s, canonical build 135.08 s, match-all 211.25 s, export 93.74 s, TDB2 load 348.35 s.

## Sources and slice
ABR and ASIC company are the tier 1 backbone. Used tier 2 sources are ASIC AFS, credit, banned organisations, liquidators, and GLEIF L1/L2; ACCC is a 20-notice tier 3 sample. TGA and annualreports.com were skipped because commercial reuse is not permitted or licensed. Wikidata was not used; it was not worth the hour given the gates. The slice is active ABRs in WA and TAS (1,023,265), plus Tier 2/3 references and required GLEIF relationships.

## Final results
V4 has 59,577 links and 12,332 abstentions. On 463 labels it made 0 wrong links: 100% precision and 93.2% recall over 308 in-graph records. The rehearsal sets were 100% precision with recall 79.8% (150/188) and 80.9% (152/188).

## Outputs
[`links.jsonl`](outputs/links.jsonl), [`abstentions.jsonl`](outputs/abstentions.jsonl), [`evaluation.md`](outputs/evaluation.md), [`resolve_results.jsonl`](outputs/resolve_results.jsonl), [`load_report.csv`](outputs/load_report.csv), [`graph_queries.md`](outputs/graph_queries.md), [`performance.md`](outputs/performance.md), [`sources.md`](outputs/sources.md), [`identifier_coverage.md`](outputs/identifier_coverage.md), and [`rehearsal/REHEARSAL.md`](outputs/rehearsal/REHEARSAL.md).

## Known gaps
`dirty_references.jsonl` was not supplied, so `resolve_results.jsonl` is from our 200-row rehearsal set. AFSL history has an 8-month Wayback gap. ACCC is a 20-notice sample with no penalty amounts on the register. GLEIF foreign branches linked to the AU head company is a modelling choice. Recall on messy free text is about 80%. Docker on Hugging Face is paid, so the Docker image is the local fallback via `docker compose up`.
