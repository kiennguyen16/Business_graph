## Notes (hand-written; the tables above are regenerated from the labels, this text is not)

### N0. Headline for v3 (`m-94f4f6b2-d37e44c6`)

* **1 wrong link in 288 labelled links** (precision 99.7%, Wilson 98.1 to 99.9). Recall 93.2% over 308 labelled
  records whose true party is in the graph. Every identifier link checked (132) is right, and so is every one of
  the 169 v3 GLEIF name links were labelled (a census): 155 correct, 1 wrong, 13 UNSURE (mostly foreign branches).
* The wrong link: GLEIF `Genesee & Wyoming Australia Pty Ltd` (LEI registered 2015, Keswick, Adelaide) linked by a
  *former name* to ARC INFRASTRUCTURE HOLDINGS NO 1 PTY LTD (WA). Two companies have held that name: ACN 080579308
  (the WA company, briefly around 2006) and ACN 079444296 (Adelaide, the name holder until 2022, now AURIZON BULK
  CENTRAL PTY LTD, not in the graph). The LEI's date and address point to the Adelaide company.
* The misses are concentrated and explainable (section 3): 8 AFSL licensees who are people, listed in the older
  "LAST, GIVEN" format on ended licences, abstain PARTY_TYPE_CONFLICT although the register prints their ABN; 4
  Australian companies registered abroad that the new jurisdiction gate refuses (the cost the v2 evaluation
  predicted); 6 trusts and funds refused by the new trust gates (5 GLEIF, 1 credit); persons never linked on a
  name (policy).
* Weighted to the population, v3 precision and recall are both above 99.5% because identifier links dominate; the
  name-path and abstention strata are where the labels were concentrated.

### N1. What the evaluation caught in v2, and what v3 did with it

The v2 evaluation (`m-1465a4ba-e5444596`, blind sample of 171 plus a census of 71; full report kept as
`outputs/evaluation_v2_m-1465a4ba-e5444596.md`) found the GLEIF name path unsafe:

* **44 wrong links in the labelled set, all GLEIF name links**, 42 of them among the 75 name links from LEIs whose
  legal jurisdiction is not Australia: 27 New Zealand family trusts linked to WA / TAS trusts of the same name; RIO
  TINTO PLC to RIO TINTO LIMITED; BHP Billiton Finance plc; STUDIOCANAL; Irish VanEck; Singapore Civmec; NZ
  Stanwell, BOC, Eaton; THE TORO COMPANY and Prism Global Group Plc through another company's alias. Two more were
  Australian same-name trusts (Browning Family Super 6210 linked to the fund in 6023; Arkad Trust SA linked to TAS).
* **41 sole-trader records refused although the stated ABN matched** (all v2 GLEIF PARTY_TYPE_CONFLICT abstentions,
  a population query).
* **Normaliser collisions** (WT FINANCE CO / WT FINANCE; SIMPLY CORPORATION / SIMPLY).

The evaluation recommended a jurisdiction gate, no NZ-trust-to-AU-trust links, postcode agreement for trusts, ABN over
type hint, and normaliser fixes (v2 notes N7). v3 implemented them. Scored on the same labels (section 2, comparison
table): v2 had 44 wrong of 295 links on these records; v3 has 1 wrong of 288. On the 75-record foreign census v3 makes
**0 wrong links**: 25 correct links remain (foreign banks and companies registered here, an AU company with a
mis-coded country), the rest abstain JURISDICTION_MISMATCH or below threshold. The 4 correct links the evaluation said
the gate would lose (Siegel, Revolut Payments NZ, MECS, GE Energy Optimization) are lost, as predicted. All 23 sampled
sole-trader EXACT_ABN links that moved from PARTY_TYPE_CONFLICT are correct.

### N2. How the labels were built

