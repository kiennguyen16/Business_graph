# Delivery Plan: AU/NZ Market Graph Case Study

Source: `Requirement.md`. Deadline: 7 days from receipt. API budget: under USD \$10.

## Stack

| Concern | Choice | Why |
|---|---|---|
| System of record: raw source records, staging, blocking, links, abstentions, labels, threshold sweeps, bulk projections | **DuckDB** (Parquet on disk) | Embedded, no Docker, fast on 1M+ rows; tabular work is most of the job |
| Knowledge graph: canonical entities, reified facts, provenance | **Apache Jena Fuseki 5.x on TDB2** (Java 17+) | Native OWL/SHACL, named graphs per source load, set semantics make reloads idempotent, active Apache project |
| Ontology | **OWL in Turtle** (`ontology/schema.ttl`) + **SHACL** (`ontology/shapes.ttl`) | The schema is the working model, not a side file; reuses FIBO, W3C Org, GLEIF, schema.org, PROV-O terms |
| Candidate retrieval | DuckDB FTS + rapidfuzz + local embeddings (sentence-transformers) | Fuzzy lookup is weak in SPARQL; keeps the semantic path cheap and local |
| Traversal logic | Python over SPARQL (bounded BFS, visited set, path returned) | SPARQL property paths cannot return the chain or bound depth |
| RDF generation | Python writing N-Triples / N-Quads directly from DuckDB queries | Faster than rdflib object graphs at ~20 to 40M triples |
| Demo | Streamlit (Community Cloud) + Fuseki on a free Render / Fly.io instance | Fallback: 2-minute recording + `docker compose up` |

### Division of responsibility

```
 sources ──► adapters ──► DuckDB (system of record) ──► N-Quads per named graph ──► Fuseki/TDB2
                              │   source records, staging,            │
                              │   blocking, links, labels             ├── SHACL validation report
                              │                                       │
                              └──────────► Python services ◄──────────┘
                                   resolve · projection · ultimate parent · caps
                                              │
                                          Streamlit demo
```

### Named graph layout (provenance, idempotency, reversibility)

| Graph IRI | Holds | Rebuilt when |
|---|---|---|
| `urn:graph:source:{source}:{snapshot_date}` | One graph per source snapshot: `SourceRecord` nodes and the facts they assert | That source reloads (HTTP PUT replaces the graph) |
| `urn:graph:canonical` | Canonical `Party` nodes and identifiers (ABN, ACN, LEI) | Tier 1 reload |
| `urn:graph:links:{matcher_version}` | `Link` nodes: source record → canonical party, with match type, confidence, evidence | Matcher or threshold changes; old versions kept side by side |
| `urn:graph:ontology` | `schema.ttl` | Schema change |

Principle carried through every FR: **source records are immutable and never deleted; canonical entities and links are derived, versioned views over them.** Links per matcher version is the mechanism for WRITEUP Q4 (recalibrate by re-thresholding stored scores, not re-matching the corpus).

---

## Functional requirements and tasks

### FR0. Foundations: environment, sources, licences, slice

| ID | Task | Depends on |
|---|---|---|
| T0.1 | Repo skeleton matching required layout (`ontology/ src/ demo/ outputs/ labels/`), Python env (duckdb, rapidfuzz, sentence-transformers, SPARQLWrapper, streamlit, pyshacl optional), Makefile/CLI entrypoints | none |
| T0.2 | Install Java 17+ and Apache Jena + Fuseki 5.x; create TDB2 dataset config (with union default graph); smoke-test SPARQL query and Graph Store PUT | T0.1 |
| T0.3 | Licence review per source (ABR, ASIC x5, GLEIF, ACCC, TGA ARTG, annualreports.com, Wikidata); record licence, URL, commercial-use verdict in `outputs/sources.md` | none |
| T0.4 | Download Tier 1: ABR bulk extract + ASIC company register | T0.1 |
| T0.5 | Download Tier 2: AFS licensee, credit licensee, banned/disqualified, liquidator, GLEIF L1 + L2 (AU/NZ filter) | T0.1 |
| T0.6 | Acquire Tier 3: ACCC register scrape, TGA ARTG 4 CSV chunks, small annualreports.com PDF sample (subsidiary notes) | T0.1, T0.3 (only what licence allows) |
| T0.7 | Define and apply Tier 1 slice (active status + state and/or ANZSIC divisions) targeting ~1M entities; record the exact filter | T0.4 |
| T0.8 | Locate / confirm `dirty_references.jsonl` (200 rows, 12 not in graph). **Not in the repo yet: request the file** | none |

### FR1. Ontology (OWL + SHACL)

