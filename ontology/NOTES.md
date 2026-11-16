# Ontology notes

Files: `schema.ttl` (OWL, namespace `https://w3id.org/bizgraph/ont#`, prefix `bg:`), `shapes.ttl` (SHACL invariants), `examples.ttl` (synthetic data incl. one deliberate violation), tests in `tests/test_ontology.py`.

## 1. Five questions, and what each one forced

| # | Question | Schema decision it shaped |
|---|---|---|
| Q1 | Ultimate parent of X, following the chain, bounded, cycle-safe | `bg:Ownership` reified with `bg:relationshipKind` (DIRECT vs ULTIMATE consolidation: the traversal follows DIRECT only, ULTIMATE is a cross-check); cycles are legal data, not a constraint |
| Q2 | Organisations within N hops of a party banned on date D | One `bg:Party` superclass so a `bg:Ban` can hit a person or an organisation; `bg:Relationship` with generic roles `bg:subject` / `bg:counterparty` so a traversal walks any relationship type; `bg:traversalPolicy` marks which edges to expand |
| Q3 | Did X hold a current AFSL/ACL on D, with which authorisations, and who held licence N then | `bg:Licence` is a *holding period*, not the licence: a transfer is a new holding with the same number and `bg:transferredFrom`; one-holder-at-a-time is a SHACL rule |
| Q4 | ACCC notice AND financial services licence cancelled in the last 3 months, with confidence | `bg:validFrom`/`bg:validTo` on every fact; `bg:Link` carries `bg:matchType` and `bg:confidence` so the projection can filter by attribution strength |
| Q5 | ARTG sponsor of P, which party it resolves to, or why not | `bg:SourceRecord` (PROV-O) kept forever; `bg:Abstention` is first-class with reason and best candidate; `bg:matcherVersion` on every decision |

## 2. Reified vs property

- **Reified (n-ary nodes):** Licence holding, Ban, Ownership, Affiliation, InfringementNotice, ProductSponsorship (all `bg:Fact`, the two-party ones `bg:Relationship`), and the resolution decisions `bg:Link` / `bg:Abstention`. Each has its own attributes, a validity interval, or provenance of its own.
- **Left as literal properties:** identifiers, name, status, state, postcode, ANZSIC, entity type, licence authorisation text, ban type, ARTG product name, regulator code, evidence JSON, matcher version.
- **Facts point at records, not parties.** In the source graph a fact says `bg:aboutRecord <urn:src:...>`. The party-level role (`bg:licensee`, `bg:bannedParty`, `bg:owner`, ...) is a shortcut written into `urn:graph:links:{version}` and derived from the `bg:Link`. Changing a threshold therefore rewrites attributions by swapping one named graph; facts are never edited. A SHACL rule rejects any role edge not backed by a link.
- **Identifiers are literals, not nodes.** A unique identifier node has degree 1 and adds only triples. The canonical IRI is minted from the strongest one (`urn:abn:`, else `urn:acn:`, else `urn:lei:`, else `urn:party:`), so the identifier already is the node. Licence numbers are not party identifiers (they transfer), so they live on `bg:Licence`.

## 3. One party type or two

One superclass `bg:Party`, two disjoint subclasses `bg:Organisation` and `bg:Person`. Bans, links and licences range over `bg:Party` because both kinds are banned, licensed and named in name-only sources. A sole trader holds an ABN, so identifiers attach to `bg:Party`, not `bg:Organisation`.

"Unknown type" is a property of a **record** (`bg:partyTypeHint "unknown"`), never of a canonical party: the pipeline does not mint a party it cannot type (a node typed only `bg:Party` is a SHACL warning). Consequences for resolution: a person record can never link to an organisation (abstain, `PARTY_TYPE_CONFLICT`); unknown-type records get the strictest threshold; person matching never uses the organisation semantic path (two people with the same name are not evidence of identity).

## 4. Uniqueness constraints and invariants (shapes.ttl)

- ABN `^[1-9][0-9]{10}$`, ACN/ARBN `^[0-9]{9}$`, LEI `^[A-Z0-9]{18}[0-9]{2}$`; checksums are enforced at ingest in Python, so SHACL is the second fence.
- A party has at most one ABN, ACN, LEI and exactly one current name; an ABN, ACN or LEI value belongs to at most one party (`sh:sparql`).
- Every fact has exactly one `bg:aboutRecord`, `validFrom <= validTo`, at least one `prov:wasDerivedFrom`, at most one subject party per links version.
- Ownership percentage in [0, 100]. A licence number has one holder at any instant.
- A link has exactly one source record, one party, one match type from the scheme, confidence in [0, 1], evidence and matcher version. One decision per record per matcher version.
- A ban references exactly one party record; its party attribution is at most one (zero means the matcher abstained, which is allowed: a wrong link is worse than none).

**On violation: quarantine, never merge.** The records and all parties carrying the conflicting value go to the DuckDB `quarantine` table; the parties stay separate; any candidate whose match rests on a quarantined identifier is refused with `QUARANTINED_TARGET`. `examples.ttl` contains this case (ACN 610005555 under two names) and the test asserts both parties are reported. OWL keys (`owl:hasKey`, inverse-functional properties) are deliberately absent: OWL's answer to a duplicate key is to infer `owl:sameAs`, which is a silent, irreversible merge.

## 5. High-degree nodes at 15M companies

