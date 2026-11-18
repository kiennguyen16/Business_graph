# Ontology notes

`schema.ttl` (OWL, `bg:` = `https://w3id.org/bizgraph/ont#`), `shapes.ttl` (SHACL), `examples.ttl` (synthetic violation), tests in `tests/test_ontology.py`.

## 1. Five questions and the decisions they forced

| # | Question | Decision |
|---|---|---|
| Q1 | Ultimate parent of X, bounded, cycle-safe | Reified `bg:Ownership` with `bg:relationshipKind`; traversal follows DIRECT consolidation only, ULTIMATE is a cross-check; cycles are legal data |
| Q2 | Organisations within N hops of a party banned on date D | One `bg:Party` superclass (a ban hits a person or an organisation); `bg:Relationship` with generic roles `bg:subject` / `bg:counterparty` so traversal walks any relationship type |
| Q3 | Did X hold an AFSL/ACL on D; who held licence N then | `bg:Licence` is a holding period; a transfer is a new holding with `bg:transferredFrom`; one holder per number at any instant |
| Q4 | ACCC notice AND licence cancelled in the last 3 months, with confidence | Validity bounds on every fact; `bg:Link` carries match type and confidence |
| Q5 | ARTG sponsor of P, its party, or why not | `bg:SourceRecord` kept forever; first-class `bg:Abstention`; `bg:matcherVersion` on every decision |

## 2. Reified vs property

- **Reified:** Licence holding, Ban, Ownership, Affiliation, Trusteeship, InfringementNotice, ProductSponsorship (all `bg:Fact`; two-party ones `bg:Relationship`), plus `bg:Link` / `bg:Abstention`. Each has attributes, a validity interval or its own provenance.
- **Literals:** identifiers, names, status, state, postcode, ANZSIC, legal form, jurisdiction, authorisation text, ban type, product name, regulator, notice numbers and legislation, evidence JSON, matcher version. Records carry `bg:sourceUrl` and `bg:foreignReference` (evidence only, never a match key).
- **Graph layout:** one published snapshot graph per source (latest only: record IRIs are stable, so a union would give a record two `bg:snapshotDate` values), `urn:graph:derived:*` for facts inferred across snapshots (e.g. `licence_history`: ended licences as `urn:fact:{source}:{record_id}:ended:{event_date}` with NotBefore/NotAfter bounds), `urn:graph:canonical`, `urn:graph:links:{version}`, `urn:graph:ontology`.
- **Facts point at records, not parties.** In a source graph a fact has `bg:aboutRecord <urn:src:...>`. Party roles (`bg:licensee`, `bg:bannedParty`, `bg:owner`, `bg:trustee`, ...) are shortcuts written to `urn:graph:links:{version}`, derived from links. Re-thresholding swaps one named graph; facts are never edited. SHACL rejects a role edge not backed by a link (or, for a counterparty named only by ACN/LEI, by identifier equality).
- **Unresolved counterparty.** A relationship may name its counterparty only by `bg:counterpartyName` (500 of 660 liquidators name their firm this way). The fact is kept, but a name never backs a party role: `bg:affiliatedWith` is written only once the firm resolves through a link. This is the abstention principle applied to relationships.
- **Identifiers are literals, not nodes:** the party IRI is minted from the strongest identifier. Party identifiers (`bg:abn`, `acn`, `arbn`, `arsn`, `nzbn`, `nzCompanyNumber`, `lei`) live on `bg:PartyOrRecord`: the record holds source assertions, the party the canonical choice. Licence and liquidator numbers are **record-only**. `bg:leiRegistrationStatus` is separate from entity status (a DUPLICATE or ANNULLED LEI never supports `EXACT_LEI`).
- **`bg:relationshipStatus`** is the source's status as of the snapshot (GLEIF ACTIVE/INACTIVE), not validity time.

## 3. One party type or two

One `bg:Party`, two disjoint subclasses `bg:Organisation` and `bg:Person`. Bans, links and licences range over `bg:Party`; a sole trader is a Person with an ABN. "Unknown type" exists only on a **record** (`bg:partyTypeHint`); the pipeline never mints an untyped party (SHACL warning). Resolution consequences: person-to-organisation links are refused (`PARTY_TYPE_CONFLICT`); unknown-type records get the strictest threshold; same-name people are never merged on name alone. `bg:ManagedInvestmentScheme` (ARSN) subclasses `bg:Organisation` rather than adding a third type, so queries over organisations stay correct while the matcher refuses ARSN-to-ACN matches (same checksum, different number space).

## 4. Uniqueness constraints and invariants

- Formats: ABN 11 digits, ACN/ARBN/ARSN 9, NZBN `94` + 11, LEI 18 alphanumerics + 2 digits, licence numbers without leading zeros. Checksums run at ingest; SHACL is the second fence.
- At most one value per identifier scheme per party; each identifier value on at most one party (`sh:sparql`). An ARSN implies `bg:ManagedInvestmentScheme`, which never has an ACN.
- Every fact: exactly one `bg:aboutRecord`, at least one `prov:wasDerivedFrom`, at most one subject party per links version, `validFrom <= validTo`, and every bound ordered (`NotBefore <= NotAfter`, a stated date inside its bounds).
- A relationship names its counterparty by exactly one of record, ACN, LEI or name. Ownership percentage in [0, 100]. One licence holder at a time.
- A link: exactly one source record, party and match type, confidence in [0, 1]. One decision per record per matcher version. A ban has exactly one party record and at most one attributed party (zero = abstained, which is allowed).

