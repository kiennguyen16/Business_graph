# Evaluation of matcher version `m-b5e50f74-d37e44c6`


## 1. Sample and labels

463 labelled records: 392 labelled blind (evidence file only, no score or decision), 71 labelled in a census that was not blind (see notes, section N2). UNSURE: 24, excluded from every metric.

| source | NONE | NOT_IN_GRAPH | UNSURE | party in graph | total |
|---|---|---|---|---|---|
| accc_notice | 2 | 11 | 0 | 7 | 20 |
| asic_afsl | 0 | 7 | 0 | 43 | 50 |
| asic_banned_org | 0 | 3 | 0 | 12 | 15 |
| asic_credit | 0 | 7 | 1 | 36 | 44 |
| asic_liquidator | 0 | 2 | 0 | 1 | 3 |
| gleif_l1 | 72 | 27 | 23 | 209 | 331 |


Strata of `m-b5e50f74-d37e44c6` that hold labelled records (stratum = source | decision | match type or abstain reason | score band | segment; segment: GLEIF `foreign` (legal jurisdiction not AU), `au-person-abn` (stated ABN is a sole trader) or `au`; AFSL / credit `ended` or `current` licence):

| stratum | population | labelled |
|---|---|---|
| accc_notice\|abstain\|BELOW_THRESHOLD\|far\| | 10 | 10 |
| accc_notice\|abstain\|NO_CANDIDATE\|none\| | 3 | 3 |
| accc_notice\|link\|EXACT_ACN\|id\| | 7 | 7 |
| asic_afsl\|abstain\|AMBIGUOUS\|near0.05\|current | 2 | 1 |
| asic_afsl\|abstain\|BELOW_THRESHOLD\|far\|current | 30 | 4 |
| asic_afsl\|abstain\|BELOW_THRESHOLD\|far\|ended | 4 | 2 |
| asic_afsl\|abstain\|PARTY_TYPE_CONFLICT\|far\|ended | 13 | 8 |
| asic_afsl\|link\|EXACT_ABN\|id\|current | 6351 | 19 |
| asic_afsl\|link\|EXACT_ABN\|id\|ended | 365 | 10 |
| asic_afsl\|link\|EXACT_ACN\|id\|current | 168 | 6 |
| asic_banned_org\|abstain\|BELOW_THRESHOLD\|far\| | 3 | 3 |
| asic_banned_org\|link\|EXACT_ACN\|id\| | 12 | 12 |
| asic_credit\|abstain\|BELOW_THRESHOLD\|far\|current | 58 | 1 |
| asic_credit\|abstain\|BELOW_THRESHOLD\|far\|ended | 3 | 2 |
| asic_credit\|abstain\|BELOW_THRESHOLD\|near0.05\|current | 15 | 2 |
| asic_credit\|abstain\|BELOW_THRESHOLD\|near0.05\|ended | 1 | 1 |
| asic_credit\|abstain\|BELOW_THRESHOLD\|near0.10\|current | 1 | 1 |
| asic_credit\|abstain\|BELOW_THRESHOLD\|near0.10\|ended | 1 | 1 |
| asic_credit\|abstain\|NO_CANDIDATE\|none\|current | 1 | 1 |
| asic_credit\|abstain\|NO_CANDIDATE\|none\|ended | 1 | 1 |
| asic_credit\|link\|EXACT_ABN\|id\|current | 3846 | 18 |
| asic_credit\|link\|EXACT_ABN\|id\|ended | 272 | 10 |
| asic_credit\|link\|EXACT_ACN\|id\|current | 387 | 6 |
| asic_liquidator\|abstain\|BELOW_THRESHOLD\|far\| | 624 | 1 |
| asic_liquidator\|abstain\|BELOW_THRESHOLD\|near0.05\| | 22 | 2 |
| gleif_l1\|abstain\|AMBIGUOUS\|near0.05\|au | 7 | 6 |
| gleif_l1\|abstain\|BELOW_THRESHOLD\|far\|au | 4558 | 13 |
| gleif_l1\|abstain\|BELOW_THRESHOLD\|far\|foreign | 4752 | 6 |
| gleif_l1\|abstain\|BELOW_THRESHOLD\|near0.05\|au | 543 | 15 |
| gleif_l1\|abstain\|BELOW_THRESHOLD\|near0.10\|au | 260 | 1 |
| gleif_l1\|abstain\|BELOW_THRESHOLD\|near0.10\|foreign | 158 | 1 |
| gleif_l1\|abstain\|IDENTIFIER_CONFLICT\|near0.05\|au | 3 | 3 |
| gleif_l1\|abstain\|JURISDICTION_MISMATCH\|near0.05\|foreign | 259 | 73 |
| gleif_l1\|abstain\|NO_CANDIDATE\|none\|foreign | 610 | 3 |
| gleif_l1\|link\|EXACT_ABN\|id\|au | 13908 | 10 |
| gleif_l1\|link\|EXACT_ABN\|id\|au-person-abn | 248 | 23 |
| gleif_l1\|link\|EXACT_ACN\|id\|au | 33809 | 12 |
| gleif_l1\|link\|NAME_FUZZY\|0.95-0.97\|au | 6 | 6 |
| gleif_l1\|link\|NAME_FUZZY\|0.95-0.97\|foreign | 1 | 1 |
| gleif_l1\|link\|NAME_FUZZY\|ge0.97\|au | 14 | 14 |
| gleif_l1\|link\|NAME_NORMALISED_EXACT\|ge0.97\|au | 120 | 119 |
| gleif_l1\|link\|NAME_NORMALISED_EXACT\|ge0.97\|foreign | 25 | 25 |


8 strata with 428 decisions have no labelled record (mostly exact-path strata and small bands); they do not enter the weighted estimates. Top by size:

| stratum | population |
|---|---|
| gleif_l1\|abstain\|NO_CANDIDATE\|none\|au | 326 |
| gleif_l1\|abstain\|BELOW_THRESHOLD\|near0.05\|foreign | 50 |
| asic_credit\|link\|EXACT_ACN\|id\|ended | 20 |
| asic_afsl\|link\|EXACT_ACN\|id\|ended | 16 |
| asic_liquidator\|abstain\|BELOW_THRESHOLD\|near0.10\| | 11 |
| asic_liquidator\|abstain\|NO_CANDIDATE\|none\| | 2 |
| gleif_l1\|link\|EXACT_ABN\|id\|foreign | 2 |
| asic_liquidator\|abstain\|PARTY_TYPE_CONFLICT\|near0.05\| | 1 |


## 2. Precision and recall

Precision = links to the labelled true party / links. Recall = links to the true party / records whose true party is in the graph (NONE and NOT_IN_GRAPH records are not in the recall denominator; an abstention on them is correct). `sample` columns are raw counts in the labelled sample with Wilson 95% intervals. `weighted` re-weights each labelled record by population / labelled of its stratum (post-stratification), so oversampled strata (near-threshold abstentions, the foreign census) do not dominate; strata with no labelled record are missing from it.

