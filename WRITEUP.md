# Write-up

## 1. What lives where, and what it cost
- **DuckDB is the system of record**: every raw source record (immutable, versioned by content hash with first/last-seen snapshot), canonical parties, identifiers, aliases, quarantine, every scored candidate with its features and gate inputs, links and abstentions per matcher version, labels. All matching runs here, set-based.
- **Fuseki/TDB2 is a derived view**, rebuilt one named graph at a time from DuckDB: one graph per source (latest snapshot), `canonical`, `links:{matcher_version}`, `derived:licence_history`, `ontology`. Graph-store PUT replaces a graph, so a reload is idempotent. SHACL over the published set: 0 violations (outputs/shacl_report.md).
- **Consistency: solved by direction, not by sync.** Data flows one way, DuckDB to Fuseki; Fuseki is disposable. The cost: an export step on every change (about 33 s per million parties), a second service to host, and SPARQL being weak exactly where traversals need the path (ownership is walked in Python with a visited set and a depth bound).
- Fuzzy candidate retrieval is an inverted token index inside DuckDB, not a search engine: one less store to keep consistent, at the cost of hand-built blocking (blocking recall 98.5 to 99.4 percent, outputs/evaluation.md).

## 2. The threshold
- Name path 0.90; **0.97 plus a wider margin and compatible legal forms for banned/disqualified and ACCC**, where a wrong link publishes an accusation. Identifier links are 1.0; licence numbers 0.95 (licences transfer).
- Thresholds were not the main lever. In v2, every wrong GLEIF name link scored 0.97 to 1.0 (NZ trusts onto same-name WA trusts; RIO TINTO PLC onto RIO TINTO LIMITED). Gates removed them where no threshold could: jurisdiction, every reference token present, trust postcode/state, no formal-name match through trading-name aliases, reused former names.
- Result (v4, `m-b5e50f74`): **0 wrong links** on 463 labels (precision 100%, recall 92.5% over in-graph records), on our 200-row rehearsal set (100% / 79.8%) and on a held-out set never tuned on (100% / 80.9%).
- What a customer sees: a **false positive** is a confident, wrong statement about a real company (worst case: a ban or ACCC notice on the wrong business). A **false negative** is a missing fact, shown as an abstention with its reason and best candidate (outputs/abstentions.jsonl). We trade recall for precision deliberately.
- General-purpose embeddings are poor at entity names (CBA vs Commonwealth Superannuation Corporation: cosine 0.66), so the semantic path is evidence only and decided 0 links. An A/B test (MiniLM vs bge-small, both local and free) found no gain, so the baseline stayed.

## 3. Extension
- **New relationship type**: one subclass of `bg:Relationship`, two role subproperties of `bg:subject`/`bg:counterparty`, one `bg:RelationshipKind` concept, one SHACL shape. Generic traversals read roles from the ontology graph. `bg:Trusteeship` (from GLEIF trustee ACNs) was added this way mid-project without touching existing classes.
- **New entity type**: a subclass of `bg:Party` (as `bg:ManagedInvestmentScheme` was) plus its identifier property and uniqueness shape.
- **Reprocessed**: only the source that carries it (one adapter, one named graph). Existing links are untouched unless the new type changes eligibility, in which case `redecide` replays stored candidates. Components touched: a new `SourceAdapter` subclass and the exporter's fact mapping.

## 4. Reprocess economics (the important one)
- **Decide from stored evidence; do not re-match.** Every candidate pair is stored with its full feature vector, scorer inputs and gate inputs (jurisdiction, postcode, alias type). A matcher version is immutable: code hash plus policy plus scorer config. Canonical keys are stable across rebuilds (a key registry), so stored decisions stay valid.
- A **threshold or policy change** is `redecide`: re-arbitrate stored candidates, write a new links version, diff it. Measured: about 10 s over 147k AFSL candidates against 56 s to re-match.
- A **scorer-weight change** is a rescoring redecide from stored features: 35 s over 405k GLEIF candidates against 132 s to re-match.
- A **new feature** needs re-scoring of stored candidate pairs only; a **blocking change** is the only full re-run (v1 to v2 was one; measured and recorded).
- **What must be recorded in advance**: the candidate set (including refused candidates), raw features and gate inputs, the version id on every link, stable canonical keys, and immutable source records so inputs can be recomputed. Links are versioned graphs (`urn:graph:links:{version}`), so switching versions is a pointer change and rollback is free.

## 5. Time
- Facts carry validity (`bg:validFrom/validTo`); load time is the snapshot graph. Where a date is only known to lie between two snapshots (AFSL cancellations from weekly diffs), we store **bounds** (`validToNotBefore/NotAfter`) rather than invent a day, so "was it valid on D?" can answer unknown.
- To answer "true on date D" fully: keep every snapshot in DuckDB (we do), version canonical parties (renames and mergers as dated facts rather than overwritten names), and project links per snapshot. Today the graph answers as-of-latest for party attributes and as-of-D for facts with validity.

## 6. Scale
- First to break: **Python feature extraction** in the matcher (39 s of 147 s for 60k GLEIF records), then **the triple store** (TDB2 at billions of triples), then single-writer DuckDB for concurrent loads.
- Path: vectorised feature extraction in SQL, sharded blocking by block key, and a distributed graph store, keeping DuckDB/Parquet as the system of record. Cost is not the constraint: about USD 0.01 to 0.02 per 1,000 resolutions (v4 p50 285 ms) on an assumed USD 0.20/hour instance, embeddings local, API spend USD 0 (outputs/performance.md).

## 7. Licence
- **TGA ARTG**: personal or internal use only, no commercial use without permission. **annualreports.com**: no reuse licence. Neither used.
- Used: ABR and ASIC (CC BY 3.0 AU), GLEIF (CC0), ACCC (CC BY 4.0, third-party content excluded). Method: CKAN metadata for data.gov.au, each site's own terms page and robots.txt, quoted in outputs/sources.md.

## 8. Next (three weeks instead of six hours)
1. A human-labelled gold set across all source pairs and a CI regression gate, so every matcher change ships with measured precision; then fine-tune an entity-name embedding on our identifier-confirmed pairs (positives) and gate refusals (hard negatives).
2. Person-level data (directors) so "two hops from a disqualified person" has real edges, and resolve liquidator firms to companies.
3. Point-in-time canonical parties and weekly ABR/ASIC snapshots, closing the AFSL history gap.
