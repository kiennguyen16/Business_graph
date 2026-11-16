# Architecture and Object-Oriented Design

Companion to `PLAN.md`. Stack: Python 3.11+, DuckDB (system of record), Apache Jena Fuseki on TDB2 (knowledge graph), local embeddings (semantic path), FastAPI + Streamlit (interfaces).

Diagrams are Mermaid and render on GitHub and in VS Code.

---

## 1. Architecture overview

### 1.1 Layers

| Layer | Responsibility | Components |
|---|---|---|
| **Sources** | Raw files and pages, untouched | ABR XML, ASIC CSVs, GLEIF L1/L2, ACCC HTML, ARTG CSVs, annual report PDFs, Wikidata SPARQL |
| **Ingestion** | Parse, validate, hash, stage; never mutates raw data | Source adapters, identifier validators, name normaliser |
| **Storage** | Durable state | DuckDB (records, canonical parties, candidates, links, labels), Fuseki/TDB2 (RDF graph per named graph), vector index (name embeddings) |
| **Resolution** | Candidate generation, scoring, arbitration, decision | Exact path, blocking + semantic path, arbiter, threshold policy |
| **Graph publishing** | DuckDB → RDF → Fuseki, then SHACL validation | RDF exporter, graph loader, SHACL validator |
| **Services** | Read-side logic an agent or UI calls | `ResolveService`, `ProjectionService`, `TraversalService` |
| **Interfaces** | Delivery | FastAPI (agent tool), Streamlit demo, CLI |

### 1.2 Component diagram

```mermaid
flowchart LR
  subgraph SRC[Sources]
    ABR[ABR bulk XML]
    ASIC[ASIC company register]
    T2[AFSL / Credit / Banned / Liquidator]
    GLEIF[GLEIF L1 + L2]
    T3[ACCC / ARTG / Annual reports]
    WD[Wikidata SPARQL]
  end

  subgraph ING[Ingestion]
    AD[Source adapters]
    NV[Normaliser + identifier validators]
  end

  subgraph DDB[DuckDB: system of record]
    SR[(source_record)]
    CP[(party_canonical / identifier)]
    QU[(quarantine)]
    CA[(candidate + features)]
    LK[(link / abstention)]
    LB[(label)]
  end

  VI[(Vector index<br/>name embeddings)]

  subgraph RES[Resolution]
    EX[Exact path]
    BL[Blocking]
    SE[Semantic path]
    AR[Arbiter + threshold policy]
  end

  subgraph PUB[Graph publishing]
    RX[RDF exporter]
    GL[Graph loader]
    SH[SHACL validator]
  end

  FU[(Fuseki / TDB2<br/>named graphs)]

  subgraph SVC[Services]
    RS[ResolveService]
    PS[ProjectionService]
    TS[TraversalService]
  end

  API[FastAPI agent tool]
  UI[Streamlit demo]

  SRC --> AD --> NV --> SR
  SR --> CP
  NV --> QU
  CP --> VI
  SR --> EX & BL
  CP --> EX & BL
  VI --> BL
  BL --> SE
  EX & SE --> CA --> AR --> LK
  LB --> AR
  SR & CP & LK --> RX --> GL --> FU
  FU --> SH --> QU
  CP & VI & LK --> RS
  FU --> RS & PS & TS
  DDB --> PS
  RS & PS & TS --> API & UI
```

### 1.3 Store responsibilities

| Store | Owns | Never holds | Rebuilt from |
|---|---|---|---|
| DuckDB | Truth: raw source records, canonical parties, every candidate with features, links per matcher version, labels, quarantine | Nothing derived from Fuseki | Raw source files |
| Fuseki/TDB2 | Graph view: parties, reified facts, provenance, links per version, ontology | Unresolved candidates, features, labels | DuckDB (export + load) |
| Vector index | Embeddings of normalised canonical names | Anything authoritative | `party_canonical` |

**Consistency rule:** data flows one way, DuckDB → Fuseki. Fuseki is disposable, so if it disagrees with DuckDB you rebuild the affected named graph. Every Fuseki write is a whole-graph `PUT` derived from a DuckDB snapshot, so partial states are never exposed.