### By source pair

| source_pair | labelled | links | correct | wrong | precision (95% CI) | true target in graph | missed | recall (95% CI) | weighted P / R |
|---|---|---|---|---|---|---|---|---|---|
| accc_notice->abr | 7 | 7 | 7 | 0 | 100.0% (64.6 to 100.0) | 7 | 0 | 100.0% (64.6 to 100.0) | 100.0% / 100.0% |
| accc_notice->none | 13 | 0 | 0 | 0 | n/a (n/a) | 0 | 0 | n/a (n/a) | n/a / n/a |
| asic_afsl->abr | 38 | 30 | 30 | 0 | 100.0% (88.6 to 100.0) | 38 | 8 | 78.9% (63.7 to 88.9) | 100.0% / 99.8% |
| asic_afsl->asic_company | 5 | 5 | 5 | 0 | 100.0% (56.6 to 100.0) | 5 | 0 | 100.0% (56.6 to 100.0) | 100.0% / 100.0% |
| asic_afsl->none | 7 | 0 | 0 | 0 | n/a (n/a) | 0 | 0 | n/a (n/a) | n/a / n/a |
| asic_banned_org->abr | 12 | 12 | 12 | 0 | 100.0% (75.7 to 100.0) | 12 | 0 | 100.0% (75.7 to 100.0) | 100.0% / 100.0% |
| asic_banned_org->none | 3 | 0 | 0 | 0 | n/a (n/a) | 0 | 0 | n/a (n/a) | n/a / n/a |
| asic_credit->abr | 30 | 27 | 27 | 0 | 100.0% (87.5 to 100.0) | 30 | 3 | 90.0% (74.4 to 96.5) | 100.0% / 99.6% |
| asic_credit->asic_company | 6 | 6 | 6 | 0 | 100.0% (61.0 to 100.0) | 6 | 0 | 100.0% (61.0 to 100.0) | 100.0% / 100.0% |
| asic_credit->none | 7 | 0 | 0 | 0 | n/a (n/a) | 0 | 0 | n/a (n/a) | n/a / n/a |
| asic_liquidator->abr | 1 | 0 | 0 | 0 | n/a (n/a) | 1 | 1 | 0.0% (0.0 to 79.3) | n/a / 0.0% |
| asic_liquidator->none | 2 | 0 | 0 | 0 | n/a (n/a) | 0 | 0 | n/a (n/a) | n/a / n/a |
| gleif_l1->abr | 197 | 186 | 186 | 0 | 100.0% (98.0 to 100.0) | 197 | 11 | 94.4% (90.3 to 96.9) | 100.0% / 99.3% |
| gleif_l1->asic_company | 12 | 12 | 12 | 0 | 100.0% (75.7 to 100.0) | 12 | 0 | 100.0% (75.7 to 100.0) | 100.0% / 100.0% |
| gleif_l1->none | 99 | 0 | 0 | 0 | n/a (n/a) | 0 | 0 | n/a (n/a) | n/a / n/a |


### By tier

| tier | labelled | links | correct | wrong | precision (95% CI) | true target in graph | missed | recall (95% CI) | weighted P / R |
|---|---|---|---|---|---|---|---|---|---|
| tier 2 | 419 | 278 | 278 | 0 | 100.0% (98.6 to 100.0) | 301 | 23 | 92.4% (88.8 to 94.9) | 100.0% / 99.5% |
| tier 3 | 20 | 7 | 7 | 0 | 100.0% (64.6 to 100.0) | 7 | 0 | 100.0% (64.6 to 100.0) | 100.0% / 100.0% |


### By tier and path (exact vs name)

| tier | source | path_group | labelled | links | correct | wrong | precision (95% CI) | true target in graph | missed | recall (95% CI) | weighted P / R |
|---|---|---|---|---|---|---|---|---|---|---|---|
| tier 2 | asic_afsl | abstain | 15 | 0 | 0 | 0 | n/a (n/a) | 8 | 8 | 0.0% (0.0 to 32.4) | n/a / 0.0% |
| tier 2 | asic_afsl | exact | 35 | 35 | 35 | 0 | 100.0% (90.1 to 100.0) | 35 | 0 | 100.0% (90.1 to 100.0) | 100.0% / 100.0% |
| tier 2 | asic_banned_org | abstain | 3 | 0 | 0 | 0 | n/a (n/a) | 0 | 0 | n/a (n/a) | n/a / n/a |
| tier 2 | asic_banned_org | exact | 12 | 12 | 12 | 0 | 100.0% (75.7 to 100.0) | 12 | 0 | 100.0% (75.7 to 100.0) | 100.0% / 100.0% |
| tier 2 | asic_credit | abstain | 10 | 0 | 0 | 0 | n/a (n/a) | 3 | 3 | 0.0% (0.0 to 56.2) | n/a / 0.0% |
| tier 2 | asic_credit | exact | 33 | 33 | 33 | 0 | 100.0% (89.6 to 100.0) | 33 | 0 | 100.0% (89.6 to 100.0) | 100.0% / 100.0% |
| tier 2 | asic_liquidator | abstain | 3 | 0 | 0 | 0 | n/a (n/a) | 1 | 1 | 0.0% (0.0 to 79.3) | n/a / 0.0% |
| tier 2 | gleif_l1 | abstain | 110 | 0 | 0 | 0 | n/a (n/a) | 11 | 11 | 0.0% (0.0 to 25.9) | n/a / 0.0% |
| tier 2 | gleif_l1 | exact | 45 | 45 | 45 | 0 | 100.0% (92.1 to 100.0) | 45 | 0 | 100.0% (92.1 to 100.0) | 100.0% / 100.0% |
| tier 2 | gleif_l1 | name | 153 | 153 | 153 | 0 | 100.0% (97.6 to 100.0) | 153 | 0 | 100.0% (97.6 to 100.0) | 100.0% / 100.0% |
| tier 3 | accc_notice | abstain | 13 | 0 | 0 | 0 | n/a (n/a) | 0 | 0 | n/a (n/a) | n/a / n/a |
| tier 3 | accc_notice | exact | 7 | 7 | 7 | 0 | 100.0% (64.6 to 100.0) | 7 | 0 | 100.0% (64.6 to 100.0) | 100.0% / 100.0% |


### By match type (links only)

