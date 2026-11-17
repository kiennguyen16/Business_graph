# Write-up

Draft. Numbers marked TODO are filled from the final (v3) run.

## 1. What lives where, and what it cost
- **DuckDB is the system of record**: every raw source record (immutable, versioned by content hash with first/last-seen snapshot), canonical parties, identifiers, aliases, quarantine, every scored candidate with its features, links and abstentions per matcher version, labels. All matching runs here, set-based.
- **Fuseki/TDB2 is a derived view**, rebuilt one named graph at a time from DuckDB: one graph per source (latest snapshot), `canonical`, `links:{matcher_version}`, `derived:licence_history`, `ontology`. Graph-store PUT replaces a graph, so a reload is idempotent. SHACL runs over the published set.
- **Consistency: solved by direction, not by sync.** Data flows one way, DuckDB to Fuseki; Fuseki is disposable. The cost: an export step on every change (about 33 s per million parties), a second service to host, and SPARQL being weak exactly where traversals need the path (we walk ownership in Python with a visited set).
- Fuzzy candidate retrieval is an inverted token index inside DuckDB, not a search engine: one less store to keep consistent, at the cost of hand-built blocking.

## 2. The threshold
- Default 0.90 on the name path; **0.97 plus a wider margin and compatible legal forms for banned/disqualified and ACCC**, where a wrong link publishes an accusation. Exact identifier links are 1.0, licence numbers 0.95 (licences transfer).
- Thresholds turned out not to be the main lever. In v2, every wrong GLEIF name link scored 0.97 to 1.0 (NZ trusts onto same-name WA trusts; RIO TINTO PLC onto RIO TINTO LIMITED). They were removed by **gates**, not thresholds: jurisdiction, all-token agreement, trust postcode, no formal-name match through trading-name aliases.
- What a customer sees: a **false positive** is a confident, wrong statement about a real company (worst case: a ban or ACCC notice on the wrong business). A **false negative** is a missing fact, shown as an abstention with the reason and best candidate. We trade recall for precision: name-only recall TODO (v2: AFSL 93%, credit 87% at 100% precision).

## 3. Extension
- **New relationship type**: one subclass of `bg:Relationship`, two role subproperties of `bg:subject`/`bg:counterparty`, one `bg:RelationshipKind` concept, one SHACL shape. Generic traversals read the roles from the ontology graph. `bg:Trusteeship` (from GLEIF `trustee_acn`) was added this way mid-project without touching existing classes.
- **New entity type**: a subclass of `bg:Party` (as `bg:ManagedInvestmentScheme` was) plus its identifier property and uniqueness shape.
- **Reprocessed**: only the source that carries it (one adapter, one named graph). Existing links are untouched unless the new type changes eligibility, in which case `redecide` replays stored candidates. Component touched: a new `SourceAdapter` subclass and the exporter's fact mapping.

## 4. Reprocess economics (the important one)
- **Decide from stored evidence, don't re-match.** Every candidate pair is stored with its full feature vector, the scorer inputs and the gate inputs (jurisdiction, postcode, alias type). A matcher version is immutable: code hash plus policy plus scorer config.
- A **threshold or policy change** is `redecide`: re-arbitrate stored candidates, write a new links version, diff it. Measured: about 10 s over 147k AFSL candidates, against 56 s to re-match (TODO v3 numbers).
- A **scorer-weight or gate change** replays the same way because inputs, not just scores, are stored (TODO confirm v3).
- A **new feature** needs re-scoring, but only of stored candidate pairs, not re-blocking a million records; a **blocking change** is the only full re-run. v1 to v2 was such a case and we measured it.
- **What must be recorded in advance**: the candidate set (including refused candidates), raw features, gate inputs, the version id on every link, and immutable source records so the inputs can be recomputed. Links are versioned graphs (`urn:graph:links:{version}`), so switching versions is a pointer change and rollback is free.

## 5. Time
- Facts carry validity (`bg:validFrom/validTo`); load time is the snapshot graph. Where a date is only known to lie between two snapshots (AFSL cancellations from weekly diffs), we store **bounds** (`validToNotBefore/NotAfter`) rather than invent a day, so "was it valid on D?" can answer unknown.
- To answer "true on date D" fully: keep every snapshot in DuckDB (we do) and publish point-in-time views; version canonical parties (renames and mergers as dated `bg:Fact`s rather than overwritten names); resolve links per snapshot. Today the graph answers as-of-latest for party attributes and as-of-D for facts with validity.

## 6. Scale
- First to break: **the triple store** (TDB2 at about 10B triples) and, before it, **Python feature extraction** in the matcher (47 s of 135 s for 60k GLEIF records; TODO v3). Then single-writer DuckDB for concurrent loads.
- Path: move feature extraction into SQL/vectorised UDFs, shard blocking by block key, and move the graph to a distributed store (Neptune, GraphDB cluster, or a property graph) while keeping DuckDB/Parquet as the system of record.

## 7. Licence
- **TGA ARTG**: "personal or internal use", no commercial use without permission. **annualreports.com**: no reuse licence. Neither used.
- Used: ABR and ASIC (CC BY 3.0 AU), GLEIF (CC0), ACCC (CC BY 4.0, third-party content excluded). Method: CKAN metadata for data.gov.au, each site's own terms page and robots.txt, quoted in `outputs/sources.md`.

## 8. Next (three weeks instead of six hours)
1. A human-labelled gold set across all source pairs and a regression gate in CI, so every matcher change ships with measured precision.
2. Person-level data (directors) so "two hops from a disqualified person" has real edges, and resolving liquidator firms to companies.
3. Point-in-time canonical parties and weekly ABR/ASIC snapshots, closing the AFSL history gap.