### 1.4 Key DuckDB tables

| Table | Key columns | Purpose |
|---|---|---|
| `source_snapshot` | source, snapshot_date, file_hash, records_in | One row per ingested file |
| `source_record` | source, record_id, content_hash, snapshot_date, payload (JSON), name_raw, name_norm, abn, acn, lei, licence_no | Immutable raw records; PK (source, record_id, content_hash) |
| `party_canonical` | canonical_key, party_type, name, name_norm, abn, acn, lei, status, state, anzsic, valid_from, valid_to | Tier 1 backbone |
| `identifier` | canonical_key, scheme, value | ABN / ACN / LEI / licence numbers, unique per (scheme, value) |
| `quarantine` | source, record_id, invariant, detail, detected_at | Invariant violations (e.g. ACN under two names) |
| `candidate` | run_id, source, record_id, canonical_key, path, features (JSON), score | **Every** scored pair, kept for recalibration |
| `matcher_version` | version, code_hash, policy (JSON), created_at | What produced each link |
| `link` | link_id, matcher_version, source, record_id, canonical_key, match_type, confidence, evidence (JSON) | Accepted links |
| `abstention` | matcher_version, source, record_id, best_candidate, best_score, reason | Refused links |
| `label` | sample_id, source, record_id, canonical_key, is_match, labeller, notes | Hand labels |

---

## 2. Workflows

### 2.1 Ingestion (runs per source, weekly for ABR)

```mermaid
flowchart TD
  A[Download source file] --> B[Compute file hash]
  B --> C{Snapshot already ingested?}
  C -- yes --> Z[Skip: no-op rerun]
  C -- no --> D[Adapter: stream-parse to raw rows]
  D --> E[Validate identifiers<br/>ABN checksum, ACN check digit, LEI format]
  E --> F[Normalise names]
  F --> G[Compute content_hash per record]
  G --> H[Upsert source_record<br/>insert only new hashes]
  E -- invalid --> R[Count rejection + reason]
  H --> I{Tier 1?}
  I -- yes --> J[Build / update party_canonical + identifier]
  J --> K{Invariant violated?<br/>e.g. ACN under two names}
  K -- yes --> Q[Write quarantine row,<br/>do not merge]
  K -- no --> L[Refresh vector index for changed parties]
  I -- no --> M[Ready for resolution]
  L --> M
  R --> N[Load stats]
  M --> N
```

**Idempotency:** the file hash short-circuits identical reruns; content hashes mean a changed file only inserts changed records. Rerun cost = hash the file (seconds) if unchanged, otherwise parse + diff.

### 2.2 Resolution (batch, per non-Tier-1 source)

```mermaid
flowchart TD
  S[source_record rows for source X] --> P{Carries valid ABN / ACN / LEI / licence no?}
  P -- yes --> EX[Exact path:<br/>identifier join]
  P -- no --> BK[Blocking:<br/>token + state, FTS top-k, embedding top-k]
  EX --> FE[Feature extraction]
  BK --> FE
  FE --> SC[Scorers:<br/>exact, fuzzy, semantic]
  SC --> ST[(Store every candidate<br/>+ features + scores)]
  ST --> AR[Arbiter:<br/>identifier beats name,<br/>conflicting identifier = veto,<br/>top-1 vs top-2 margin]
  AR --> TP[Threshold policy<br/>per source / per party type]
  TP -- accept --> LK[(link)]
  TP -- refuse --> AB[(abstention + reason)]
  LK --> EXP[Export to urn:graph:links:version]
```

### 2.3 Graph publishing

```mermaid
sequenceDiagram
  participant CLI
  participant Exporter as RdfExporter
  participant DuckDB
  participant Loader as GraphLoader
  participant Fuseki
  participant SHACL as ShaclValidator

  CLI->>Exporter: export(named_graph)
  Exporter->>DuckDB: SELECT rows for graph
  Exporter-->>CLI: graph.nt (deterministic IRIs)
  alt first build
    CLI->>Loader: bulk_load(all .nq)  [tdb2.tdbloader, Fuseki stopped]
  else incremental
    CLI->>Loader: replace(graph_iri, graph.nt)
    Loader->>Fuseki: HTTP PUT /data?graph=iri
  end
  CLI->>SHACL: validate(graph_iri)
  SHACL->>Fuseki: CONSTRUCT graph
  SHACL-->>DuckDB: violations into quarantine
```