* **Two blind rounds.** Round 1 (v2): 171 records drawn on v2's strata. Round 2 (v3): `eval-sample --plan topup
  --exclude-labelled` drew 221 new records on v3's own strata: every v3 GLEIF name link not already labelled (136; with
  the 33 already labelled this covers all 169), 20 JURISDICTION_MISMATCH abstentions, 20 sole-trader EXACT_ABN links
  (segment `au-person-abn`), 20 exact links and 10 abstentions on ended AFSL / credit licences (segment `ended`), 5 AFSL
  PARTY_TYPE_CONFLICT, the 2 AMBIGUOUS and 8 near-threshold GLEIF abstentions. Both rounds were labelled from the
  blind file only (reference, candidate list without scores, register facts); the decisions file was joined after.
* **One non-blind census** (71 v2 foreign-jurisdiction name links, round 1), flagged `NOT blind` in the labeller column.
* **Label values**: a canonical key; `NOT_IN_GRAPH` (a real Australian-registered entity outside this graph);
  `NONE` (no Australian entity: NZ trusts, foreign companies without an Australian registration); `UNSURE`
  (24, excluded). Recall counts only keys.
* **Rules applied**: a stated identifier is truth when the register entry agrees on name or former name; a foreign
  company's Australian registration (FNOS / ARBN, or an ABR "Other Incorporated Entity" of the same name) is the same
  legal person as its head-office LEI; a GLEIF branch registered abroad is UNSURE (modelling question); renamed
  companies are the same party (ASIC former names); subsidiaries, siblings, dual-listed twins and companies that reused
  a deregistered company's name are different; trusts and funds of a common name need postcode agreement; a GLEIF
  legal name of the form "X Pty Ltd" filed with that company's ACN is labelled as the company even when GLEIF's legal
  form says trust (human check advised, listed in section 6 of this note).
* **Corrections after the join, all disclosed in the evidence column ("AMENDED")**. Round 1: two blind labels moved
  to UNSURE (Hart Superannuation Fund, 43 Degrees South). Round 2: five labels, found by joining the 6 rows where v3
  disagreed with my label and then auditing *every* NONE / NOT_IN_GRAPH label against the blind file uniformly. Three
  moved to the matcher's answer (L1 Capital Global Long Short Fund, TriMas Corporation renamed AutoPacific Australia,
  Sanofi-Aventis Healthcare renamed Opella Healthcare) and two to UNSURE (Phil Asker Pty Ltd, a 2017 name swap between
  two companies; UniSuper, fund or trustee company). In all five the blind file *did* list the right candidate; my
  compact viewer had hidden the alias column ("former name") or truncated the list. This is a labeller error, not a
  sampler gap, and it inflated the apparent v3 error count from 1 to 6 before the audit. The audit found no other
  NONE / NOT_IN_GRAPH label with a non-trust exact-name or former-name candidate.
* **Limits.** One AI labeller, no second rater. Trust identity rests on name plus postcode (the ABR does not publish
  trustees). The post-join corrections show the labeller makes mistakes in the direction of "not in graph" when a
  company has been renamed; a human should re-check the renamed-company labels first. NZ register facts were not
  checked against the NZ Companies Office.

### N3. Thresholds

Policy of v3 (from `matcher_version.policy`, unchanged from v2): name path **0.90** with a 0.05 margin; **0.97 with a
0.10 margin** for ACCC notices and banned organisations; 0.95 for references of unknown party type; persons never
linked on a name; identifier links not thresholded. All metrics are at these thresholds. The sweep (section 5) shows
0.85, 0.90 and 0.95 give identical AFSL / credit name-only results: after the v3 gates the name scores are bimodal, so
the threshold no longer moves anything in this range, and the remaining v3 error is a gate case (a reused former
name) that no threshold would fix. The v3 rescoring redecide `mr-94f4f6b2-f3b4d9f4` (register-state penalty 0.15)
also scores 0 wrong on the labels, at a recall cost (section 2).

### N4. Identifier coverage per Tier 2 source (`outputs/identifier_coverage.md`, current-file records)

| Source | Records | ABN | ACN (any) | ABN or ACN | Other keys | No business key |
|---|---|---|---|---|---|---|
| asic_afsl | 6,551 | 96.9% | 97.3% | 99.5% | AFSL 100%, ARBN 0.4% | 2 |
| asic_credit | 4,308 | 89.3% | 89.9% | 98.3% | ACL 100%, AFSL 7.2% | 74 (69 persons) |
| asic_banned_org | 15 | 0% | 100% | 100% | none | 0 |
| asic_liquidator | 660 | 0% | 0% | 0% | liquidator no. 100% | 660 (all persons) |
| gleif_l1, AU entities | 54,082 | 26.2% | 63.1% | 89.3% | LEI 100%, ARSN 4.8% | 0 |
| gleif_l1, NZ entities | 4,281 | 0% | 0% | 0% | NZBN 24.0%, NZ co. no. 30.8% | 0 |
| accc_notice (Tier 3) | 20 | 6 state an ABN | 15 state an ACN | 18 of 20 | none | 2 |

v3 adds ended licences from the history captures (AFSL 6,949 licences, credit 4,606); the labelled exact links on
ended licences (20) are all correct.

### N5. Blocking key and its recall cost

* **Key**: first distinctive token plus state (state ignored when either side lacks it), top 20 by Jaro-Winkler,
  blocks over 20,000 skipped; IDF full-text retrieval, top 20, tokens with document frequency over 5,000 ignored;
  exact identifier and exact normalised-name probes.
* **Measured on the identifier-stripped v3 run** (truth = ABN, else ACN, printed on the register record; section 5):
  blocking recall **99.39% AFSL, 98.48% credit** (v2: 99.95% / 99.8% on current licences only). The drop comes from
  the ended-licence records added in v3, many of them people in the older "LAST, GIVEN" format, whose name tokens
  do not block against the "GIVEN LAST" ABR names.
* **Own check on labelled records**: the true party was among v3's stored candidates for 308 of 308 labelled in-graph
  records, so no labelled miss of v3 is a blocking miss.
* **Stale keys** (found by this evaluation): the identifier-stripped run and its three redecides were made before the
  canonical rebuild, and 407 of their 10,662 link targets no longer exist (party keys are minted from the strongest
  identifier, so a party that gained an ABN was re-minted from `urn:acn:` to `urn:abn:`). The evaluation maps them to
  the current party through the identifier table and reports the count. Before the remap they looked like 408 wrong
  links; after it, 1 (below). The matcher should either keep keys stable across rebuilds or re-key stored decisions,
  because a redecide over stored candidates after a rebuild writes dangling links.
* **One real name-only error**: AFSL licensee HARVEST FUNDS PTY LTD (printed ABN 60635352706) linked by name to
  ZENOBIA CAPITAL PTY LTD, whose *former* name is HARVEST FUNDS PTY LTD, while the current holder of the name is in
  the graph. Same class as the v3 Genesee error.

### N6. Confusion cases on v3

* **Commonwealth Bank of Australia vs Commonwealth Superannuation Corporation** (`bizgraph --db
  data/snap_v3_eval.duckdb resolve`, v3 code): "Commonwealth Bank of Australia" resolves to urn:abn:48123123124 CBA,
  NAME_NORMALISED_EXACT 0.97, margin 0.30; CSC is not among the candidates. "Commonwealth Superannuation Corporation"
  resolves to urn:abn:48882817243 CSC with CBA not a candidate. **Pass.**
* **Banned and disqualified organisations**: 12 EXACT_ACN links, all correct; 3 abstentions, all correctly not in the
  graph. No decision on a name. **Pass, unchanged since v1.**
* **ACCC notices (Tier 3)**: 7 EXACT_ACN links correct, 13 abstentions correct (SYSTEMS OPERATIONS vs POLYLINE PIPE
  SYSTEMS OPERATIONS, COTTON ON AUSTRALIA vs COTTON ON FINANCE refused). **Pass.**
* **Reused former names** (the v3 error class): Genesee & Wyoming Australia (wrong link), Harvest Funds (wrong in the
  name-only run), Phil Asker Pty Ltd (2017 name swap, UNSURE). A name that is a current name of one company and a
  former name of another, or a former name of two companies, should abstain unless the reference's date or address
  separates them.
* **Renamed companies** are now handled well: TriMas, Sanofi-Aventis Healthcare, Brookfield Rail, Gerling, MLC
  Limited, Telvent, FMC Technologies, Lamboo Resources, Jervois Mining, Surtron all link to the renamed company.
* **GLEIF branches registered abroad** (ANZ Paris, Macquarie London, QBE France, Beiersdorf NZ, Komatsu NZ, CMC NZ,
  Po Valley Italy) are linked to the Australian head company. A branch is the same legal person, but the link makes
  the graph say the Australian company holds the foreign branch's LEI. Labelled UNSURE; this needs a modelling
  decision (a branch node with IS_INTERNATIONAL_BRANCH_OF), not a threshold.

### N7. What the matcher should change next

1. **Former-name ambiguity**: when the matched name is a former name, check that no other party (in or out of the
   graph, via the ASIC register's former names) holds or held it; prefer the current holder; abstain when the
   reference's registration date or address points elsewhere. Fixes the one v3 error and the name-only error.
2. **ABN beats a type hint for AFSL / credit too**: 13 ended AFSL licences (people listed as "LAST, GIVEN") abstain
   PARTY_TYPE_CONFLICT although the printed ABN is the person's (8 of 8 sampled are correct parties). Apply R1c to the
   licence registers, or parse "LAST, GIVEN" as a person in the history files.
3. **Stable keys**: never re-mint a canonical key on rebuild (keep the first key and add the ABN as an identifier), or
   re-key `link`, `abstention` and `candidate` in the same transaction.
4. **Foreign branches**: decide the model; until then abstain on BRANCH LEIs registered outside Australia.
5. **Trust gates**: 6 labelled misses are correct parties refused by the trust / fund gates (MPF Diversified Fund
   No.2, PAC Global Esports Fund, Marketing Seven Trust, Eilistraee No 2 Trust, RM Linton Family Trust: postcodes
   differ within the same city; Browning Family Super: the right fund shares the postcode but v3 abstains). Allow an
   adjacent or same-city postcode for distinctive names.

### N8. Rows a human should verify first (short list)

1. The 19 ACCC and banned-organisation links (section 6, item 1): each is an accusation if wrong.
2. The v3 wrong link `S0c558d8bb5` (Genesee & Wyoming) and the five round-2 amendments: `S448132864a`,
   `Sac1b703b42`, `S4b414a1935`, `S4e1d59192b`, `S6c778ae0f2`.
3. The "Pty Ltd filed as trustee" convention rows: `S1e17e28972`, `S037333463d`, `S14db34ebf4`, `S21be7a0738`,
   `S4287efcbf8`, `S4427fed5ba`.
4. Ten of the 71 non-blind census rows labelled as a party (foreign-company registrations).