| ID | Task | Depends on |
|---|---|---|
| T1.1 | Write the five driving questions (e.g. ultimate parent; parties within 2 hops of a disqualified party; licence status on date X; who sponsors ARTG product Y; companies with an ACCC notice and an AFSL cancelled in the last N months) | none |
| T1.2 | Party model: `:Party` superclass with `:Organisation` (aligned to `org:FormalOrganization`, `fibo-be:LegalEntity`) and `:Person` (`schema:Person`) subclasses; document consequences for resolution (bans and liquidators can attach to either) | T1.1 |
| T1.3 | Reification using the n-ary pattern: `:Licence` (number, authorisations, validFrom/validTo, status, transfers), `:Ban` (type, validFrom/validTo), `:Ownership` (owner, owned, percentage, source, validity), `:InfringementNotice` (amount, date), `:ProductSponsorship`. Keep ANZSIC, state, status as literals or SKOS concepts, not hub-linked nodes | T1.1, T1.2 |
| T1.4 | Provenance with PROV-O: `:SourceRecord` (`prov:Entity`) per raw record, `prov:wasDerivedFrom` from canonical facts; source records are never deleted | T1.3 |
| T1.5 | Validity time on every reified fact (`:validFrom`, `:validTo`) plus load time from the named graph's snapshot date (bitemporal) | T1.3 |
| T1.6 | SHACL shapes for invariants (ABN 11 digits + checksum, ABN unique per party, ACN unique, LEI unique, one canonical key per party, ownership percentage 0 to 100); violation handling: quarantine table in DuckDB + conflict record (e.g. ACN under two names) | T1.3, T1.4 |
| T1.7 | High-degree analysis at 15M scale (state, ANZSIC, postcode, address, status) and mitigation (literals / SKOS, no hub edges) | T1.3 |
| T1.8 | Extension points: new source = new adapter + new named graph; new relationship type = new subclass of `:Relationship` (n-ary) with no change to existing classes; new entity type = subclass of `:Party` or `:Thing` | T1.3 |
| T1.9 | `match_type` vocabulary as a SKOS concept scheme (e.g. `exact_abn`, `exact_acn`, `exact_lei`, `exact_licence_no`, `name_normalised_exact`, `name_fuzzy`, `name_semantic`, `wikidata_alias`) | T1.3 |
| T1.10 | Write `ontology/schema.ttl` (OWL) and `ontology/shapes.ttl` (SHACL); diagram optional | T1.2 to T1.9 |
| T1.11 | `ontology/NOTES.md` (2 pages): questions, reification choices, party type, constraints, extension points, take/reject from schema.org, W3C Org, FIBO, GLEIF | T1.10 |

### FR2. Graph build and load

| ID | Task | Depends on |
|---|---|---|
| T2.1 | Document storage split and consistency strategy: DuckDB is the system of record; Fuseki is a derived view rebuilt per named graph from DuckDB | T0.1, T1.10 |
| T2.2 | Source adapters: parse each source into a DuckDB staging table with stable `source_record_id` and content hash; stream-parse ABR XML | T0.4 to T0.6, T1.4 |
| T2.3 | Name normalisation library (case, punctuation, PTY LTD / LIMITED, "THE", "&"/"AND", trading-as splits) | T2.2 |
| T2.4 | Tier 1 canonical parties in DuckDB keyed on ABN/ACN, with conflict quarantine | T2.2, T1.6, T0.7 |
| T2.5 | RDF exporter: DuckDB query to N-Quads per named graph, deterministic IRIs from natural keys (e.g. `urn:abn:{abn}`, `urn:src:{source}:{id}`) | T2.4, T1.10 |
| T2.6 | Load into Fuseki: initial bulk load with `tdb2.tdbloader` (offline, Java, works on Windows); incremental reloads via Graph Store HTTP PUT per named graph (replace = idempotent); measure rerun cost | T2.5, T0.2 |
| T2.7 | SHACL validation run (Jena `shacl` CLI or pyshacl on a sample); violations into the quarantine table | T2.6, T1.6 |
| T2.8 | Validity time populated (licence start/cancel, ban start/end, deregistration date) | T2.4, T1.5 |
| T2.9 | Tier 2 / Tier 3 source records + reified facts exported to their named graphs (links come from FR3) | T2.2, T2.5 |
| T2.10 | GLEIF L2 parent/child into `:Ownership` facts | T2.9, T3.2 |
| T2.11 | `outputs/load_report.csv`: source, records_in, nodes_out, edges_out, records_rejected, top_rejection_reason (nodes/edges counted per named graph via SPARQL) | T2.6 to T2.10, T3.6 |

### FR3. Entity resolution (runs in DuckDB + Python)