| source | outcome | labelled | links | correct | wrong | precision (95% CI) | true target in graph | missed | recall (95% CI) | weighted P / R |
|---|---|---|---|---|---|---|---|---|---|---|
| accc_notice | EXACT_ACN | 7 | 7 | 7 | 0 | 100.0% (64.6 to 100.0) | 7 | 0 | 100.0% (64.6 to 100.0) | 100.0% / 100.0% |
| asic_afsl | EXACT_ABN | 29 | 29 | 29 | 0 | 100.0% (88.3 to 100.0) | 29 | 0 | 100.0% (88.3 to 100.0) | 100.0% / 100.0% |
| asic_afsl | EXACT_ACN | 6 | 6 | 6 | 0 | 100.0% (61.0 to 100.0) | 6 | 0 | 100.0% (61.0 to 100.0) | 100.0% / 100.0% |
| asic_banned_org | EXACT_ACN | 12 | 12 | 12 | 0 | 100.0% (75.7 to 100.0) | 12 | 0 | 100.0% (75.7 to 100.0) | 100.0% / 100.0% |
| asic_credit | EXACT_ABN | 27 | 27 | 27 | 0 | 100.0% (87.5 to 100.0) | 27 | 0 | 100.0% (87.5 to 100.0) | 100.0% / 100.0% |
| asic_credit | EXACT_ACN | 6 | 6 | 6 | 0 | 100.0% (61.0 to 100.0) | 6 | 0 | 100.0% (61.0 to 100.0) | 100.0% / 100.0% |
| gleif_l1 | EXACT_ABN | 33 | 33 | 33 | 0 | 100.0% (89.6 to 100.0) | 33 | 0 | 100.0% (89.6 to 100.0) | 100.0% / 100.0% |
| gleif_l1 | EXACT_ACN | 12 | 12 | 12 | 0 | 100.0% (75.7 to 100.0) | 12 | 0 | 100.0% (75.7 to 100.0) | 100.0% / 100.0% |
| gleif_l1 | NAME_FUZZY | 20 | 20 | 20 | 0 | 100.0% (83.9 to 100.0) | 20 | 0 | 100.0% (83.9 to 100.0) | 100.0% / 100.0% |
| gleif_l1 | NAME_NORMALISED_EXACT | 133 | 133 | 133 | 0 | 100.0% (97.2 to 100.0) | 133 | 0 | 100.0% (97.2 to 100.0) | 100.0% / 100.0% |


### GLEIF name-path links by jurisdiction segment

| segment | labelled | links | correct | wrong | precision (95% CI) | true target in graph | missed | recall (95% CI) | weighted P / R |
|---|---|---|---|---|---|---|---|---|---|
| au | 128 | 128 | 128 | 0 | 100.0% (97.1 to 100.0) | 128 | 0 | 100.0% (97.1 to 100.0) | 100.0% / 100.0% |
| foreign | 25 | 25 | 25 | 0 | 100.0% (86.7 to 100.0) | 25 | 0 | 100.0% (86.7 to 100.0) | 100.0% / 100.0% |


Overall (all labelled, sample counts): 285 links, 0 wrong, precision 100.0% (98.7 to 100.0); recall 92.5% over 308 in-graph records.


### The same labels against other matcher versions

Sample counts on every labelled record each version decided. The label sample was drawn on v2's and then v3's strata, so these rows compare versions on the same records; they are not population estimates for the other versions.

| version | subset | labelled | links | wrong | precision (95% CI) | missed | recall (95% CI) |
|---|---|---|---|---|---|---|---|
| m-b5e50f74-d37e44c6 | all | 439 | 285 | 0 | 100.0% (98.7 to 100.0) | 23 | 92.5% (89.0 to 95.0) |
| m-b5e50f74-d37e44c6 | exact | 132 | 132 | 0 | 100.0% (97.2 to 100.0) | 0 | 100.0% (97.2 to 100.0) |
| m-b5e50f74-d37e44c6 | name links | 153 | 153 | 0 | 100.0% (97.6 to 100.0) | 0 | 100.0% (97.6 to 100.0) |
| m-94f4f6b2-d37e44c6 | all | 439 | 288 | 1 | 99.7% (98.1 to 99.9) | 21 | 93.2% (89.8 to 95.5) |
| m-94f4f6b2-d37e44c6 | exact | 132 | 132 | 0 | 100.0% (97.2 to 100.0) | 0 | 100.0% (97.2 to 100.0) |
| m-94f4f6b2-d37e44c6 | name links | 156 | 156 | 1 | 99.4% (96.5 to 99.9) | 0 | 100.0% (97.6 to 100.0) |
| m-1465a4ba-e5444596 | all | 404 | 295 | 44 | 85.1% (80.6 to 88.7) | 28 | 90.0% (85.9 to 93.0) |
| m-1465a4ba-e5444596 | exact | 109 | 109 | 0 | 100.0% (96.6 to 100.0) | 0 | 100.0% (96.6 to 100.0) |
| m-1465a4ba-e5444596 | name links | 186 | 186 | 44 | 76.3% (69.7 to 81.9) | 1 | 99.3% (96.1 to 99.9) |


## 3. Every wrong link and every miss in the labelled set

**Wrong links: 0.**

_(none)_


**Missed (abstained although the true party is in the graph): 23.**