### 2.4 Recalibration (WRITEUP Q4)

```mermaid
flowchart LR
  A[New ThresholdPolicy or arbiter rule] --> B[Re-decide from stored<br/>candidate features + scores]
  B --> C[New matcher_version]
  C --> D[Diff vs previous version:<br/>new links, dropped links, flipped abstentions]
  D --> E[Review sample of flips]
  E --> F[Export urn:graph:links:new_version]
  F --> G[Switch active version pointer]
```

No re-matching of the corpus is needed unless **features** change. If a new feature is added, only candidates in the affected score band are rescored.

### 2.5 `resolve` request

```mermaid
sequenceDiagram
  participant Agent as Agent / UI
  participant RS as ResolveService
  participant RP as ReferenceParser
  participant CG as CandidateGenerators
  participant DuckDB
  participant VI as VectorIndex
  participant M as Matcher
  participant Fuseki

  Agent->>RS: resolve("Commonwealth Bank of Aust, ABN 48 123 123 124")
  RS->>RP: parse(text)
  RP-->>RS: Reference(name_norm, identifiers)
  RS->>CG: generate(reference)
  CG->>DuckDB: identifier lookup / FTS
  CG->>VI: nearest names
  CG-->>RS: candidates (with path = SQL / vector query)
  RS->>M: score + arbitrate + decide
  M-->>RS: ranked candidates, decision
  RS->>Fuseki: SPARQL enrich top-k (identifiers, licences, bans)
  RS-->>Agent: ResolveResult(decision, candidates[match_type, score, evidence, path], latency_ms)
```

### 2.6 Projection (selection criteria → dataset)

```mermaid
flowchart LR
  A[CriteriaSpec JSON<br/>e.g. ACCC notice AND AFSL cancelled in last 3 months] --> B[QueryPlanner splits predicates]
  B --> C[SparqlCompiler:<br/>graph + validity-time predicates]
  B --> D[SqlCompiler:<br/>bulk attribute filters]
  C --> E[Fuseki: canonical keys]
  D --> F[DuckDB: canonical keys + columns]
  E & F --> G[Join on canonical_key]
  G --> H[Projection CSV / Parquet<br/>+ provenance columns]
```

### 2.7 Ultimate parent traversal

```mermaid
flowchart TD
  S[Start: canonical_key] --> Q[SPARQL: direct parents via :Ownership<br/>valid on as_of date, pct >= rule]
  Q --> V{Parent already visited?}
  V -- yes --> CY[Mark cycle, stop branch]
  V -- no --> D{Depth >= max_depth?}
  D -- yes --> TR[Mark truncated, stop]
  D -- no --> N{Has parents?}
  N -- no --> U[Ultimate parent found]
  N -- yes --> Q
  U & CY & TR --> R[Return chain, depth, cycle flag, truncated flag]
```

---

## 3. Object-oriented design

### 3.1 Package layout

```
src/bizgraph/
  config.py            Settings
  domain/              Party, Organisation, Person, Identifier, Fact subclasses, SourceRecord
  sources/             SourceAdapter + one adapter per source, SourceRegistry
  normalise/           NameNormaliser, IdentifierValidator subclasses
  store/               DuckDBStore, FusekiClient, VectorIndex, repositories
  rdf/                 Vocabulary, IriFactory, RdfExporter, GraphLoader, ShaclValidator
  pipeline/            IngestionPipeline, PublishPipeline, LoadReport
  resolution/          CandidateGenerator, Blocker, FeatureExtractor, Scorer, Arbiter,
                       ThresholdPolicy, Matcher, MatcherVersion, Link, Abstention
  evaluation/          LabelSampler, Evaluator, Metrics
  services/            ResolveService, ProjectionService, TraversalService, TraversalBudget
  api/                 FastAPI app
  cli.py               Entry points
demo/app.py            Streamlit
```