| Would-be node | Degree at 15M | Mitigation |
|---|---|---|
| State (NSW) | ~5M | literal `bg:state` |
| Status (Active) | ~10M | literal `bg:registrationStatus` |
| ANZSIC class, postcode | up to ~1M, ~100k | literals; label lists as SKOS joined by `skos:notation`, no edges |
| Source / snapshot / matcher run | 1M to 15M | literal `bg:sourceId`, `bg:matcherVersion`; snapshot = named graph |
| Regulator (ACCC, ASIC) | every notice | literal `bg:regulator` |
| Match type, licence kind, relationship kind | millions of links | kept as SKOS concepts (they need definitions) but `bg:traversalPolicy "filter-only"`: used as filter constants, never expanded; no inverse properties declared |
| Large groups (one parent, thousands of subsidiaries) | real, unavoidable | traversal caps in the service layer, ranked by recency and fact type |

## 6. Extension points

- **New relationship type:** subclass `bg:Relationship`, add one role subproperty of `bg:subject` and one of `bg:counterparty`, add a `bg:RelationshipKind` concept, add a shape. Generic traversals read role properties from `urn:graph:ontology`; no existing class, data or graph changes. `bg:Affiliation` was added exactly this way.
- **New single-party fact:** subclass `bg:Fact` with a role subproperty of `bg:subject`.
- **New entity type:** subclass `bg:Party` (or `bg:Organisation`); existing links untouched.
- **New source:** new named graph `urn:graph:source:{source}:{date}`; nothing in the schema changes unless it carries a new fact type.
- **New match type / abstain reason:** a SKOS concept plus the `sh:in` list in `shapes.ttl`.

## 7. What was taken and rejected

- **schema.org:** `bg:Organisation subClassOf schema:Organization`, `bg:Person subClassOf schema:Person`, `bg:name subPropertyOf schema:name`, `bg:lei subPropertyOf schema:leiCode`. Rejected `schema:parentOrganization` / `subOrganization` as the ownership edge: no percentage, no validity, no provenance.
- **W3C Org:** `bg:Organisation subClassOf org:FormalOrganization` (every canonical organisation comes from a register). `bg:Affiliation` closeMatch `org:Membership` (same n-ary idea). Rejected `org:subOrganizationOf` and `org:hasSubOrganization` for the same reason as schema.org.
- **FIBO / OMG Commons:** `bg:Organisation` closeMatch `cmns-org:LegalEntity`, `bg:Licence` closeMatch `fibo-be-le-lp:BusinessLicense` (IRIs checked against the published files). Rejected `subClassOf cmns-org:LegalPerson`: ABR trusts and partnerships are not legal persons. Rejected FIBO's party-in-role model as the party class; rejected `LegallyCompetentNaturalPerson` (we cannot assert competence about a banned person). Not imported: FIBO's axioms (e.g. exactly one jurisdiction of incorporation) would be false for parts of our data.
- **GLEIF:** `bg:Organisation` closeMatch `gleif-L1:LegalEntity`; `bg:Ownership` closeMatch `gleif-base:LegalEntityRelationship`; `bg:owner`/`bg:owned` closeMatch `gleif-L2:hasParent`/`hasChild`; relationship kinds closeMatch `gleif-L2:DirectConsolidation`, `UltimateConsolidation`, `InternationalBranchRelationship`. Taken: the DIRECT vs ULTIMATE distinction. Rejected: modelling the L2 record itself as our ownership node (it is a source record; our `bg:Ownership` is derived from it). `gleif-L1:LEI` is referenced as `skos:closeMatch` / `rdfs:seeAlso` only; whether it is a class or a property in the published L1 file is still to verify.
- **PROV-O:** `bg:SourceRecord`, `bg:Fact`, `bg:Link` are `prov:Entity`; `prov:wasDerivedFrom` from facts and parties to records; `bg:Party subClassOf prov:Agent`.
- **owl:equivalentClass** is used nowhere against an external vocabulary: equivalence would pull their axioms onto our data in both directions.

## 8. Match type vocabulary (`bg:MatchTypeScheme`)

Exact path: `EXACT_ABN`, `EXACT_ACN`, `EXACT_LEI`, `EXACT_LICENCE_NO` (interval-aware), `NAME_NORMALISED_EXACT` (only when exactly one compatible party has that normalised name). Semantic path: `NAME_FUZZY`, `NAME_SEMANTIC`, `WIKIDATA_ALIAS`. Each concept has a `skos:broader` path and a `bg:precedence`. Arbitration: an identifier match always wins; a semantic match never overrides a conflicting identifier (abstain, `IDENTIFIER_CONFLICT`). Abstain reasons: `NO_CANDIDATE`, `BELOW_THRESHOLD`, `AMBIGUOUS`, `IDENTIFIER_CONFLICT`, `PARTY_TYPE_CONFLICT`, `QUARANTINED_TARGET`.

## 9. Source records are never deleted

A resolved record stays in its snapshot graph and in DuckDB, unchanged. Parties, role shortcuts and links are derived views (canonical graph, one links graph per matcher version). This is safe because nothing downstream owns data the records do not hold: undoing a merge, recalibrating a threshold or dropping a bad matcher version means re-deriving or deleting a *links graph*, never repairing parties. The cost is storage (one copy per changed record per snapshot, deduplicated by content hash), which is the price of being able to change our mind.

## 10. Time

Validity time: `bg:validFrom`/`bg:validTo` on every fact (closed interval, open when absent; events such as notices have equal dates). Load time: the snapshot date of the named graph. "What was true on D" is a filter on the facts; "what did we believe on D" is a choice of snapshot and links graphs. Not yet modelled with dates: name history and registration status history of a party (they are visible across snapshot graphs; a `bg:Naming` fact is the extension).