| sample_id | source | reference | abstain reason | best candidate | true target |
|---|---|---|---|---|---|
| S147859486f | asic_afsl | CHAMPION, DAVID RUSSELL | PARTY_TYPE_CONFLICT | urn:abn:33640626581 | urn:abn:33640626581 DAVID RUSSELL CHAMPION |
| Sc9228d8fbb | asic_afsl | PASKALIDIS, ANGELOS EVANGELOS | PARTY_TYPE_CONFLICT | urn:abn:97928830776 | urn:abn:97928830776 EVANGELOS PASKALIDIS |
| Sedd80fd6b9 | asic_afsl | SAWERES, SHERENE | PARTY_TYPE_CONFLICT | urn:abn:43896454640 | urn:abn:43896454640 SHERENE SAWERES |
| Sa853a29164 | asic_afsl | SUN, PAUL | PARTY_TYPE_CONFLICT | urn:abn:14877103674 | urn:abn:14877103674 PAUL SUN |
| S535402f30f | asic_afsl | GU, LI | PARTY_TYPE_CONFLICT | urn:abn:12303231943 | urn:abn:12303231943 LI GU |
| S4ea917a14d | asic_afsl | FROST, KYLE CLIFFORD | PARTY_TYPE_CONFLICT | urn:abn:80620929309 | urn:abn:80620929309 KYLE CLIFFORD FROST |
| S47a42a9617 | asic_afsl | WAN, VICTOR KIT | PARTY_TYPE_CONFLICT | urn:abn:87290948916 | urn:abn:87290948916 VICTOR KIT WAH WAN |
| S42c468870f | asic_afsl | SALTER, GEOFFREY GORDON | PARTY_TYPE_CONFLICT | urn:abn:98951387736 | urn:abn:98951387736 GEOFFREY GORDON SALTER |
| S5254559e1e | asic_credit | TRUSTEES OF THE RM LINTON FAMILY TRUST | BELOW_THRESHOLD | urn:abn:66902383651 | urn:abn:66902383651 The trustee for The RM Linton Family Trust |
| Sfd0da40a14 | asic_credit | PLUMB, ROBERT CHARLES | BELOW_THRESHOLD | urn:abn:70565772914 | urn:abn:70565772914 ROBERT CHARLES PLUMB |
| Sb45e875585 | asic_credit | WHYTE, BENJAMIN JOHN | BELOW_THRESHOLD | urn:abn:15745649351 | urn:abn:15745649351 BENJAMIN JOHN WHYTE |
| S287b774c23 | asic_liquidator | LEDGER, ALAN EDSON | BELOW_THRESHOLD | urn:abn:57650942525 | urn:abn:57650942525 ALAN EDSON LEDGER |
| S61cbc9eb77 | gleif_l1 | MLC Limited | AMBIGUOUS | urn:abn:90000000402 | urn:abn:90000000402 NIPPON LIFE INSURANCE AUSTRALIA AND NEW ZEALAND LIMITED |
| S80a8a0cafb | gleif_l1 | LAMBOO Resources Limited | AMBIGUOUS | urn:abn:27099098192 | urn:abn:27099098192 NH3 CLEAN ENERGY LIMITED |
| Sf1d23bedc9 | gleif_l1 | The Trustee for Marketing Seven Trust | BELOW_THRESHOLD | urn:abn:81961915252 | urn:abn:81961915252 The Trustee for MARKETING SEVEN TRUST |
| S9831c8c512 | gleif_l1 | PAC GLOBAL ESPORTS FUND | BELOW_THRESHOLD | urn:abn:68800507120 | urn:abn:68800507120 The Trustee for PAC GLOBAL ESPORTS FUND |
| S957b03cf74 | gleif_l1 | MPF DIVERSIFIED FUND NO.2 | BELOW_THRESHOLD | urn:abn:81102464940 | urn:abn:81102464940 The Trustee for the MPF Diversified Fund No.2 |
| S50fcd855cc | gleif_l1 | Browning Family Super (''The Fund'') | BELOW_THRESHOLD | urn:abn:51037296725 | urn:abn:56315290319 The Trustee for Browning Family Super |
| S7f2a2b41a5 | gleif_l1 | THE EILISTRAEE NO 2 TRUST | BELOW_THRESHOLD | urn:abn:77669508760 | urn:abn:77669508760 The Trustee for Eilistraee No. 2 Trust |
| S4a3dc2c33f | gleif_l1 | GE ENERGY OPTIMIZATION AND CONTROL PTY LTD | JURISDICTION_MISMATCH | urn:abn:97082286913 | urn:abn:97082286913 BAKER HUGHES DIGITAL SOLUTIONS AUSTRALIA PTY LTD |
| S8ce9f5ef4e | gleif_l1 | SIEGEL PTY LTD | JURISDICTION_MISMATCH | urn:abn:35609511542 | urn:abn:35609511542 SIEGEL PTY LTD |
| Sdc7c969a17 | gleif_l1 | MECS CAPITAL MANAGEMENT PTY LTD | JURISDICTION_MISMATCH | urn:abn:47650269677 | urn:abn:47650269677 MECS CAPITAL MANAGEMENT PTY LTD |
| S54e87feae2 | gleif_l1 | REVOLUT PAYMENTS NEW ZEALAND PTY LIMITED | JURISDICTION_MISMATCH | urn:abn:89645171651 | urn:abn:89645171651 REVOLUT PAYMENTS NEW ZEALAND PTY LTD |


**UNSURE (excluded): 24.** The decision is shown so a human can settle them.