### 3.2 Domain model (mirrors the ontology)

```mermaid
classDiagram
  direction LR

  class Party {
    <<abstract>>
    +canonical_key: str
    +name: str
    +name_norm: str
    +identifiers: list~Identifier~
    +facts: list~Fact~
  }
  class Organisation {
    +entity_type: str
    +status: str
    +state: str
    +anzsic: str
  }
  class Person {
    +given_names: str
    +family_name: str
  }
  class Identifier {
    <<value object>>
    +scheme: IdScheme
    +value: str
  }
  class IdScheme {
    <<enum>>
    ABN
    ACN
    LEI
    AFSL
    ACL
  }
  class Fact {
    <<abstract>>
    +fact_id: str
    +valid_from: date
    +valid_to: date
    +derived_from: list~SourceRecord~
    +is_valid_on(d: date) bool
  }
  class Licence {
    +licence_no: str
    +kind: str
    +authorisations: list~str~
    +status: str
  }
  class Ban {
    +ban_type: str
  }
  class Ownership {
    +owner: Party
    +owned: Party
    +percentage: float
  }
  class InfringementNotice {
    +amount_aud: Decimal
    +description: str
  }
  class ProductSponsorship {
    +artg_id: str
    +product_name: str
  }
  class SourceRecord {
    <<immutable>>
    +source: str
    +record_id: str
    +content_hash: str
    +snapshot_date: date
    +payload: dict
  }

  Party <|-- Organisation
  Party <|-- Person
  Party "1" *-- "many" Identifier
  Identifier --> IdScheme
  Party "1" o-- "many" Fact : subject of
  Fact <|-- Licence
  Fact <|-- Ban
  Fact <|-- Ownership
  Fact <|-- InfringementNotice
  Fact <|-- ProductSponsorship
  Fact "many" --> "1..*" SourceRecord : derived from
  Ownership --> Party : owner
  Ownership --> Party : owned
```

`Fact` is the in-code equivalent of a reified edge in the ontology: anything with its own attributes or validity period. **Extension point:** a new relationship type is a new `Fact` subclass plus an ontology subclass; nothing else changes.

### 3.3 Ingestion and publishing

```mermaid
classDiagram
  direction LR

  class SourceAdapter {
    <<abstract>>
    +source_id: str
    +tier: int
    +licence: str
    +fetch(dest: Path) Path
    +parse(path: Path) Iterator~RawRow~
    +to_record(row: RawRow) SourceRecord
    +run(path: Path) LoadStats
  }
  class AbrAdapter
  class AsicCompanyAdapter
  class AfslAdapter
  class CreditLicenceAdapter
  class BannedOrgAdapter
  class LiquidatorAdapter
  class GleifL1Adapter
  class GleifL2Adapter
  class AcccNoticeAdapter
  class ArtgAdapter

  class SourceRegistry {
    -adapters: dict~str, SourceAdapter~
    +register(adapter)
    +get(source_id) SourceAdapter
    +all() list~SourceAdapter~
  }

  class IdentifierValidator {
    <<abstract>>
    +scheme: IdScheme
    +normalise(raw: str) str
    +is_valid(value: str) bool
  }
  class AbnValidator
  class AcnValidator
  class LeiValidator

  class NameNormaliser {
    +normalise(name: str) str
    +distinctive_tokens(name: str) set~str~
    +split_trading_as(name: str) list~str~
  }

  class IngestionPipeline {
    -registry: SourceRegistry
    -store: DuckDBStore
    +ingest(source_id, path) LoadStats
  }
  class CanonicalBuilder {
    +build(snapshot) list~Violation~
  }
  class RdfExporter {
    -iris: IriFactory
    -vocab: Vocabulary
    +export(graph: NamedGraph, out: Path) Path
  }
  class GraphLoader {
    -fuseki: FusekiClient
    +bulk_load(files: list~Path~)
    +replace(graph_iri: str, file: Path)
  }
  class ShaclValidator {
    +validate(graph_iri: str) list~Violation~
  }
  class PublishPipeline {
    +publish(graph: NamedGraph) LoadStats
  }
  class LoadReport {
    +rows: list~LoadStats~
    +to_csv(path)
  }

  SourceAdapter <|-- AbrAdapter
  SourceAdapter <|-- AsicCompanyAdapter
  SourceAdapter <|-- AfslAdapter
  SourceAdapter <|-- CreditLicenceAdapter
  SourceAdapter <|-- BannedOrgAdapter
  SourceAdapter <|-- LiquidatorAdapter
  SourceAdapter <|-- GleifL1Adapter
  SourceAdapter <|-- GleifL2Adapter
  SourceAdapter <|-- AcccNoticeAdapter
  SourceAdapter <|-- ArtgAdapter
  IdentifierValidator <|-- AbnValidator
  IdentifierValidator <|-- AcnValidator
  IdentifierValidator <|-- LeiValidator

  SourceRegistry o-- SourceAdapter
  SourceAdapter --> NameNormaliser
  SourceAdapter --> IdentifierValidator
  IngestionPipeline --> SourceRegistry
  IngestionPipeline --> DuckDBStore
  IngestionPipeline --> CanonicalBuilder
  PublishPipeline --> RdfExporter
  PublishPipeline --> GraphLoader
  PublishPipeline --> ShaclValidator
  GraphLoader --> FusekiClient
  ShaclValidator --> FusekiClient
  IngestionPipeline ..> LoadReport : produces stats
  PublishPipeline ..> LoadReport : produces stats
```

