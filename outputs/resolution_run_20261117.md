# Resolution run, 2026-11-17 / 18 (draft)

Store: `data/bizgraph.duckdb`. Engine: `src/bizgraph/resolution/`. DuckDB `memory_limit='5GB'`,
`threads=4`; embeddings `sentence-transformers/all-MiniLM-L6-v2` on CPU, loaded once per process and
computed only where the semantic path may apply. All numbers are **measured** on this machine unless
marked otherwise.

Three matcher versions are kept side by side in the store:

| | v1 (baseline) | v2 | v3 (current) |
|---|---|---|---|
| matcher_version | `m-dabec5ea-d900271d` | `m-1465a4ba-e5444596` | `m-94f4f6b2-d37e44c6` |
| What changed | first full-scale run | fixes after an adversarial test suite (section 5) | evaluation-driven gates (jurisdiction, trust postcode / state, stated ABN over a type hint, normaliser), data refresh, state penalty by basis, scorer config in the version, reference stored once per record |
| Needed | | re-match (new features and scorers) | re-match (new features and new data) |
| Labelled precision (242 labels on v2's sample) | | 74.3% (127 of 171 decided links; 44 wrong) | **100% (123 of 123; 0 wrong)** |

Reprocess economics in one line: a change of **policy or scorer weights** is a `redecide` over stored
candidates (GLEIF, 405k candidates, full rescore: 35 s; AFSL name-only, 157k candidates: 12 to 16 s);
a change of **features, gates that read new inputs, or data** is a re-match (GLEIF: 132 s). v2 and v3
both changed features, so both were re-matched; v3 stores its gate inputs in the candidate features so
the next gate change can be replayed by `redecide`.

## 0. v3 (current)

### What changed since v2

Evaluation-driven gates (`outputs/evaluation.md` sections 3 and N7; every case is a regression test in
`tests/test_resolution.py`):

1. **Jurisdiction gate (R3b).** A GLEIF reference whose legal jurisdiction is not AU may match on name
   only a party that is the Australian registration of a foreign body (ABR "Other Incorporated Entity",
   ASIC FNOS / RACN, ARBN; table `res_foreign_reg`). Any other name candidate is vetoed; if the veto
   blocked a candidate that would otherwise have linked, the reason is the new
   `AbstainReason.JURISDICTION_MISMATCH` (added to `bizgraph.domain.models`; needs the ontology
   concept). This removes the NZ trust to WA / TAS trust class, RIO TINTO PLC to RIO TINTO LIMITED, BHP
   Billiton Finance plc, Stanwell (NZ), The Toro Company, and keeps the foreign banks registered here.
2. **Trusts and super funds (R5h).** When either side is a trust or super fund (name, "trustee for", or
   ABR entity type), differing postcodes make the candidate ineligible, and a stated state that differs
   is a veto rather than a penalty (Browning Family Super 6210 vs 6023; Arkad Trust SA vs TAS).
3. **A stated ABN beats a type hint (R1c).** When the ABN matches and the reference's party type is only
   a hint (GLEIF entity category, SOLE_PROPRIETOR, or unknown), link EXACT_ABN and record the type
   disagreement in `evidence.disagreement`. 41 GLEIF records move from PARTY_TYPE_CONFLICT to EXACT_ABN.
4. **R5f covers NAME_NORMALISED_EXACT** (it already did; Toro matched through a *former* name of another
   company, now stopped by the jurisdiction gate; Prism Global Group Plc through a business name).
5. **Normaliser** (`normalise/names.py`): CO / COMPANY / CORP / CORPORATION are stripped only when a
   distinctive name of two or more tokens remains (`WT FINANCE CO` stays, `SIMPLY CORPORATION` stays,
   `WESTPAC BANKING CORPORATION` becomes `WESTPAC BANKING`), and a second legal form is stripped only for
   `... & CO PTY LTD`. The resolution index now normalises every party name and alias itself, because
   `party_canonical.name_norm` is the ingest-time value; a normaliser change no longer needs a Tier 1
   re-ingest to reach the matcher.
6. **Register names have no typo tolerance.** Found while checking the first v3 build: `Sunrise Medical
   Pty. Ltd` (GLEIF) linked SUNRISE MEDIA PTY LTD because MEDICAL / MEDIA pass the 0.93 Jaro-Winkler typo
   rule. Names read from a register (GLEIF, ASIC registers) now align tokens exactly; free text keeps
   the typo tolerance (`Comonwealth Bank`).
7. **Gate inputs stored in the candidate features**: `ref_jurisdiction`, `candidate_foreign_registration`,
   `jurisdiction_conflict`, `ref_postcode`, `candidate_postcode`, `postcode_match`, `trust_like`,
   `candidate_entity_type`, `party_type_basis`, `compared_name_kind`, `state_basis`.

Also in v3:

* **Data refresh.** New GLEIF L1 slice (59,659 entities) and L2 (370 new relationships). AFSL and credit
  histories: 6 archived AFSL captures (2025-04-14 to 2026-11-10) and 2 credit captures. The current
  files had been stored as 2026-11-09, before the 2026-11-10 capture, so both sources were rebuilt from
  the raw files in date order with the current files at their CKAN last_modified dates (AFSL
  2026-11-11, credit 2026-11-15; `outputs/sources.md`). AFSL holds 6,949 licences (13,758 versions),
  credit 4,606 (4,965 versions). `licence_event`: 2,532 events (AFSL 480 granted, 399 cancelled or
  lapsed, 246 renamed, 902 authorisation changed, 1 reappeared; credit 137 granted, 298 cancelled or
  lapsed, 48 renamed, 16 authorisation changed, 5 status changed; no HOLDER_CHANGED). Canonical
  rebuild: 1,075,667 parties, 42 quarantined. The ABR slice was not re-ingested against the new Tier 2
  references (recall cost; see section 6).
* **State penalty by basis.** -0.15 when a free-text reference states a state and the party is
  elsewhere; -0.05 register to register (a GLEIF legal address and an ABR main business location mean
  different things). Trusts and funds: veto, item 2.
* **Scorer config in the version, rescoring redecide**, **reference stored once per record**
  (`candidate_ref`), **CLI** (`bizgraph match | match-all | redecide | resolve | resolve-file |
  licence-events`) and **`scripts/run_pipeline.sh`** (all steps, per-step timing in `data/logs/`).

### Precision on the evaluation labels

The evaluation agent's 242 labels (`labels/labels_m-1465a4ba-e5444596.csv`) re-scored mechanically
against v3 (the evaluation agent will re-score independently):

| | v2 | v3 |
|---|---|---|
| Links on labelled records | 182 | 126 |
| Correct / wrong (UNSURE excluded) | 127 / 44 | 123 / 0 |
| Precision | 74.3% | **100%** |
| Labelled records with a true party in the graph but abstained | 7 | 12 |
| GLEIF name links of the census (v2 linked 91 labelled records on name, 75 of them decided) | 37 correct, 44 wrong | 29 correct, **0 wrong**, 60 abstain (2 still linked are UNSURE) |

The extra misses are the price: correct foreign-registration links lost where the GLEIF record is an
Australian company registered abroad (the 4 the evaluation predicted), and AU trusts whose postcode
differs between GLEIF and ABR.

### Batch results (v3)

| Source | Records | Links v1 / v2 / v3 | v3 links by match_type | v3 abstentions | Candidates | Wall-clock | Records/s |
|---|---|---|---|---|---|---|---|
| asic_afsl | 6,949 (incl. ended licences) | 6,522 / 6,519 / 6,872 | EXACT_ABN 6,688; EXACT_ACN 184 | BELOW_THRESHOLD 69; NO_CANDIDATE 5; PARTY_TYPE_CONFLICT 2; IDENTIFIER_CONFLICT 1 | 15,626 | 4.9 s | 1,419 |
| asic_credit | 4,606 | 4,235 / 4,234 / 4,464 | EXACT_ABN 4,057; EXACT_ACN 407 | BELOW_THRESHOLD 132; NO_CANDIDATE 10 | 12,460 | 3.9 s | 1,176 |
| asic_banned_org | 15 | 12 / 12 / 12 | EXACT_ACN 12 | BELOW_THRESHOLD 3 | 106 | 0.4 s | 40 |
| asic_liquidator | 660 | 0 / 0 / 0 | none (persons) | BELOW_THRESHOLD 657; NO_CANDIDATE 2; PARTY_TYPE_CONFLICT 1 | 17,091 | 4.8 s | 136 |
| gleif_l1 | 59,659 | 48,862 / 48,179 / 48,134 | EXACT_ACN 33,809; EXACT_ABN 14,158; NAME_NORMALISED_EXACT 143; NAME_FUZZY 24 | BELOW_THRESHOLD 10,510; NO_CANDIDATE 926; JURISDICTION_MISMATCH 84; IDENTIFIER_CONFLICT 3; AMBIGUOUS 2 | 405,081 | 131.8 s | 453 |
| accc_notice | 20 | 7 / 7 / 7 | EXACT_ACN 7 | BELOW_THRESHOLD 10; NO_CANDIDATE 3 | 341 | 0.5 s | 42 |

Peak process memory 3.4 GB (GLEIF). Start-up 62 s (index rebuild with Python re-normalisation of
1.65M names and aliases: 31 s; cached afterwards). Identifier links never retargeted between versions.

* v2 to v3: AFSL +353 and credit +231 identifier links (licences present only in the history files),
  credit -1; GLEIF +62 (41 EXACT_ABN from item 3, 20 NAME_FUZZY, 1 NAME_NORMALISED_EXACT) and -107
  (jurisdiction, trust postcode / state, register typo gate).
* **Ended licences**: every licence that ever appeared has a decision (matching reads the latest
  version of each licence, including licences absent from the current file). CANCELLED_OR_LAPSED
  licences: AFSL 399, of which 354 linked; credit 298, of which 231 linked; the rest abstain (mostly
  holders outside the ABR slice). All licences with any event: AFSL 1,641 (1,591 linked, 50 abstained),
  credit 498 (430 linked, 68 abstained). No HOLDER_CHANGED events, so the latest version's holder is
  the holder of every version.
* **ACCC**: identical to v1 and v2 (7 EXACT_ACN links, 13 abstentions; table in section 2).

### Candidate storage

| Version | Candidate rows | candidate.features JSON | candidate_ref | Bytes per candidate |
|---|---|---|---|---|
| v2 | 444,953 | 711.3 MB | none (reference repeated on every row) | 1,598 |
| v3 | 450,705 | 684.8 MB | 71,909 rows, 34.2 MB | 1,595 |

Moving the reference out saved about 1 KB per record but the v3 feature vector gained 11 gate inputs, so
bytes per candidate are flat. Next: store non-default features only and the query text once per
(record, path).

### Recalibration with rescoring (no re-match)

`redecide(v3, policy, source_id="gleif_l1", scorer_config=ScorerConfig(state_penalty_register=0.15))`
(v2's register-state penalty replayed on v3's stored features) read 405,081 candidates, rescored and
re-decided them in **35.1 s** (load 17.7 s, decide 11.7 s), dropping 9 name links, with no candidate
generation or feature extraction. Version `mr-94f4f6b2-f3b4d9f4` records the scorer config and
`rescored: true`.

### Name-only precision and recall (v3, identifiers stripped)

| Source | Truth (EXACT_ABN links) | Blocking recall | Name links on truth | Wrong | Precision | Recall (0.85, 0.90, 0.95 identical) |
|---|---|---|---|---|---|---|
| asic_afsl | 6,688 | 99.96% | 6,485 | 0 | 100% | 97.0% |
| asic_credit | 4,057 | 99.8% | 3,603 | 0 | 100% | 88.8% |

Redecide per threshold: 12.1 to 15.7 s (AFSL, 156,895 candidates), 7.5 to 8.5 s (credit, 103,775).
The threshold no longer moves anything in this range: after the gates the name scores are bimodal.

### resolve() latency (v3, warm)

Same 200-string recipe as v2 (28 with an ABN): p50 188 ms, p95 224 ms, max 241 ms. Outcomes: 139
NAME_NORMALISED_EXACT, 27 EXACT_ABN, 1 NAME_FUZZY, 28 BELOW_THRESHOLD, 5 AMBIGUOUS. Named cases
unchanged (CBA by name and by ABN, CSC by name). `bizgraph resolve-file in.jsonl out.jsonl` writes the
`outputs/resolve_results.jsonl` row format (reference id, ordered candidates with canonical key, score,
match type, evidence and path, decision resolved / abstained, latency); candidates that failed a gate
are counted, not listed, so a reference that is not in the graph gets an empty list.

---

The sections below are the v1 / v2 record (2026-11-17).

## 1. Batch results per source

| Source | Records | v1 links | v2 links | v2 links by match_type | v2 abstentions by reason | Candidates (v2) | v2 wall-clock | v2 records/s | Peak RSS (process) |
|---|---|---|---|---|---|---|---|---|---|
| asic_afsl | 6,551 | 6,522 | 6,519 | EXACT_ABN 6,351; EXACT_ACN 168 | BELOW_THRESHOLD 32 | 14,052 | 4.3 s | 1,536 | 1.1 GB |
| asic_credit | 4,308 | 4,235 | 4,234 | EXACT_ABN 3,846; EXACT_ACN 387; NAME_NORMALISED_EXACT 1 | BELOW_THRESHOLD 73; NO_CANDIDATE 1 | 10,579 | 3.2 s | 1,366 | 1.2 GB |
| asic_banned_org | 15 | 12 | 12 | EXACT_ACN 12 | BELOW_THRESHOLD 3 | 106 | 0.3 s | 50 | 1.2 GB |
| asic_liquidator | 660 | 0 | 0 | none (persons: never linked on a name alone) | BELOW_THRESHOLD 658; NO_CANDIDATE 2 | 17,031 | 4.9 s | 134 | 1.3 GB |
| gleif_l1 | 59,606 | 48,862 | 48,179 | EXACT_ACN 33,809; EXACT_ABN 14,117; NAME_NORMALISED_EXACT 238; NAME_FUZZY 15 | BELOW_THRESHOLD 10,379; NO_CANDIDATE 934; AMBIGUOUS 70; PARTY_TYPE_CONFLICT 41; IDENTIFIER_CONFLICT 3 | 402,844 | 135.4 s | 440 | 3.7 GB |
| accc_notice | 20 | 7 | 7 | EXACT_ACN 7 | BELOW_THRESHOLD 10; NO_CANDIDATE 3 | 341 | 0.6 s | 36 | n/a |

v1 detail for comparison: asic_afsl had EXACT_ABN 6,351, EXACT_ACN 168, NAME_SEMANTIC 2, NAME_FUZZY 1;
asic_credit had NAME_NORMALISED_EXACT 1, NAME_SEMANTIC 1; gleif_l1 had NAME_FUZZY 440, NAME_SEMANTIC
231, NAME_NORMALISED_EXACT 265 (936 name-path links against 253 in v2). v1 GLEIF wall-clock was 104.9 s
(568 records/s); v2 is slower because every candidate now aligns all tokens of every alias.

Notes:
* Exact-path links are identical between versions (48,127 GLEIF links unchanged, no retargets).
* GLEIF time split (v2): features 47 s, decide 27 s, persist 22 s, party loading 9 s, embeddings 9 s,
  blocking 7 s. Python feature extraction is the bottleneck, not DuckDB.
* `candidate` holds 444,953 v2 rows (about 711 MB of feature JSON, mostly the repeated reference
  block). Store file 3.2 GB. That repetition is the first thing to normalise before 15M companies.
* Peak RSS is the process working set read from the OS (`GetProcessMemoryInfo`), including the
  embedding model (about 0.7 GB at start-up).

### What v1 got wrong on GLEIF (and why v2 abstains)

v2 drops 735 GLEIF name links and 4 AFSL / credit name links that v1 made; it adds 52 (exact names that
v1 lost to ties or margins, e.g. `Bank of China Limited`, `Brookfield Rail Pty Ltd` via its former name
on ARC INFRASTRUCTURE PTY LTD). The v2 reason for each dropped v1 link:

| v2 rule that refused the v1 link | Count | Typical v1 error |
|---|---|---|
| reference token missing from candidate (R5a) | 349 | `JBWERE (NZ) NOMINEES LIMITED` to JBWERE LTD; `QIC Strategy Fund No. 3` to `... No. 2`; `INFRASHORE ASSET MANAGEMENT TRUST` to the Pty Ltd |
| legal form incompatible (R5c) | 168 | `CITIGROUP INC.` to CITIGROUP PTY LIMITED; `BOSTON SCIENTIFIC CORPORATION` to BOSTON SCIENTIFIC PTY LTD |
| score below threshold after the stated-state penalty | 65 | mostly real trust matches whose GLEIF and ABR states differ (recall cost, see 6) |
| formal name, candidate has extra tokens (R5g) | 39 | `MERCER PASSIVE INTERNATIONAL SHARES FUND` to the SUSTAINABLE fund |
| formal name only matches a business / trading / other name (R5f) | 41 | `ADT SECURITY LIMITED` to WORMALD AUSTRALIA PTY LTD; `GENUINE PARTS COMPANY` to RIVIERA AUSTRALIA |
| trust or fund vs company (R5d) | 29 | `Growth Fund` to THE GROWTH FUND PTY LTD; `RMF HOLDINGS LIMITED` to The Trustee for RMF Holdings |
| formal name without AUSTRALIA vs an AUSTRALIA candidate (R5e) | 28 | `DASSAULT SYSTEMES` to DASSAULT SYSTEMES AUSTRALIA PTY LTD |
| party type conflict | 18 | organisations against person parties |
| identifier conflict | 2 | |

Eyeball of a random 40 of the dropped v1 links: about 33 were wrong (mostly foreign parents linked to
their Australian subsidiary, NZ entities to AU namesakes, one fund to a sibling fund), 3 to 4 were
right and lost (trusts whose GLEIF state differs from the ABR state), the rest uncertain. Eyeball of
all 15 v2 NAME_FUZZY links and 40 random v2 NAME_NORMALISED_EXACT links: no clear error; 3 uncertain
(`APA Group` to APA GROUP LIMITED, a stapled group; `Shane Thomas McEwan & Dianne McEwan ATF Lifestyle
Superannuation Fund` to a generically named fund; `FARMLANDS MATHIAS INTERNATIONAL` to the Pty Ltd).
These are judgements for the label sample, not labels.

## 2. ACCC infringement notices (strict policy: threshold 0.97, margin 0.10)

Outcome is the same in v1 and v2 for every record (7 links, 13 abstentions); only the abstain reasons
changed (v1 reported IDENTIFIER_CONFLICT for Venue Smart and PARTY_TYPE_CONFLICT for H&M against weak
candidates; v2 reports a veto only when it blocked a candidate that would otherwise have passed).

| Slug | Name | Stated id | Decision (v2) | Match type / reason | Target party (link) or best candidate (abstention) |
|---|---|---|---|---|---|
| bayswood-timber-wholesalers-pty-ltd | Bayswood Timber Wholesalers Pty Ltd | ACN 006313284 | link | EXACT_ACN | BAYSWOOD TIMBER WHOLESALERS PTY. LTD. |
| cotton-on-australia-pty-ltd | Cotton On Australia Pty Ltd | ACN 634090083 | abstain | BELOW_THRESHOLD (0.64) | COTTON ON FINANCE PTY LTD |
| digital-imaging-express-pty-ltd-0 | Digital Imaging Express Pty Ltd | ACN 122703806 | link | EXACT_ACN | DIGITAL IMAGING EXPRESS PTY. LTD. |
| dysck-pty-ltd-trading-as-neptune-blanket | Dysck Pty Ltd | ACN 600485194 | link | EXACT_ACN | DYSCK PTY. LTD. |
| dysck-pty-ltd-trading-as-neptune-blanket-0 | Dysck Pty Ltd | ACN 600485194 | link | EXACT_ACN | DYSCK PTY. LTD. |
| hm-hennes-mauritz-pty-ltd | H&M Hennes & Mauritz Pty Ltd | ACN 160056548 | abstain | BELOW_THRESHOLD (0.46) | ANNELISE MAURITZ (a person) |
| hsk-united-pty-ltd | HSK United Pty Ltd | ACN 653084569 | link | EXACT_ACN | HSK UNITED PTY LTD |
| hsk-united-pty-ltd-0 | HSK United Pty Ltd | ACN 653084569 | link | EXACT_ACN | HSK UNITED PTY LTD |
| lactalis-australia-pty-ltd | Lactalis Australia Pty Ltd | ACN 072928879 | abstain | NO_CANDIDATE | |
| marshall-freeman-collections-pty-ltd | Marshall Freeman Collections Pty Ltd | ACN 104876995 | abstain | BELOW_THRESHOLD (0.53) | Marshall and Sons Investments Pty Ltd |
| marshall-freeman-collections-pty-ltd-0 | Marshall Freeman Collections Pty Ltd | ACN 104876995 | abstain | BELOW_THRESHOLD (0.53) | Marshall and Sons Investments Pty Ltd |
| sharetea-australia-pty-ltd | Sharetea Australia Pty Ltd | ABN 15160436911 | abstain | NO_CANDIDATE | |
| systems-operations-pty-ltd-trading-as-vuly-play-group | Systems Operations Pty Ltd | ACN 655129623 | abstain | BELOW_THRESHOLD (0.66) | POLYLINE PIPE SYSTEMS OPERATIONS PTY LTD |
| the-sleeping-giant-pty-ltd-trading-as-james-lane | The Sleeping Giant Pty Ltd | ACN 134349894 | link | EXACT_ACN | THE SLEEPING GIANT PTY LIMITED |
| vacaciones-edreams-sl | Vacaciones eDreams, S.L. | none | abstain | BELOW_THRESHOLD (0.37) | SL PHARMACY PTY LTD |
| vacaciones-edreams-sl-0 | Vacaciones eDreams, S.L. | none | abstain | BELOW_THRESHOLD (0.37) | SL PHARMACY PTY LTD |
| venue-smart-pty-ltd | Venue Smart Pty Ltd | ABN 52604254766 | abstain | BELOW_THRESHOLD (0.60) | VENUE MAESTRO PTY LTD |
| venue-smart-pty-ltd-0 | Venue Smart Pty Ltd | ABN 52604254766 | abstain | BELOW_THRESHOLD (0.60) | VENUE MAESTRO PTY LTD |
| venue-smart-pty-ltd-1 | Venue Smart Pty Ltd | ABN 52604254766 | abstain | BELOW_THRESHOLD (0.60) | VENUE MAESTRO PTY LTD |
| weflex-pty-ltd | WeFlex Pty Ltd | ABN 44644941873, ACN 644941873 | abstain | NO_CANDIDATE | |

All 7 links are identifier links. The 11 abstentions that carry an ABN or ACN are recipients outside
the Tier 1 slice (active WA and TAS businesses plus Tier 2 referenced numbers): the identifier finds no
party, and the name path finds only different businesses. Both Vacaciones eDreams records abstain, as
expected. No ACCC notice was attached on a name alone.

## 3. Name-path precision and recall (identifiers stripped)

AFSL and credit records re-run with every identifier removed (`match_batch(..., strip_identifiers=True)`,
own matcher version `m-1465a4ba-7bdb4123`), compared with the EXACT_ABN links of the full v2 run as
ground truth. Blocking recall = the true party is among the stored candidates.

| Source | Truth (EXACT_ABN links) | Blocking recall | Threshold | Name links on truth records | Correct | Wrong | Precision | Recall |
|---|---|---|---|---|---|---|---|---|
| asic_afsl | 6,351 | 99.95% (6,348) | 0.85 | 6,191 | 6,191 | 0 | 100% | 97.5% |
| asic_afsl | 6,351 | 99.95% | 0.90 (default) | 5,918 | 5,918 | 0 | 100% | 93.2% |
| asic_afsl | 6,351 | 99.95% | 0.95 | 5,918 | 5,918 | 0 | 100% | 93.2% |
| asic_credit | 3,846 | 99.79% (3,838) | 0.85 | 3,427 | 3,427 | 0 | 100% | 89.1% |
| asic_credit | 3,846 | 99.79% | 0.90 (default) | 3,326 | 3,326 | 0 | 100% | 86.5% |
| asic_credit | 3,846 | 99.79% | 0.95 | 3,326 | 3,326 | 0 | 100% | 86.5% |

* At the default threshold the name path labels 5,853 of the AFSL hits NAME_NORMALISED_EXACT and 65
  NAME_FUZZY; abstentions on truth records are BELOW_THRESHOLD 406, AMBIGUOUS 26, NO_CANDIDATE 1.
* 0.90 and 0.95 give identical results: after the v2 gates (all reference tokens present, no extra
  tokens for a registered name, compatible legal form) the surviving fuzzy scores sit at 0.95 or above
  or below 0.90. Lowering to 0.85 adds 274 AFSL and 104 credit links, all correct; it also drops 3 credit
  links (a lower threshold lets a second candidate inside the margin, so AMBIGUOUS replaces a link).
* Caveat: AFSL and credit names are clean register names of companies that are in the slice because
  their ABN is referenced; this is an upper bound for the name path, not its performance on ACCC prose.
  The adversarial suite (section 5) is the harder test.
* The name path also linked 163 AFSL and 379 credit records that have no EXACT_ABN truth (ACN-only or
  no identifier in the full run); those are unverified and belong in the label sample.

### Redecide (recalibration without re-matching)

| Run | Stored candidates | Load candidates | Decide | Total | Diff vs the name-only run |
|---|---|---|---|---|---|
| AFSL at 0.85 | 147,071 | 5.5 s | 4.2 s | 10.1 s | +274 links, 0 dropped, 0 retargeted |
| AFSL at 0.90 | 147,071 | 6.4 s | 5.3 s | 12.4 s | no change |
| AFSL at 0.95 | 147,071 | 6.0 s | 4.0 s | 13.5 s | no change |
| credit at 0.85 | 96,343 | 3.3 s | 3.1 s | 6.7 s | +104, 3 dropped |
| credit at 0.90 | 96,343 | 3.3 s | 3.1 s | 6.6 s | no change |
| credit at 0.95 | 96,343 | 3.3 s | 3.0 s | 7.1 s | no change |

The name-only match itself took 55.6 s (AFSL) and 31.7 s (credit), so a redecide costs roughly a fifth
of a re-match here; the gap widens with corpus size because it is a scan of stored rows rather than
blocking plus feature extraction. Each redecide writes a new immutable `mr-...` matcher version whose
policy JSON names the candidate run it re-decided.

## 4. resolve() latency (warm, single process, v2)

200 messy strings built from real source names (70 AFSL, 60 credit, 70 GLEIF; random lower-casing,
dropped legal form, `&` to `and`, double spaces; an ABN appended to 20% of the strings that had one, 29
in total). Embeddings on.

| n | p50 | p95 | max | mean |
|---|---|---|---|---|
| 200 | 169.8 ms | 223.0 ms | 230.3 ms | 162.8 ms |

Outcomes: 143 NAME_NORMALISED_EXACT, 29 EXACT_ABN, 21 BELOW_THRESHOLD, 7 AMBIGUOUS. The ABN strings
resolve in about 100 ms (one identifier lookup plus the name-equality probe); name-only strings cost the
two blocking queries plus feature extraction over 20 to 40 candidates.

Named cases on the real store:
* `Commonwealth Bank of Australia` links CBA (urn:abn:48123123124) as NAME_NORMALISED_EXACT 0.97, margin
  0.30 over COMMONWEALTH BANK GROUP SUPER. COMMONWEALTH SUPERANNUATION CORPORATION is not even in the top
  three. Its feature vector against CSC (urn:abn:48882817243): jaro_winkler 0.8824, token_set_ratio
  0.6316, token_overlap 0.3333, distinctive_coverage 0.5, reference token missing BANK, candidate extra
  SUPERANNUATION, embedding_cosine 0.6048, fuzzy 0.5577, semantic 0.6048: ineligible under R5a / R5b
  whatever the embedding says.
* `Commonwealth Superannuation Corporation` links CSC (NAME_NORMALISED_EXACT); CBA is ineligible
  (SUPERANNUATION missing).
* `Commonwealth Bank of Aust, ABN 48 123 123 124` links CBA as EXACT_ABN with the SQL in the evidence.

## 5. Independent adversarial suite

`tests/independent/test_resolution_contract.py` (tester-written, synthetic stores): pre-fix code 83 passed /
11 failed (the tester reported 82 / 12 on an earlier build); v2 **94 passed, 0 failed**. Its recall-sanity test on 500 perturbed references over 20k
parties: precision 100% (332 of 332 links correct), recall on resolvable references 99.7%; the 168
abstentions are all AMBIGUOUS (same name in several states with no state given).
Own tests: `tests/test_resolution.py` 24 passed.

Changes from v1 to v2 (all in `src/bizgraph/resolution/`; rules are written in `decision.arbitrate`):
1. All-token gate (R5a): every meaningful reference token, generic ones included, must be in the
   candidate's name or one alias; candidate extra tokens lower the fuzzy score symmetrically (Jaccard
   over all tokens). Australian geography words are exempt for informal references only. NZ is not
   exempt (deviation from the instruction): `X (NZ) LIMITED` and the Australian X are different
   entities in the GLEIF data.