| ID | Task | Depends on |
|---|---|---|
| T3.1 | Identifier coverage per Tier 2 source (count + %) of ABN/ACN/LEI present and valid (ABN checksum) | T2.9 |
| T3.2 | **Exact path**: deterministic joins on ABN, ACN, LEI, licence number, normalised-name exact on Tier 1 | T2.4, T2.9, T3.1 |
| T3.3 | Blocking for name-only records (normalised first distinctive token + state, sorted neighbourhood, FTS top-k); measure blocking recall on exact-path pairs | T2.3, T2.4 |
| T3.4 | **Semantic path**: fuzzy scoring (token set, Jaro-Winkler) + local embeddings on blocked candidates; distinctive-token overlap feature so "Commonwealth Bank of Australia" vs "Commonwealth Superannuation Corporation" fails | T3.3 |
| T3.5 | Arbitration rule: identifier match always wins; semantic can never override a conflicting identifier; top-1 vs top-2 margin rule | T3.2, T3.4 |
| T3.6 | Thresholds: global + stricter per-source threshold for banned/disqualified and ACCC (accusation risk); person vs organisation handling for liquidators and bans | T3.5, T4.3 |
| T3.7 | Emit `outputs/links.jsonl` and export to `urn:graph:links:{matcher_version}` (left/right source + record id, canonical key, match_type, confidence, evidence) | T3.6, T2.5 |
| T3.8 | Emit `outputs/abstentions.jsonl` (source, record id, best candidate, score, reason) | T3.6 |
| T3.9 | Store matcher version, raw features and scores for every candidate in DuckDB so recalibration re-thresholds without re-matching | T3.4 |

### FR4. Evaluation and labels

| ID | Task | Depends on |
|---|---|---|
| T4.1 | Stratified sample (by source pair, tier, score band, incl. abstentions and near-threshold), at least 50, ideally 150+ | T3.4 |
| T4.2 | Hand-label in `labels/` with method notes (blind to score, checked against ABN Lookup / ASIC) | T4.1 |
| T4.3 | Threshold sweep on labels in DuckDB; pick operating point favouring precision | T4.2, T3.9 |
| T4.4 | Precision/recall per source pair and per tier; blocking recall cost; confusion cases incl. the two named tests | T3.7, T3.8, T4.3 |
| T4.5 | Write `outputs/evaluation.md` | T3.1, T3.3, T4.4 |

### FR5. `resolve` lookup

| ID | Task | Depends on |
|---|---|---|
| T5.1 | `resolve(reference)`: parse identifiers if present, route to exact path, else blocking + semantic; enrich top candidates from Fuseki; return canonical key, score, match_type, evidence, and the SQL/SPARQL that found it | T3.5, T3.6, T2.6 |
| T5.2 | Decision: resolved vs abstained (same thresholds as FR3) | T5.1 |
| T5.3 | Run all 200 `dirty_references.jsonl` rows, emit `outputs/resolve_results.jsonl` in order with latency | T5.2, T0.8 |
| T5.4 | Expose as FastAPI endpoint + agent tool schema | T5.1 |

### FR6. Selection criteria to dataset projection

| ID | Task | Depends on |
|---|---|---|
| T6.1 | Criteria spec (JSON: fact predicates + time windows + projection columns) | T1.10 |
| T6.2 | Compiler: graph predicates to SPARQL (with `validFrom`/`validTo` filters), bulk filters to DuckDB SQL; join on canonical key | T6.1, T2.8, T3.7 |
| T6.3 | Projection output (CSV/Parquet) with provenance columns (source graph, link id); documented examples incl. "ACCC notice AND AFSL cancelled in last 3 months" | T6.2 |

### FR7. Graph traversals

| ID | Task | Depends on |
|---|---|---|
| T7.1 | Ultimate parent in Python: BFS over one-hop SPARQL `:Ownership` queries, max depth, visited set, majority/percentage rule; returns full chain, depth and cycle flag. Show the SPARQL property path (`:ownedBy+`) version alongside and explain why it is not enough | T2.10 |
| T7.2 | Graph-only question in SPARQL: parties within 2 hops of a banned/disqualified party (via liquidator firm, shared ownership, shared address), or a better one | T3.7, T2.9 |
| T7.3 | Traversal caps: per-relationship budgets and ranking (active over historical, regulatory facts over products, recency) with "N more truncated" summary | T7.1, T7.2 |
| T7.4 | Write `outputs/graph_queries.md`: query text, result, runtime, cycle behaviour | T7.1 to T7.3 |

### FR8. Performance and cost

| ID | Task | Depends on |
|---|---|---|
| T8.1 | Measure resolve p50/p95 (T5.3 run + warm benchmark) | T5.3 |
| T8.2 | Load wall-clock per source (export + load), TDB2 and DuckDB size on disk, triple count per named graph | T2.11 |
| T8.3 | Cloud cost per 1,000 resolutions (estimated: compute for Fuseki + app); track actual API spend | T8.1 |
| T8.4 | Write `outputs/performance.md`, marking measured vs estimated | T8.1 to T8.3 |

### FR9. Demo