`SourceAdapter.run()` is a **template method**: fetch → parse → validate → normalise → hash → store is fixed, and subclasses only implement `parse` and `to_record`. **Extension point:** a new source is a new adapter registered in `SourceRegistry`.

### 3.4 Storage access

```mermaid
classDiagram
  direction LR

  class DuckDBStore {
    -conn
    +records: SourceRecordRepository
    +parties: PartyRepository
    +candidates: CandidateRepository
    +links: LinkRepository
    +labels: LabelRepository
    +quarantine: QuarantineRepository
  }
  class SourceRecordRepository {
    +upsert(records) int
    +by_source(source_id) Iterator~SourceRecord~
  }
  class PartyRepository {
    +by_identifier(scheme, value) Party
    +search_fts(name_norm, k) list~Party~
    +by_block_key(key) list~Party~
  }
  class CandidateRepository {
    +save(run_id, candidates)
    +for_run(run_id) Iterator~Candidate~
  }
  class LinkRepository {
    +save(version, links, abstentions)
    +active_version() str
    +diff(v_old, v_new) LinkDiff
  }
  class LabelRepository
  class QuarantineRepository

  class FusekiClient {
    -endpoint: str
    +query(sparql: str) list~dict~
    +construct(sparql: str) str
    +put_graph(iri: str, file: Path)
    +delete_graph(iri: str)
  }
  class VectorIndex {
    +build(parties)
    +nearest(text: str, k: int) list~tuple~
  }

  DuckDBStore *-- SourceRecordRepository
  DuckDBStore *-- PartyRepository
  DuckDBStore *-- CandidateRepository
  DuckDBStore *-- LinkRepository
  DuckDBStore *-- LabelRepository
  DuckDBStore *-- QuarantineRepository
```

### 3.5 Resolution