| sample_id | source | reference | decision | outcome | target | why unsure |
|---|---|---|---|---|---|---|
| Sbdadceffa8 | gleif_l1 | Shane Thomas McEwan & Dianne McEwan ATF Lifestyle Superannuation Fund | abstain | BELOW_THRESHOLD | urn:abn:93667727032 LIFESTYLE SUPERANNUATION FUND | 'Shane Thomas McEwan & Dianne McEwan ATF Lifestyle Superannuation Fund', c/o United Global Capital, Level 7 Melbourne. The VIC 'LIFESTYLE SUPERANNUATION FUND' (ABN 93667727032, 3013) is in the graph because another LEI (984500C594FDBD6D8939, Level 7 North Tower 459 Collins St) states it. Same adviser address and name, but many clients' SMSFs share an adviser address and the name is generic; trustees not visible for the ABN. Cannot decide. |
| S523009f69e | gleif_l1 | 43 DEGREES SOUTH PTY LIMITED | abstain | JURISDICTION_MISMATCH | urn:abn:79613231664 43 DEGREES SOUTH PTY LTD | AMENDED DURING CENSUS (original blind label NONE). '43 DEGREES SOUTH PTY LIMITED' on the NZ register (8491629, Methven NZ). The census showed 'Pty' companies on the NZ register are often Australian companies registered in NZ as overseas companies (Siegel, Revolut Payments NZ), so this may be the Tasmanian 43 DEGREES SOUTH PTY LTD (ACN 613231664) registered in NZ. Cannot confirm either way: UNSURE. |
| Sd338fb78fa | gleif_l1 | Luerssen Australia international PTY LTD | abstain | JURISDICTION_MISMATCH | urn:abn:40637189345 LUERSSEN AUSTRALIA INTERNATIONAL PTY LTD | 'Luerssen Australia international PTY LTD', jurisdiction Saudi Arabia (Riyadh registry). A 'Pty Ltd' registered in Saudi Arabia is likely the Australian LUERSSEN AUSTRALIA INTERNATIONAL PTY LTD (ACN 637189345) registered there as a foreign company (a branch), but this cannot be confirmed. |
| Sb4743f3f9e | asic_credit | BLUE AEGIS PTY LTD | link | EXACT_ABN | urn:abn:68694439024 ROYGO FINANCE PTY LTD | Credit register prints ABN 68694439024 for BLUE AEGIS PTY LTD (licence 2026-10-07) but ASIC and ABR both name that ACN/ABN 'ROYGO FINANCE PTY LTD' (registered 2026-01-16, no former names). Either a rename not yet in the snapshots or a wrong number on the register; cannot tell from the data. |
| Sd4cc1897b9 | gleif_l1 | KOMATSU AUSTRALIA CORPORATE FINANCE PTY LTD | link | NAME_NORMALISED_EXACT | urn:abn:84067959666 KOMATSU AUSTRALIA CORPORATE FINANCE PTY LTD | GLEIF BRANCH LEI: Komatsu Australia Corporate Finance Pty Ltd, New Zealand branch (Auckland). Head entity (ACN 067959666) in the graph. Foreign branch: policy question. |
| S4f3270aeed | gleif_l1 | MACQUARIE BANK LIMITED | link | NAME_NORMALISED_EXACT | urn:abn:46008583542 MACQUARIE BANK LIMITED | GLEIF BRANCH LEI: Macquarie Bank Limited London branch (UK BR002678). Head entity MACQUARIE BANK LIMITED (ACN 008583542) is in the graph. Foreign branch: policy question. |
| S892cfa9d66 | gleif_l1 | PO VALLEY OPERATIONS PTY LTD | link | NAME_NORMALISED_EXACT | urn:abn:46083354269 PO VALLEY OPERATIONS PTY LIMITED | GLEIF BRANCH LEI: Po Valley Operations Pty Ltd, Italian branch (Rome). Head entity PO VALLEY OPERATIONS PTY LIMITED (ACN 083354269) in the graph. Foreign branch: policy question. |
| Sd654d50c27 | gleif_l1 | GENETIC TECHNOLOGIES LIMITED | abstain | JURISDICTION_MISMATCH | urn:abn:17009212328 GENETIC TECHNOLOGIES LIMITED | GENETIC TECHNOLOGIES LIMITED on the NZ register (NZBN 9429000018333, Remuera). Could be the ASX-listed Australian company (ACN 009212328) registered in NZ as an overseas company, or an unrelated NZ company of the same name. Cannot tell. |
| Se6684695e2 | gleif_l1 | Jacqueline Kim Stein ATF Stein Family Trust | abstain | BELOW_THRESHOLD | urn:abn:38245244171 The Trustee for The Stein Family Trust | 'Jacqueline Kim Stein ATF Stein Family Trust', Perth WA 6026, no number. Graph has three 'Stein Family Trust' trusts (6027, 6065, 6163) plus 'J Stein Family Trust' (6210); 6027 is adjacent to 6026 but nothing confirms the trustee. Cannot decide. |
| Se095d115bc | gleif_l1 | ELGAS LIMITED | abstain | JURISDICTION_MISMATCH | urn:abn:85002749260 ELGAS LIMITED | ELGAS LIMITED on the NZ register (NZBN 9429032428322, Penrose Auckland) with HQ North Ryde NSW, the address of the Australian ELGAS LIMITED (ACN 002749260). Possibly the Australian company's NZ overseas registration, possibly a separate NZ company. Cannot tell. |
| S6c778ae0f2 | gleif_l1 | UniSuper | link | NAME_NORMALISED_EXACT | urn:abn:54006027121 UNISUPER LIMITED | AMENDED AFTER JOIN (blind label NOT_IN_GRAPH): the blind file listed this candidate, but my compact viewer dropped its alias / via columns, so I missed it. LEI legal name 'UniSuper', c/o UniSuper Limited, entity created 1983-01-01, registered 2012. Could be the fund (whose trustee is UniSuper Limited, not in the graph) or UNISUPER LIMITED (ACN 006027121, in the graph). Not decidable from the record. |
| S9dd137b8d6 | gleif_l1 | BEIERSDORF AUSTRALIA LTD | link | NAME_NORMALISED_EXACT | urn:abn:98000025623 BEIERSDORF AUSTRALIA LTD | GLEIF BRANCH LEI: Beiersdorf Australia Ltd, New Zealand branch (Auckland). Head entity BEIERSDORF AUSTRALIA LTD (ACN 000025623) in the graph. Foreign branch: policy question. |
| S06f15a18dd | gleif_l1 | CMC MARKETS STOCKBROKING LIMITED | link | NAME_NORMALISED_EXACT | urn:abn:69081002851 CMC MARKETS STOCKBROKING LIMITED | GLEIF BRANCH LEI: CMC Markets Stockbroking Limited (NZ Branch), registered on the NZ register. Head entity CMC MARKETS STOCKBROKING LIMITED (ACN 081002851) is in the graph. Foreign branch of an Australian company: same policy question as the v2 branch rows. |
| Sa7bcb6093c | gleif_l1 | SMEC International Pty Limited | link | NAME_NORMALISED_EXACT | urn:abn:32065440619 SMEC INTERNATIONAL PTY. LIMITED | GLEIF record is an international BRANCH (Indian registry RA000394 F06919, Gurgaon) of SMEC International Pty Limited; the head entity SMEC INTERNATIONAL PTY. LIMITED (ACN 065440619) is in the graph. A branch is not a separate legal person, but GLEIF models it as its own LEI with an IS_INTERNATIONAL_BRANCH_OF edge. Whether it should link to the head company is a policy decision for a human. |
| Se9aea98759 | gleif_l1 | HEIDELBERG GRAPHIC EQUIPMENT LIMITED | abstain | JURISDICTION_MISMATCH | urn:abn:19004395779 HEIDELBERG GRAPHIC EQUIPMENT LIMITED | HEIDELBERG GRAPHIC EQUIPMENT LIMITED on the NZ register (Auckland). Possibly the Australian company (ACN 004395779) registered in NZ as an overseas company, possibly a separate NZ subsidiary of the same name. Cannot tell. |
| Sa9bfcee9a2 | gleif_l1 | THE HART SUPERANNUATION FUND | abstain | BELOW_THRESHOLD | urn:abn:51996950901 HART SUPERANNUATION FUND | AMENDED AFTER JOIN (original blind label NOT_IN_GRAPH). GLEIF 'THE HART SUPERANNUATION FUND', 5 Masthead Quay, postcode 4566 (Noosaville QLD) but region coded AU-NSW. The blind note said all graph Hart funds were WA; that was wrong: the candidate list also held HART SUPERANNUATION FUND, ABN 51996950901, Booral NSW 2425, stated by another LEI (25490012J71UB7JQBW08). A NSW region on a QLD address hints the fund moved from NSW, so the two LEIs may be one SMSF; equally a common name. Cannot decide: UNSURE. |
| S4e1d59192b | gleif_l1 | Phil Asker Pty Ltd | abstain | AMBIGUOUS | urn:abn:82063895876 CAPTAIN'S CHOICE PTY LTD | AMENDED AFTER JOIN (blind label NOT_IN_GRAPH): the blind file listed this candidate, but my compact viewer dropped its alias / via columns, so I missed it. Name swap: on 2017-04-11 ACN 063895876 (then PHIL ASKER PTY LTD, now CAPTAIN'S CHOICE PTY LTD, in the graph) and ACN 005001874 (then Captain's Choice, now PHIL ASKER PTY LTD, not in the graph) exchanged names. The LEI was registered 2013 and lapsed, which points to 063895876; its current legal name points to 005001874. Cannot decide. |
| S77b2d58655 | gleif_l1 | MACQUARIE CORPORATE HOLDINGS PTY LIMITED | link | NAME_NORMALISED_EXACT | urn:abn:54096705109 MACQUARIE CORPORATE HOLDINGS PTY LIMITED | GLEIF BRANCH LEI: Macquarie Corporate Holdings Pty Limited, London branch (UK BR009622). Head entity (ACN 096705109) in the graph. Foreign branch: policy question. |
| S6d39c186cb | gleif_l1 | QBE INSURANCE INTERNATIONAL LIMITED | link | NAME_NORMALISED_EXACT | urn:abn:11000000948 QBE INSURANCE (INTERNATIONAL) LTD | GLEIF BRANCH LEI: QBE Insurance International Limited, French branch (RA000189). Head entity QBE INSURANCE (INTERNATIONAL) LTD (ACN 000000948) is in the graph. Foreign branch: policy question. |
| Sd4ca6b45f5 | gleif_l1 | China Construction Bank Corporation | link | NAME_NORMALISED_EXACT | urn:abn:24125167553 China Construction Bank Corporation | GLEIF record is the New Zealand BRANCH of China Construction Bank Corporation (Chinese bank). The graph party 'China Construction Bank Corporation' (ABN 24125167553, foreign company ARBN 125167553) is the same legal person's Australian registration. A branch is not a separate legal person but has its own LEI; whether to link a foreign branch to the AU-registered head entity is a policy decision. |
| Sf434544ae8 | gleif_l1 | AUSTRALIA AND NEW ZEALAND BANKING GROUP LIMITED | link | NAME_NORMALISED_EXACT | urn:abn:11005357522 AUSTRALIA AND NEW ZEALAND BANKING GROUP LIMITED | GLEIF BRANCH LEI: ANZ Paris branch (French registry). Head entity AUSTRALIA AND NEW ZEALAND BANKING GROUP LIMITED (ACN 005357522) in the graph. Foreign branch: policy question. |
| S478544e8fa | gleif_l1 | APA Group | link | NAME_FUZZY | urn:abn:99091344704 APA GROUP LIMITED | 'APA Group' (stapled group, LEI legal form 'COMPANY'). APA GROUP LIMITED (ACN 091344704) is one company inside the stapled structure; whether the LEI is for that company or the stapled group is unclear. |
| S0eea39a327 | gleif_l1 | PRIMELINE PTY LTD ATF DONALD FAMILY TRUST | abstain | BELOW_THRESHOLD | urn:abn:29029528159 The trustee for DONALD FAMILY TRUST | GLEIF 'PRIMELINE PTY LTD ATF DONALD FAMILY TRUST', Beaumaris VIC 3193, no registration number, LEI lapsed. The only VIC 'DONALD FAMILY TRUST' in the graph (ABN 29029528159, VIC 3187) is in the graph because a different LEI (984500C9B89PQ0F4FD58, 'The trustee for DONALD FAMILY TRUST', Brighton VIC 3186, created 2001) names it. Different LEIs, different street addresses, trustee not stated for the ABN; 'Donald Family Trust' is a common name. Cannot confirm; leaning different. |
| Sbc8714c9b7 | gleif_l1 | ATTACH2 PTY LIMITED | abstain | JURISDICTION_MISMATCH | urn:abn:98634198691 ATTACH2 PTY LTD | 'ATTACH2 PTY LIMITED' on the NZ register (6254636, c/o PwC Wellington). 'Pty' suggests an Australian company registered in NZ as an overseas company, i.e. ATTACH2 PTY LTD (ACN 634198691, QLD), but the NZ number may predate the 2019 ACN. Cannot confirm. |


## 4. Blocking recall, own check on labelled records

Of 308 labelled records whose true party is in the graph, the true party was among the stored candidates of `m-b5e50f74-d37e44c6` for 308 (100.0%). 


## 6. Rows a human should check first

1. Every ACCC and banned-organisation **link** (a wrong one publishes an accusation): S0a82ad361a, S104fa9a54f, S187082f660, S32382bf8a7, S3c90842232, S692aa3e1e1, S8006ed7bce, S8087a23aee, S89dd867cee, Sa11bd4967b, Sb61dd676d5, Sb85857f6d3, Sdd84b09f46, Sf2baeceeac, Sf2c6b1af9a, Sf326e19dac, Sf8e48f5b66, Sfd483c527e, Sff4c7d6ae4.
2. Every ACCC and banned-organisation abstention labelled with a party in the graph: none.
3. Every wrong link in section 3 and every UNSURE row.
4. The non-blind census rows (labeller column says NOT blind), starting with the ones labelled as a party (foreign-company registrations, branches).
5. Ten random blind labels of each class (party / NONE / NOT_IN_GRAPH) to estimate the labeller's own error rate.


## Notes (hand-written; the tables above are regenerated, this text is not)

### N1. How the labels were built

* **Labeller.** An AI evaluation agent working independently of the matcher's author. It never read the
  matcher's scores, its tests' expectations or `outputs/resolution_run_*.md` precision claims while
  labelling, and it labelled from `labels/sample_<version>.csv` only.
* **Blind file.** For each sampled record the blind file holds the reference record (name, stated ABN / ACN
  / LEI / licence, state, source facts such as GLEIF legal form, registration authority and number, legal
  address), a candidate list and register facts. The candidate list is the union of four routes:
  stated-identifier lookups, exact normalised-name lookups (name and alias), the matcher's stored blocking
  candidates (top 10 by an independent `token_set_ratio`, not the matcher's score) and every decided
  target, so the matcher's choice is always present but never marked. Register facts are read directly
  from the loaded ASIC company register (all 4.0M companies, including the stated ACN, the ABN printed on
  the ASIC row, former names and status) and from the loaded ABR records, plus "same normalised name"
  hits across the whole ASIC register (this is how `NOT_IN_GRAPH` is told apart from `NONE`). No public
  lookup service was called.
* **Decisions file.** `labels/sample_<version>_decisions.csv` (version, stratum, decision, target, score)
  was joined only after all 171 blind labels were written.
* **Label values.** A canonical key; `NOT_IN_GRAPH` (a real Australian-registered business that is not a
  party in this WA/TAS + Tier 2 slice, so abstaining is correct); `NONE` (no Australian entity: NZ trusts,
  foreign companies with no Australian registration); `UNSURE`. Recall counts only records whose label is
  a key.
* **Rules the labeller applied.** A stated identifier counts as truth only when the register entry it
  points to agrees on name (or former name) and legal form. A foreign company's Australian registration
  (ASIC type FNOS, an ARBN, an "Other Incorporated Entity" ABN of the same name) is the same legal person
  as its head-office LEI. A subsidiary, a sibling, a dual-listed twin (Rio Tinto plc / Limited), a company
  that reused a deregistered company's name, or a same-named trust in another state or country is a
  different party. A GLEIF *branch* LEI registered outside Australia is UNSURE (policy question, see N6).
  Name plus postcode agreement on a distinctive trust or person name was accepted; on a common name
  ("Donald Family Trust", "Lifestyle Superannuation Fund") it was not.
* **Corrections after the join, disclosed.** Two blind labels were changed, both towards UNSURE, never
  towards agreeing with the matcher: `Sa9bfcee9a2` (Hart Superannuation Fund; the blind note had missed
  an NSW candidate further down the list) and `S523009f69e` (43 Degrees South; the census showed that
  "Pty" companies on the NZ register are often Australian companies registered there). Both rows say
  "AMENDED" in their evidence column.
* **Limits.** One labeller, no second rater, so no inter-rater agreement figure. An AI labeller can share
  blind spots with an AI-written matcher (both may over-trust name equality); the rules above were chosen
  to push against that. Trust identity is the weakest evidence: the ABR does not publish trustees, so many
  trust labels rest on name + postcode. NZ legal facts (whether an NZ entry is an overseas registration of
  an Australian company) could not be checked against the NZ Companies Office. A human should spot-check
  the rows listed in section 6 before these numbers are quoted externally.

### N2. Sample design, and the census that was not blind

* Seeded (`seed=20261118`) and reproducible: inside each stratum records are taken in sha256(seed |
  source | record_id) order, so a re-run on the same store gives byte-identical files (tested).
* Plan (`DEFAULT_PLAN` in `sampler.py`): all 20 ACCC notices, all 15 banned organisations, GLEIF name links
  (8 NAME_FUZZY, 12 NAME_NORMALISED_EXACT), 22 GLEIF and 18 AFSL / credit exact links, 41 abstentions spread
  over GLEIF BELOW_THRESHOLD (near-threshold bands weighted x3), AMBIGUOUS, NO_CANDIDATE,
  PARTY_TYPE_CONFLICT, IDENTIFIER_CONFLICT, AFSL / credit / liquidator abstentions, and from the
  identifier-stripped run 20 AFSL / credit name links and 12 name-path abstentions. 171 records.
* **Census.** After the blind labels were joined, a population query (no labels involved) showed that 75 of
  the 253 v2 GLEIF name-path links come from LEIs whose legal jurisdiction is not Australia. Because the
  blind sample had already found 3 wrong links in that group, every one of them was labelled: the plan
  gained a final quota (`segment="foreign"`, take all), appended last so the 171 earlier draws are
  unchanged (verified), and 71 new rows were labelled. **These 71 labels are not blind**: the labeller had
  seen the link targets in the population query. They carry `NOT blind` in the labeller column, and they
  are the second thing a human should check. The four foreign-jurisdiction records that were already in
  the blind sample keep their blind labels.
* Weighted estimates post-stratify on the version's own strata, which include the jurisdiction segment for
  GLEIF, so the census stratum gets weight 1 and the random AU stratum keeps its sampling weight.

### N3. Thresholds evaluated, and why

Policy of `m-1465a4ba-e5444596` (from `matcher_version.policy`): name-path threshold **0.90** with a margin
of 0.05 over the runner-up; **0.97 with margin 0.10** for `accc_notice` and `asic_banned_org` (a wrong link
publishes an accusation); 0.95 for references of unknown party type; persons are never linked on a name.
Identifier links (EXACT_ABN / EXACT_ACN) are not thresholded. All metrics above are at these policy
thresholds; the sweep in section 5 shows 0.85 / 0.90 / 0.95 on the AFSL and credit name path.

The sweep says the threshold is not the lever that matters for the errors found here: 0.90 and 0.95 give
identical results on AFSL / credit, 0.85 adds about 270 AFSL and 100 credit links that are all correct, and
every wrong GLEIF link sits at **0.97 or 1.0** (NAME_NORMALISED_EXACT is emitted at a fixed 0.97). Any
threshold low enough to keep correct exact-name links keeps the wrong ones. The fix is a gate (N7), not a
number. With that gate in place, 0.85 for register-sourced references would be a reasonable recall gain.

### N4. Identifier coverage per Tier 2 source (from `outputs/identifier_coverage.md`)

| Source | Records | ABN | ACN (any) | ABN or ACN | Other keys | No business key |
|---|---|---|---|---|---|---|
| asic_afsl | 6,551 | 96.9% | 97.3% | 99.5% | AFSL 100%, ARBN 0.4% | 2 |
| asic_credit | 4,308 | 89.3% | 89.9% | 98.3% | ACL 100%, AFSL 7.2% | 74 (69 persons) |
| asic_banned_org | 15 | 0% | 100% | 100% | none | 0 |
| asic_liquidator | 660 | 0% | 0% | 0% | liquidator no. 100% | 660 (all persons) |
| gleif_l1, AU entities | 54,082 | 26.2% | 63.1% | 89.3% | LEI 100%, ARSN 4.8% | 0 |
| gleif_l1, NZ entities | 4,281 | 0% | 0% | 0% | NZBN 24.0%, NZ co. no. 30.8% | 0 |
| accc_notice (Tier 3) | 20 | 6 notices state an ABN | 15 state an ACN | 18 of 20 | none | 2 (the Spanish company) |

The labelled exact links agree with this: 101 of 101 labelled identifier links point at the party the
register entry names (one more, Blue Aegis, is UNSURE because the ABN on the credit register belongs to a
company ASIC still calls ROYGO FINANCE).

### N5. Blocking key and its recall cost

* **Key.** Two blockers plus two exact probes. `block_token_state`: the first distinctive token of the
  normalised name plus the state (state ignored when either side lacks one), top 20 by Jaro-Winkler, blocks
  over 20,000 rows skipped. `block_fts`: IDF-weighted retrieval over distinctive tokens, top 20, tokens with
  document frequency over 5,000 ignored. Exact probes: stated identifier, exact normalised name.
* **Cost measured by the matcher's author** (name-only experiment, ABN truth): blocking recall 99.95% AFSL,
  99.8% credit.
* **Own recomputation** (section 5, truth = ABN else ACN printed on the register record, read from
  `source_record` and the identifier table, not from the matcher's links): AFSL and credit blocking recall
  as shown in the sweep table, consistent with the author's figures; the credit misses are a handful of
  records.
* **Own check on the labelled sample** (section 4): the true party was in the stored candidate set for every
  labelled record whose true party is in the graph, in both v2 and the name-only run. So none of the misses
  in section 3 is a blocking miss; they are all decision-rule misses.
* Not measured: blocking recall for GLEIF and ACCC references with no identifier (no independent truth at
  population scale). The state filter is the obvious risk for them (a GLEIF legal-address state differing
  from the ABR main-business state drops the true party from `block_token_state`; `block_fts` has no state
  filter and is the safety net).

### N6. Confusion cases

* **Commonwealth Bank of Australia vs Commonwealth Superannuation Corporation.** Run on the evaluation
  snapshot with `bizgraph --db data/eval_snapshot_20261118.duckdb resolve "<text>"` (v2 code, read-only):
  "Commonwealth Bank of Australia" resolves to urn:abn:48123123124 COMMONWEALTH BANK OF AUSTRALIA
  (NAME_NORMALISED_EXACT 0.97, margin 0.30 over The Trustee for Commonwealth Bank Group Super; CSC is not
  in the top candidates). "Commonwealth Superannuation Corporation" resolves to urn:abn:48882817243
  COMMONWEALTH SUPERANNUATION CORPORATION, with CBA not a candidate. "Commonwealth Bank" also resolves to
  CBA (0.97). Both entities verified against the ABR records in the store. **Pass**: the token gate stops
  the high-similarity pair, whatever the embedding says.
* **Banned and disqualified organisations.** 15 records, all labelled. 12 links, all EXACT_ACN, all to the
  party whose ACN the ban states and whose ABR / ASIC name matches (several are deregistered companies with
  cancelled ABNs, which is expected for 1999 to 2009 bans). 3 abstentions (Knightsbridge Finance, Gamel Ward,
  Blackburne & Dixon): their ACNs are held by no party in the graph, and the nearest names (KNIGHTSBRIDGE
  PARTNERS, Blackburne Money, people surnamed Ward) are different entities. **No wrong link, no miss.** The
  0.97 / 0.10 strict policy was never exercised: no banned record was decided on its name.
* **ACCC notices (Tier 3).** 7 links, all EXACT_ACN and correct; 13 abstentions, all correct (11 recipients
  are real companies outside the slice, 2 are the Spanish company). The near misses the strict policy had to
  refuse were real traps: SYSTEMS OPERATIONS PTY LTD vs POLYLINE PIPE SYSTEMS OPERATIONS PTY LTD
  (token_set_ratio 100), COTTON ON AUSTRALIA vs its sibling COTTON ON FINANCE, H&M vs WA sole traders named
  Mauritz, VENUE SMART vs VENUE MAESTRO.
* **Foreign entities with an Australian namesake (the main failure).** NZ family trusts linked to WA / TAS
  trusts of the same name (Mora, Juno, Wanaka, Kanda, Luna, Camel ... 27 of them, counting one NZ unit trust), foreign parents linked
  to their Australian subsidiaries or twins (RIO TINTO PLC to RIO TINTO LIMITED, BHP Billiton Finance plc to
  BHP Billiton Finance Limited, STUDIOCANAL to STUDIOCANAL PTY LIMITED, VanEck Investments Limited (IE) to
  the Australian VanEck Investments Limited, Civmec Limited (SG) to the new Australian Civmec Limited), NZ
  companies linked to unrelated Australian ones (Stanwell Limited to STANWELL CORPORATION LIMITED, BOC, Eaton
  Industries, Farmlands Mathias International), and two links through a business name to a different
  company (THE TORO COMPANY to HAVEN LICENSING PTY LIMITED; Prism Global Group Plc to PZM LTD).
* **Same-name trusts inside Australia.** Browning Family Super (WA 6210) linked to the Browning fund in 6023
  although a same-name fund sits in 6210; Arkad Trust (SA) linked to the TAS Arkad Trust. Common trust names
  are the AU-side error class.
* **Reused company names.** SYMPHONY FINCO, PROJECT 10X and HARVEYCREST: the LEI states the old, deregistered
  company's ACN and a new company now holds the name. v2 abstained (IDENTIFIER_CONFLICT) on all three:
  correct.
* **Normaliser traps found while labelling.** "WT FINANCE CO PTY LIMITED" and "WT FINANCE PTY LTD" normalise
  to the same string (CO is stripped); "SIMPLY CORPORATION PTY LTD" normalises to "SIMPLY", equal to a WA
  limited partnership and SIMPLY PTY LTD. The name-only run abstained AMBIGUOUS on the first and the exact
  path linked the second, so no wrong link resulted, but both would produce one in a name-only Tier 3 source.
* **Branches.** GLEIF issues LEIs to branches. The Sydney branches of foreign banks (registered with ASIC
  under the ARBN the graph party carries) were labelled as that party. Branches registered abroad (CCB New
  Zealand branch, SMEC's Indian branch) are UNSURE: a branch is the same legal person as its head office, but
  linking it makes the graph say the Australian registration holds the foreign branch's LEI. This needs a
  modelling decision (a branch node with `IS_INTERNATIONAL_BRANCH_OF`), not a label.

### N7. What the matcher should change (in priority order)

1. **Jurisdiction gate for register-sourced references.** A GLEIF record whose legal jurisdiction is not AU
   must not link on name to an Australian-incorporated party (Pty Ltd, Ltd, ABR trust or partnership). It may
   link on name only to a party that is that foreign entity's Australian registration (ASIC type FNOS /
   ARBN, or an ABR "Other Incorporated Entity" with the same name), and preferably only when the LEI's
   registration number or the ASIC former names corroborate it. In the census this rule would have removed
   all 42 wrong foreign links and kept 23 of the 27 correct ones (the foreign banks and foreign companies
   registered here). The 4 it would lose are Australian companies registered abroad (Siegel, Revolut Payments
   NZ, MECS Capital Management) and one LEI with a mis-coded country (GE Energy Optimization and Control);
   abstaining on those is the safe direction.
2. **NZ trusts never link to AU trusts on name.** A trust name carries no identity across jurisdictions;
   27 of the 42 foreign errors are this one pattern.
3. **Common trust names need a second key.** For AU trusts with no identifier, require postcode agreement
   (not only state) or abstain; Browning and Arkad are this class, and the AU segment's estimated precision
   (section 2) is below what the brief tolerates.
4. **Identifier beats a party-type hint.** All 41 v2 GLEIF PARTY_TYPE_CONFLICT abstentions have a stated ABN
   that equals the best candidate's ABN (population query, not a sample); the 3 sampled ones are correct
   sole-trader links that were refused because GLEIF types sole traders as organisations. Let an exact ABN
   win over a type conflict when the names agree, or type GLEIF SOLE_PROPRIETOR as person-capable.
5. **Business-name aliases for formal references.** THE TORO COMPANY and Prism Global Group Plc matched via
   an alias of a different company. The v2 rule R5f should also cover NAME_NORMALISED_EXACT, not only the
   fuzzy path.
6. **Normaliser.** Do not strip CO / CORPORATION when the remaining name is one token or when stripping
   creates a collision with another registered name; keep a "name collision" flag in the evidence.
7. **Persons.** The two person misses (a credit licensee and a liquidator with full three-part name and
   matching postcode) are deliberate policy costs; keep the policy, but a full-name + postcode rule for
   licensed persons would be a safe recall gain to measure next.
8. **Recalibration hook.** Because NAME_NORMALISED_EXACT confidence is a constant, `redecide` cannot sweep
   it. Record the gate features (jurisdiction, alias kind, postcode agreement) in candidate features so a
   gate change can be replayed without a re-match.

### N8. Rough population impact for v2

GLEIF name-path links in v2: 253. Foreign-jurisdiction segment (75, census): 42 wrong, 27 correct, 6 UNSURE.
AU segment (178, sampled): see the weighted precision of the `au` row in section 2, which implies on the
order of 20 to 30 further wrong links, with a wide interval (12 labelled). So roughly a quarter of v2's
GLEIF name links are wrong, while every identifier link checked (101) and every AFSL / credit name link
checked (39 from the stripped run, plus the full-population identifier sweep with zero wrong links) is
right. The GLEIF name path should be switched off, or gated as in N7, before v2's links are published.