| ID | Task | Depends on |
|---|---|---|
| T9.1 | Streamlit search box calling `resolve`; ranked candidates, match type, score, evidence | T5.1 |
| T9.2 | Entity page from SPARQL: identifiers, source records (per named graph), licences, bans, parents, subsidiaries | T9.1, T7.3 |
| T9.3 | Traversal view (ultimate parent chain or 2-hop disqualified) | T7.1, T7.2 |
| T9.4 | Abstentions page (browse `abstentions.jsonl` with reasons) | T3.8 |
| T9.5 | Deploy: Streamlit Cloud + Fuseki on free Render/Fly with a trimmed TDB2 snapshot; fallback recording + `docker compose up` (Fuseki + app) | T9.1 to T9.4 |

### FR10. Documentation and submission

| ID | Task | Depends on |
|---|---|---|
| T10.1 | `README.md`: clean-checkout run in under 10 minutes (incl. Java/Fuseki step), demo URL, sources taken/skipped and why, slice, known breakage | T9.5, T0.3, T0.7 |
| T10.2 | `WRITEUP.md` (2 pages, 8 questions; Q4 reprocess economics is the priority, answered via versioned links graphs + stored features) | FR2 to FR8 |
| T10.3 | Clean-checkout dry run on a fresh clone; confirm required filenames exist | T10.1, T10.2 |

---

## Dependency view

```
FR0 Foundations ──► FR1 Ontology ──► FR2 Load (DuckDB → N-Quads → Fuseki) ──► FR3 Resolution ◄──► FR4 Evaluation
                                          │                                     │            (threshold loop)
                                          │                                     ├──► FR5 resolve ──► FR8 Performance
                                          │                                     ├──► FR6 Projection
                                          └──► (GLEIF L2 ownership) ────────────┴──► FR7 Traversals
                                                         FR5 + FR7 + FR3 outputs ──► FR9 Demo
                                                         everything ──► FR10 Docs
```

**Critical path:** T0.4 → T0.7 → T1.10 → T2.2 → T2.4 → T3.3 → T3.4 → T4.2 → T4.3 → T3.6 → T5.1 → T5.3 → T9.5 → T10.3

**Can run in parallel:**
- T0.2 Fuseki setup, T0.3 licence review and T1.1 to T1.9 ontology design while Tier 1 downloads
- Tier 2/3 adapters (T2.9) alongside the Tier 1 load (T2.4)
- RDF export and Fuseki load (T2.5, T2.6) do not block resolution (FR3 runs in DuckDB); only T5.1 enrichment, FR6 and FR7 need Fuseki
- FR6 and FR7 alongside FR4 labelling, once links exist
- WRITEUP drafting from day 3

**The one cyclic dependency:** thresholds (T3.6) need labels (T4.3), labels need candidate scores (T3.4). Break it by running FR3 with a provisional threshold, labelling, then re-thresholding from stored features (T3.9) and writing a new `urn:graph:links:{version}`.

## Suggested 7-day schedule

| Day | Focus | Exit criterion |
|---|---|---|
| 1 | FR0 + FR1 draft | Data downloaded, slice ~1M, licences recorded, Fuseki running, `schema.ttl` v1 |
| 2 | FR2 | Tier 1 + Tier 2 in DuckDB, exported and loaded to Fuseki, SHACL report, load report v1 |
| 3 | FR3 exact path, blocking, semantic path | links + abstentions v1 |
| 4 | FR4 labels + thresholds, rerun FR3 | evaluation.md with P/R |
| 5 | FR5, FR6, FR7 | resolve_results.jsonl, graph_queries.md |
| 6 | FR8 + FR9 | Demo hosted, performance.md |
| 7 | FR10 | README, NOTES, WRITEUP, clean-checkout dry run |

## Open questions / risks

- `dirty_references.jsonl` is referenced but not supplied. Request it early (blocks T5.3).
- Java 17+ is required for Jena 5.x; include it in the README setup.
- `tdb2.xloader` is a bash script; on Windows use `tdb2.tdbloader` (pure Java) or run xloader under Git Bash/WSL.
- Estimated ~20 to 40M triples for the 1M slice; fine for TDB2, but give the loader 4+ GB heap.
- Free-tier hosts (~512 MB RAM) will not serve the full TDB2 dataset; ship a trimmed demo snapshot and state it in the README.
- ABR bulk extract is multi-GB XML: stream-parse and filter during parse.
- annualreports.com and ACCC: check terms of use before scraping (T0.3); a small manual sample may be the honest choice.
- People data (directors) is not in the listed open sources; "2 hops from a disqualified person" may need liquidator firm links or GLEIF instead. Decide in T7.2.
- At 15M companies / 1B edges (~10B+ triples) TDB2 breaks first; migration target is GraphDB, Stardog or Neptune (WRITEUP Q6).