```mermaid
classDiagram
  direction LR

  class Reference {
    <<value object>>
    +source: str
    +record_id: str
    +name_raw: str
    +name_norm: str
    +identifiers: list~Identifier~
    +party_type_hint: str
    +state: str
  }

  class CandidateGenerator {
    <<abstract>>
    +path_name: str
    +generate(ref: Reference) list~Candidate~
  }
  class ExactIdentifierGenerator
  class BlockingGenerator {
    -blockers: list~Blocker~
  }
  class Blocker {
    <<abstract>>
    +block(ref: Reference) list~str~
    +describe() str
  }
  class TokenStateBlocker
  class FtsBlocker
  class EmbeddingBlocker

  class Candidate {
    +ref: Reference
    +canonical_key: str
    +path: str
    +query_text: str
    +features: FeatureVector
    +scores: dict~str, float~
  }
  class FeatureExtractor {
    +extract(ref, party) FeatureVector
  }
  class FeatureVector {
    <<value object>>
    +identifier_match: bool
    +identifier_conflict: bool
    +jaro_winkler: float
    +token_set: float
    +distinctive_overlap: float
    +embedding_cosine: float
    +state_match: bool
    +type_compatible: bool
  }

  class Scorer {
    <<abstract>>
    +name: str
    +score(fv: FeatureVector) float
  }
  class ExactScorer
  class FuzzyScorer
  class SemanticScorer

  class Arbiter {
    +arbitrate(cands: list~Candidate~) list~RankedCandidate~
  }
  class ThresholdPolicy {
    +default: float
    +per_source: dict~str, float~
    +min_margin: float
    +decide(source, ranked) Decision
  }
  class Decision {
    <<abstract>>
  }
  class Link {
    +match_type: MatchType
    +confidence: float
    +evidence: Evidence
  }
  class Abstention {
    +best_candidate: str
    +best_score: float
    +reason: AbstainReason
  }
  class Evidence {
    +features: FeatureVector
    +path: str
    +query_text: str
    +explanation: str
  }
  class MatchType {
    <<enum>>
    EXACT_ABN
    EXACT_ACN
    EXACT_LEI
    EXACT_LICENCE_NO
    NAME_NORMALISED_EXACT
    NAME_FUZZY
    NAME_SEMANTIC
    WIKIDATA_ALIAS
  }
  class MatcherVersion {
    +version: str
    +code_hash: str
    +policy: ThresholdPolicy
  }
  class Matcher {
    -generators: list~CandidateGenerator~
    -extractor: FeatureExtractor
    -scorers: list~Scorer~
    -arbiter: Arbiter
    -version: MatcherVersion
    +match(ref: Reference) Decision
    +match_batch(source_id) RunSummary
    +redecide(run_id, policy) RunSummary
  }

  CandidateGenerator <|-- ExactIdentifierGenerator
  CandidateGenerator <|-- BlockingGenerator
  BlockingGenerator o-- Blocker
  Blocker <|-- TokenStateBlocker
  Blocker <|-- FtsBlocker
  Blocker <|-- EmbeddingBlocker
  Scorer <|-- ExactScorer
  Scorer <|-- FuzzyScorer
  Scorer <|-- SemanticScorer
  Decision <|-- Link
  Decision <|-- Abstention
  Link *-- Evidence
  Link --> MatchType
  Candidate *-- FeatureVector
  Matcher o-- CandidateGenerator
  Matcher --> FeatureExtractor
  Matcher o-- Scorer
  Matcher --> Arbiter
  Matcher --> MatcherVersion
  MatcherVersion *-- ThresholdPolicy
  Matcher ..> Decision : produces
  Arbiter ..> Candidate
```

Patterns:
- **Strategy:** `Blocker`, `Scorer` and `CandidateGenerator` are swappable, so exact and semantic stay two named paths.
- **Facade:** `Matcher` is the single entry point for both batch resolution and `resolve`, so both use identical logic and thresholds.
- **Separation of scoring from deciding:** `Matcher.redecide()` reapplies a new `ThresholdPolicy` to stored `Candidate` features without regenerating candidates (WRITEUP Q4).

### 3.6 Evaluation

```mermaid
classDiagram
  direction LR
  class LabelSampler {
    +sample(run_id, strata, n) list~Candidate~
  }
  class Evaluator {
    +evaluate(version, labels) Metrics
    +sweep(run_id, labels, thresholds) list~Metrics~
  }
  class Metrics {
    +precision: float
    +recall: float
    +by_source_pair: dict
    +by_tier: dict
    +confusion_cases: list
  }
  LabelSampler --> CandidateRepository
  Evaluator --> LabelRepository
  Evaluator --> Matcher : redecide for sweeps
  Evaluator ..> Metrics
```

### 3.7 Services