**On violation: quarantine, never merge.** Records and parties carrying the conflicting value go to the DuckDB `quarantine` table, parties stay separate, and the matcher abstains with `QUARANTINED_TARGET`. `examples.ttl` holds ACN 610005555 under two names; both parties are reported. No `owl:hasKey` or inverse-functional properties: OWL resolves a duplicate key by inferring `owl:sameAs`, a silent merge.

## 5. High-degree nodes at 15M companies

State (~5M per value), status (~10M), country, ANZSIC, postcode, legal form, source, snapshot, matcher run and regulator are **literals**: as nodes, any expansion through them returns a large share of the graph. Code lists join as SKOS by `skos:notation`, with no instance edges. Match type, licence kind and relationship kind stay SKOS concepts (they need definitions) but are marked `bg:traversalPolicy "filter-only"` and have no inverse properties. Large corporate groups are real hubs; the service layer caps traversals.

## 6. Extension points

- **New relationship type:** subclass `bg:Relationship`, one role subproperty each of `bg:subject` and `bg:counterparty`, one `bg:RelationshipKind`, one shape. Traversals read roles from `urn:graph:ontology`; nothing else changes. `bg:Affiliation` and `bg:Trusteeship` (`bg:trust`, `bg:trustee`, `HAS_TRUSTEE`) were added this way.
- **New fact / entity type:** subclass `bg:Fact` / `bg:Party`. **New source:** a named graph. **New match type:** a concept plus the `sh:in` list.

## 7. Taken and rejected

- **schema.org / W3C Org:** Organisation and Person subclass `schema:Organization`, `org:FormalOrganization` (all from registers) / `schema:Person`; `bg:lei` subproperty of `schema:leiCode`; `bg:Affiliation` closeMatch `org:Membership`. Rejected `schema:parentOrganization` and `org:subOrganizationOf` for ownership (no percentage, validity or provenance).
- **FIBO / OMG Commons:** closeMatch `cmns-org:LegalEntity`; `bg:Licence` closeMatch `fibo-be-le-lp:BusinessLicense`. Rejected subclassing `LegalPerson` (ABR trusts are not legal persons) and FIBO's party-in-role model. Not imported: some FIBO axioms (exactly one jurisdiction) are false for our data.
- **GLEIF:** closeMatch `gleif-L1:LegalEntity`, `gleif-base:LegalEntityRelationship`, `gleif-L2:hasParent` / `hasChild` and the consolidation classes. Taken: DIRECT vs ULTIMATE. Rejected: the L2 record as our ownership node (it is a source record). Whether `gleif-L1:LEI` is a class or a property is still to verify.
- **PROV-O:** records, facts and links are `prov:Entity`; `prov:wasDerivedFrom` declared and reused. `owl:equivalentClass` is never used against external terms.

## 8. Match types

Exact path: `EXACT_ABN`, `EXACT_ACN`, `EXACT_LEI`, `EXACT_LICENCE_NO`, `NAME_NORMALISED_EXACT` (one compatible party only). Semantic path: `NAME_FUZZY`, `NAME_SEMANTIC`, `WIKIDATA_ALIAS`. Identifiers always win; names never override a conflicting identifier. Abstain reasons: `NO_CANDIDATE`, `BELOW_THRESHOLD`, `AMBIGUOUS`, `IDENTIFIER_CONFLICT`, `PARTY_TYPE_CONFLICT`, `QUARANTINED_TARGET`, `JURISDICTION_MISMATCH` (a foreign entity may name-link only to its own AU foreign-body registration).

## 9. Source records are never deleted

Parties, roles and links are derived views: undoing a merge or recalibrating means re-deriving a links graph, never repairing parties. Cost: storage, deduplicated by content hash.

## 10. Time

- Validity time is `bg:validFrom` / `bg:validTo`; load time is the snapshot graph's date.
- A change seen only between weekly snapshots gets **bounds**: `bg:validToNotBefore` (last snapshot showing it), `bg:validToNotAfter` (day before the first without it), and the same pair for the start. A single `validTo` would claim precision we lack and answer "valid on D?" wrongly for up to a week; with bounds the answer is yes, no or unknown.

## 11. IRIs

IRI segments are percent-encoded (non-unreserved characters become `%XX`), e.g. `urn:src:gleif_l2:A%7CIS_DIRECTLY_CONSOLIDATED_BY%7CB`; `bg:recordId` keeps the raw id. Party IRI precedence is `urn:abn:`, `urn:acn:`, `urn:lei:`, else minted `urn:party:`. A party later given an ABN changes IRI, so IRIs are re-derived per build. `bg:ownershipPercentage` comes from GLEIF ACCOUNTING_CONSOLIDATION quantifiers when present, and from shareholding sources.