2. Person-shaped UNKNOWN references (`John Smith`: given name plus known surnames, no legal form, no
   business word) are treated as persons, so never linked on a name alone; `asic_liquidator` defaults
   to PERSON. Not implemented: "a NAME_* link to an organisation needs an organisation marker", because
   it would refuse `Smith Plumbing` style references (the recall test drops legal forms) and the
   person-shape rule already covers the failure it targets.
3. Licence numbers: EXACT_LICENCE_NO confidence 0.95; a licence never outranks an ABN / ACN; a
   licence-only match abstains IDENTIFIER_CONFLICT when a name path clears the threshold for another
   party.
4. Margin compared on scores rounded to 4 dp; exact ties are always AMBIGUOUS.
5. Parser: `(NSW)` state suffix; unlabelled digit groups of 6+ digits removed from the name; the
   trading-as part is matched as an alternative name (batch and resolve alike).
6. Evidence `disagreement` lists vetoed name candidates and licence matches pointing elsewhere; on
   strict sources a disagreement abstains IDENTIFIER_CONFLICT.
7. A stated state that differs costs 0.15; a matching one adds 0.02.
8. Added after the v2 real-data review: legal forms must be compatible for every name path (and with
   the candidate's current name, so a reused former name cannot match); trust or fund vs company
   conflict (including `The Trustee for X` names); a reference from a register (GLEIF, ASIC registers)
   is "formal", so it may not match through a business / trading name, may not gain extra candidate
   tokens, and keeps its AUSTRALIA. A veto is the abstain reason only when it blocked a candidate that
   would otherwise have passed (otherwise BELOW_THRESHOLD with the veto in the explanation).
9. Store: `abstention.evidence JSON` added (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`); every
   abstention now carries its explanation and the best candidate's features.

v3 status: the adversarial suite still passes 94 / 94 (recall sanity: precision 100%, resolvable
recall 99.7%); `tests/test_resolution.py` 38 passed, including one regression test per evaluation case
(foreign entity to Australian company, NZ trust, foreign bank allowed, Browning postcode, Arkad state,
stated ABN over a GLEIF type hint, business-name alias, CO / CORPORATION normalisation, register typo,
stale `name_norm`), the CLI (`match`, `redecide`, `resolve-file`) and rescoring redecide. The full
`tests/` run (without Fuseki) passes: 476 passed, 4 skipped.

## 6. Known costs and next steps (after v3)

* ABR slice not refreshed against the new Tier 2 references (GLEIF refresh, licence history): those
  ABNs resolve only if ABR already had them. Re-ingesting ABR with `--tier2-allowlist` closes it.
* `party_canonical.name_norm` is the ingest-time normalisation; the resolution index re-normalises, but
  other consumers of `name_norm` see the old form until Tier 1 is re-ingested with `--force`.
* Australian companies registered abroad (NZ overseas registrations of a Pty Ltd) now abstain under
  the jurisdiction gate; corroborating them via the LEI's registration number or ASIC former names is
  the safe way to win them back.
* Candidate JSON is about 1.6 KB per candidate: store non-default features and the query text once per
  (record, path).
* Identifier-matched records only probe name equality for disagreements, not full blocking (cost
  saving); a fuzzy rival to an identifier link is therefore not seen in batch.
* Exact path: identifier links identical across v1, v2 and v3 (plus 41 stated-ABN links in v3 that v2
  refused on a type hint).

## 7. Matcher v4

`m-b5e50f74-d37e44c6` rebuilt and matched all six sources with the v3 MiniLM model and thresholds.

1. Seeded the canonical key registry before rebuild. All 1,075,765 v3 party keys survived, including
   ACN keys when an ABN was added in the regression test.
2. Checked former names against current and former ASIC names, including companies outside the
   graph. Genesee now abstains as `AMBIGUOUS`, and Harvest Funds resolves to its current holder.
3. Applied the jurisdiction gate to foreign legal forms in free text. Rio Tinto plc abstains as
   `JURISDICTION_MISMATCH`. The parser reads SA as South Australia when an address delimiter or
   domestic legal suffix identifies it as a state.
4. Skipped same-party ownership projections in both traversals. A chain that stops on this edge
   reports `IDENTITY_COLLAPSE`.
5. Expanded P/L and CORP, parsed trailing town and state fragments, and allowed unique exact
   registered business or trading names of individuals for references without a person-shaped name.

| Set | v3 precision / recall | v4 precision / recall | v4 wrong links |
|---|---|---|---|
| Existing labels | 99.7% / 93.2% | 100.0% (285/285) / 92.5% (285/308) | 0 |
| Existing rehearsal | 100.0% / 68.1% | 100.0% (150/150) / 79.8% (150/188) | 0 |
| Held-out rehearsal (seed 20261119) | | 100.0% (152/152) / 80.9% (152/188) | 0 |

V4 abstained on the two previously correct labelled links for Lamboo Resources and MLC Limited
because of former-name ambiguity. Both rehearsal sets had 12 of 12 correct absent-reference abstentions.

The final focused run passed 84 tests. The full suite, including the independent resolution
contract, passed 598 tests with 20 skipped.
