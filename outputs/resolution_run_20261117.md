# Resolution run, 2026-11-17 (draft)

Store: `data/bizgraph.duckdb` (1,075,216 canonical parties: 580,501 organisations, 494,715 persons;
1,331,833 identifier rows; 575,572 aliases; 69 quarantine rows). Engine: `src/bizgraph/resolution/`.
DuckDB `memory_limit='5GB'`, `threads=4`; embeddings `sentence-transformers/all-MiniLM-L6-v2` on CPU,
loaded once per process and computed only where the semantic path may apply. All numbers below are
**measured** on this machine unless marked otherwise. Draft for the evaluation agent: precision here
is against identifier ground truth or eyeballed, not against hand labels.

Two matcher versions are kept side by side in the store:

| | v1 (baseline) | v2 (current) |
|---|---|---|
| matcher_version | `m-dabec5ea-d900271d` | `m-1465a4ba-e5444596` |
| What changed | first full-scale run | fixes after an independent adversarial test suite (below) |
| Name-only / redecide / latency measured | no (v1 code no longer exists) | yes |

Earlier interim v2 builds were run and deleted (their numbers are not reported). v2 required a full
re-match, not a redecide: it changes **features** (new token features) and **scorers**, and only
policy changes can be replayed from stored candidates. That is the reprocess-economics data point:
GLEIF (59,606 records) re-matched in 135 s, while a policy change over 147k stored AFSL candidates
re-decides in 10 s without touching candidate generation or features.

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

## 6. Known costs and next steps

* Stated-state penalty on register data: GLEIF's state (legal address) and ABR's state (main business
  location) differ for some trusts, which now drop to 0.85 (65 of the lost v1 links, several correct).
  Using 0.15 only for a user-stated state and a smaller penalty for register-derived states would win
  them back. Because scores are stored, not recomputed, this needs a re-match today; recomputing
  scores from stored features inside `redecide` would make scorer changes as cheap as policy changes.
* Candidate JSON repeats the reference block per row (about 1.6 KB per candidate); store the reference
  once per record.
* Identifier-matched records only probe name equality for disagreements, not full blocking (cost
  saving); a fuzzy rival to an identifier link is therefore not seen in batch.
* Exact path unaffected by any of this: 100% of v2 identifier links equal v1.