```mermaid
classDiagram
  direction LR

  class ResolveService {
    -parser: ReferenceParser
    -matcher: Matcher
    -fuseki: FusekiClient
    +resolve(text: str, k: int) ResolveResult
  }
  class ReferenceParser {
    +parse(text: str) Reference
  }
  class ResolveResult {
    +decision: str
    +candidates: list~RankedCandidate~
    +latency_ms: float
  }
  class RankedCandidate {
    +rank: int
    +canonical_key: str
    +name: str
    +score: float
    +match_type: MatchType
    +evidence: Evidence
    +path: str
  }

  class ProjectionService {
    -planner: QueryPlanner
    +project(spec: CriteriaSpec) Dataset
  }
  class CriteriaSpec {
    +predicates: list~Predicate~
    +as_of: date
    +columns: list~str~
  }
  class Predicate {
    +fact_type: str
    +field: str
    +op: str
    +value
    +window: TimeWindow
  }
  class QueryPlanner {
    +plan(spec) QueryPlan
  }
  class QueryCompiler {
    <<abstract>>
    +compile(preds) str
  }
  class SparqlCompiler
  class SqlCompiler

  class TraversalService {
    -fuseki: FusekiClient
    +ultimate_parent(key, as_of, max_depth) OwnershipChain
    +within_hops(key, hops, budget) Neighbourhood
    +entity_view(key, budget) EntityView
  }
  class TraversalBudget {
    +max_depth: int
    +per_fact_type: dict~str, int~
    +rank_by: list~str~
  }
  class OwnershipChain {
    +nodes: list~str~
    +edges: list~Ownership~
    +cycle_detected: bool
    +truncated: bool
  }
  class EntityView {
    +party: Party
    +facts_by_type: dict
    +truncated_counts: dict~str, int~
  }

  ResolveService --> ReferenceParser
  ResolveService --> Matcher
  ResolveService ..> ResolveResult
  ResolveResult *-- RankedCandidate
  ProjectionService --> QueryPlanner
  ProjectionService *-- CriteriaSpec
  CriteriaSpec *-- Predicate
  QueryPlanner o-- QueryCompiler
  QueryCompiler <|-- SparqlCompiler
  QueryCompiler <|-- SqlCompiler
  TraversalService --> TraversalBudget
  TraversalService ..> OwnershipChain
  TraversalService ..> EntityView
```

`TraversalBudget` implements the "cap what a traversal returns" requirement: each fact type gets a quota, items are ranked (active before historical, regulatory before products, recent first), and `EntityView.truncated_counts` tells the agent what was dropped.

---

## 4. Traceability to the plan

| FR | Main classes |
|---|---|
| FR0 Foundations | `Settings`, `SourceAdapter.fetch`, `SourceRegistry` |
| FR1 Ontology | `Vocabulary`, `domain/*`, `ontology/schema.ttl`, `ontology/shapes.ttl` |
| FR2 Load | `IngestionPipeline`, `CanonicalBuilder`, `RdfExporter`, `GraphLoader`, `ShaclValidator`, `LoadReport` |
| FR3 Resolution | `Matcher`, generators, blockers, scorers, `Arbiter`, `ThresholdPolicy`, `LinkRepository` |
| FR4 Evaluation | `LabelSampler`, `Evaluator`, `Metrics` |
| FR5 resolve | `ResolveService`, `ReferenceParser`, `ResolveResult` |
| FR6 Projection | `ProjectionService`, `CriteriaSpec`, `QueryPlanner`, `SparqlCompiler`, `SqlCompiler` |
| FR7 Traversals | `TraversalService`, `TraversalBudget`, `OwnershipChain`, `EntityView` |
| FR8 Performance | timing decorators on services, `LoadStats` |
| FR9 Demo | `demo/app.py` over the three services |

## 5. Extension points summary

| Change arriving | Touch | Reprocess |
|---|---|---|
| New source | New `SourceAdapter` subclass, register it | Ingest that source, resolve it, publish its named graph |
| New relationship type | New `Fact` subclass + ontology subclass of `:Relationship` + SHACL shape | Only the source carrying it |
| New entity type | New `Party` subclass (or sibling) + ontology class | Sources carrying it; existing links untouched |
| New threshold | New `ThresholdPolicy` → `Matcher.redecide()` | No re-matching; new links graph version |
| New feature | `FeatureExtractor` + scorer | Rescore stored candidates in the affected band only |
