# Evaluation of matcher version `m-94f4f6b2-d37e44c6`


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


Strata of `m-94f4f6b2-d37e44c6` that hold labelled records (stratum = source | decision | match type or abstain reason | score band | segment; segment: GLEIF `foreign` (legal jurisdiction not AU), `au-person-abn` (stated ABN is a sole trader) or `au`; AFSL / credit `ended` or `current` licence):

| stratum | population | labelled |
|---|---|---|
| accc_notice\|abstain\|BELOW_THRESHOLD\|far\| | 10 | 10 |
| accc_notice\|abstain\|NO_CANDIDATE\|none\| | 3 | 3 |
| accc_notice\|link\|EXACT_ACN\|id\| | 7 | 7 |
| asic_afsl\|abstain\|BELOW_THRESHOLD\|far\|current | 30 | 4 |
| asic_afsl\|abstain\|BELOW_THRESHOLD\|far\|ended | 4 | 2 |
| asic_afsl\|abstain\|BELOW_THRESHOLD\|near0.05\|current | 2 | 1 |
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
| gleif_l1\|abstain\|AMBIGUOUS\|near0.05\|au | 2 | 2 |
| gleif_l1\|abstain\|BELOW_THRESHOLD\|far\|au | 4562 | 13 |
| gleif_l1\|abstain\|BELOW_THRESHOLD\|far\|foreign | 4757 | 6 |
| gleif_l1\|abstain\|BELOW_THRESHOLD\|near0.05\|au | 544 | 15 |
| gleif_l1\|abstain\|BELOW_THRESHOLD\|near0.05\|foreign | 223 | 1 |
| gleif_l1\|abstain\|BELOW_THRESHOLD\|near0.10\|au | 260 | 1 |
| gleif_l1\|abstain\|BELOW_THRESHOLD\|near0.10\|foreign | 162 | 1 |
| gleif_l1\|abstain\|IDENTIFIER_CONFLICT\|near0.05\|au | 3 | 3 |
| gleif_l1\|abstain\|JURISDICTION_MISMATCH\|near0.05\|foreign | 84 | 72 |
| gleif_l1\|abstain\|NO_CANDIDATE\|none\|foreign | 603 | 3 |
| gleif_l1\|link\|EXACT_ABN\|id\|au | 13908 | 10 |
| gleif_l1\|link\|EXACT_ABN\|id\|au-person-abn | 248 | 23 |
| gleif_l1\|link\|EXACT_ACN\|id\|au | 33809 | 12 |
| gleif_l1\|link\|NAME_FUZZY\|0.95-0.97\|au | 8 | 8 |
| gleif_l1\|link\|NAME_FUZZY\|0.95-0.97\|foreign | 1 | 1 |
| gleif_l1\|link\|NAME_FUZZY\|ge0.97\|au | 15 | 15 |
| gleif_l1\|link\|NAME_NORMALISED_EXACT\|ge0.97\|au | 120 | 120 |
| gleif_l1\|link\|NAME_NORMALISED_EXACT\|ge0.97\|foreign | 25 | 25 |


7 strata with 375 decisions have no labelled record (mostly exact-path strata and small bands); they do not enter the weighted estimates. Top by size:

| stratum | population |
|---|---|
| gleif_l1\|abstain\|NO_CANDIDATE\|none\|au | 323 |
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
| gleif_l1->abr | 198 | 189 | 188 | 1 | 99.5% (97.1 to 99.9) | 197 | 9 | 95.4% (91.5 to 97.6) | 100.0% / 99.4% |
| gleif_l1->asic_company | 12 | 12 | 12 | 0 | 100.0% (75.7 to 100.0) | 12 | 0 | 100.0% (75.7 to 100.0) | 100.0% / 100.0% |
| gleif_l1->none | 98 | 0 | 0 | 0 | n/a (n/a) | 0 | 0 | n/a (n/a) | n/a / n/a |


### By tier

| tier | labelled | links | correct | wrong | precision (95% CI) | true target in graph | missed | recall (95% CI) | weighted P / R |
|---|---|---|---|---|---|---|---|---|---|
| tier 2 | 419 | 281 | 280 | 1 | 99.6% (98.0 to 99.9) | 301 | 21 | 93.0% (89.6 to 95.4) | 100.0% / 99.5% |
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
| tier 2 | gleif_l1 | abstain | 107 | 0 | 0 | 0 | n/a (n/a) | 9 | 9 | 0.0% (0.0 to 29.9) | n/a / 0.0% |
| tier 2 | gleif_l1 | exact | 45 | 45 | 45 | 0 | 100.0% (92.1 to 100.0) | 45 | 0 | 100.0% (92.1 to 100.0) | 100.0% / 100.0% |
| tier 2 | gleif_l1 | name | 156 | 156 | 155 | 1 | 99.4% (96.5 to 99.9) | 155 | 0 | 100.0% (97.6 to 100.0) | 99.4% / 100.0% |
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
| gleif_l1 | NAME_FUZZY | 23 | 23 | 22 | 1 | 95.7% (79.0 to 99.2) | 22 | 0 | 100.0% (85.1 to 100.0) | 95.8% / 100.0% |
| gleif_l1 | NAME_NORMALISED_EXACT | 133 | 133 | 133 | 0 | 100.0% (97.2 to 100.0) | 133 | 0 | 100.0% (97.2 to 100.0) | 100.0% / 100.0% |


### GLEIF name-path links by jurisdiction segment

| segment | labelled | links | correct | wrong | precision (95% CI) | true target in graph | missed | recall (95% CI) | weighted P / R |
|---|---|---|---|---|---|---|---|---|---|
| au | 131 | 131 | 130 | 1 | 99.2% (95.8 to 99.9) | 130 | 0 | 100.0% (97.1 to 100.0) | 99.3% / 100.0% |
| foreign | 25 | 25 | 25 | 0 | 100.0% (86.7 to 100.0) | 25 | 0 | 100.0% (86.7 to 100.0) | 100.0% / 100.0% |


Overall (all labelled, sample counts): 288 links, 1 wrong, precision 99.7% (98.1 to 99.9); recall 93.2% over 308 in-graph records.


### The same labels against other matcher versions

Sample counts on every labelled record each version decided. The label sample was drawn on v2's and then v3's strata, so these rows compare versions on the same records; they are not population estimates for the other versions.

| version | subset | labelled | links | wrong | precision (95% CI) | missed | recall (95% CI) |
|---|---|---|---|---|---|---|---|
| m-94f4f6b2-d37e44c6 | all | 439 | 288 | 1 | 99.7% (98.1 to 99.9) | 21 | 93.2% (89.8 to 95.5) |
| m-94f4f6b2-d37e44c6 | exact | 132 | 132 | 0 | 100.0% (97.2 to 100.0) | 0 | 100.0% (97.2 to 100.0) |
| m-94f4f6b2-d37e44c6 | name links | 156 | 156 | 1 | 99.4% (96.5 to 99.9) | 0 | 100.0% (97.6 to 100.0) |
| m-1465a4ba-e5444596 | all | 404 | 295 | 44 | 85.1% (80.6 to 88.7) | 28 | 90.0% (85.9 to 93.0) |
| m-1465a4ba-e5444596 | exact | 109 | 109 | 0 | 100.0% (96.6 to 100.0) | 0 | 100.0% (96.6 to 100.0) |
| m-1465a4ba-e5444596 | name links | 186 | 186 | 44 | 76.3% (69.7 to 81.9) | 1 | 99.3% (96.1 to 99.9) |
| mr-94f4f6b2-f3b4d9f4 | all | 308 | 190 | 0 | 100.0% (98.0 to 100.0) | 19 | 90.9% (86.2 to 94.1) |
| mr-94f4f6b2-f3b4d9f4 | exact | 45 | 45 | 0 | 100.0% (92.1 to 100.0) | 0 | 100.0% (92.1 to 100.0) |
| mr-94f4f6b2-f3b4d9f4 | name links | 145 | 145 | 0 | 100.0% (97.4 to 100.0) | 0 | 100.0% (97.4 to 100.0) |


## 3. Every wrong link and every miss in the labelled set

**Wrong links: 1.**

| sample_id | source | record_id | reference | match_type | score | linked to | true target | blind | evidence |
|---|---|---|---|---|---|---|---|---|---|
| S0c558d8bb5 | gleif_l1 | 549300V4V1DAUMTTC877 | Genesee & Wyoming Australia Pty Ltd | NAME_FUZZY | 0.95 | urn:abn:68080579308 ARC INFRASTRUCTURE HOLDINGS NO 1 PTY LTD | NOT_IN_GRAPH | yes | 'Genesee & Wyoming Australia Pty Ltd', Keswick Adelaide SA. ASIC: the name is a former name of AURIZON BULK CENTRAL PTY LTD (ACN 079444296, Adelaide operator), not in the graph. (ARC INFRASTRUCTURE HOLDINGS NO 1, WA, also once used a similar name; the Adelaide address points to the SA company.) |


**Missed (abstained although the true party is in the graph): 21.**

| sample_id | source | reference | abstain reason | best candidate | true target |
|---|---|---|---|---|---|
| S47a42a9617 | asic_afsl | WAN, VICTOR KIT | PARTY_TYPE_CONFLICT | urn:abn:87290948916 | urn:abn:87290948916 VICTOR KIT WAH WAN |
| S147859486f | asic_afsl | CHAMPION, DAVID RUSSELL | PARTY_TYPE_CONFLICT | urn:abn:33640626581 | urn:abn:33640626581 DAVID RUSSELL CHAMPION |
| S42c468870f | asic_afsl | SALTER, GEOFFREY GORDON | PARTY_TYPE_CONFLICT | urn:abn:98951387736 | urn:abn:98951387736 GEOFFREY GORDON SALTER |
| S535402f30f | asic_afsl | GU, LI | PARTY_TYPE_CONFLICT | urn:abn:12303231943 | urn:abn:12303231943 LI GU |
| S4ea917a14d | asic_afsl | FROST, KYLE CLIFFORD | PARTY_TYPE_CONFLICT | urn:abn:80620929309 | urn:abn:80620929309 KYLE CLIFFORD FROST |
| Sc9228d8fbb | asic_afsl | PASKALIDIS, ANGELOS EVANGELOS | PARTY_TYPE_CONFLICT | urn:abn:97928830776 | urn:abn:97928830776 EVANGELOS PASKALIDIS |
| Sedd80fd6b9 | asic_afsl | SAWERES, SHERENE | PARTY_TYPE_CONFLICT | urn:abn:43896454640 | urn:abn:43896454640 SHERENE SAWERES |
| Sa853a29164 | asic_afsl | SUN, PAUL | PARTY_TYPE_CONFLICT | urn:abn:14877103674 | urn:abn:14877103674 PAUL SUN |
| Sb45e875585 | asic_credit | WHYTE, BENJAMIN JOHN | BELOW_THRESHOLD | urn:abn:15745649351 | urn:abn:15745649351 BENJAMIN JOHN WHYTE |
| Sfd0da40a14 | asic_credit | PLUMB, ROBERT CHARLES | BELOW_THRESHOLD | urn:abn:70565772914 | urn:abn:70565772914 ROBERT CHARLES PLUMB |
| S5254559e1e | asic_credit | TRUSTEES OF THE RM LINTON FAMILY TRUST | BELOW_THRESHOLD | urn:abn:66902383651 | urn:abn:66902383651 The trustee for The RM Linton Family Trust |
| S287b774c23 | asic_liquidator | LEDGER, ALAN EDSON | BELOW_THRESHOLD | urn:abn:57650942525 | urn:abn:57650942525 ALAN EDSON LEDGER |
| S50fcd855cc | gleif_l1 | Browning Family Super (''The Fund'') | BELOW_THRESHOLD | urn:abn:51037296725 | urn:abn:56315290319 The Trustee for Browning Family Super |
| S7f2a2b41a5 | gleif_l1 | THE EILISTRAEE NO 2 TRUST | BELOW_THRESHOLD | urn:abn:77669508760 | urn:abn:77669508760 The Trustee for Eilistraee No. 2 Trust |
| S957b03cf74 | gleif_l1 | MPF DIVERSIFIED FUND NO.2 | BELOW_THRESHOLD | urn:abn:81102464940 | urn:abn:81102464940 The Trustee for the MPF Diversified Fund No.2 |
| S9831c8c512 | gleif_l1 | PAC GLOBAL ESPORTS FUND | BELOW_THRESHOLD | urn:abn:68800507120 | urn:abn:68800507120 The Trustee for PAC GLOBAL ESPORTS FUND |
| Sf1d23bedc9 | gleif_l1 | The Trustee for Marketing Seven Trust | BELOW_THRESHOLD | urn:abn:81961915252 | urn:abn:81961915252 The Trustee for MARKETING SEVEN TRUST |
| S4a3dc2c33f | gleif_l1 | GE ENERGY OPTIMIZATION AND CONTROL PTY LTD | JURISDICTION_MISMATCH | urn:abn:97082286913 | urn:abn:97082286913 BAKER HUGHES DIGITAL SOLUTIONS AUSTRALIA PTY LTD |
| S54e87feae2 | gleif_l1 | REVOLUT PAYMENTS NEW ZEALAND PTY LIMITED | JURISDICTION_MISMATCH | urn:abn:89645171651 | urn:abn:89645171651 REVOLUT PAYMENTS NEW ZEALAND PTY LTD |
| Sdc7c969a17 | gleif_l1 | MECS CAPITAL MANAGEMENT PTY LTD | JURISDICTION_MISMATCH | urn:abn:47650269677 | urn:abn:47650269677 MECS CAPITAL MANAGEMENT PTY LTD |
| S8ce9f5ef4e | gleif_l1 | SIEGEL PTY LTD | JURISDICTION_MISMATCH | urn:abn:35609511542 | urn:abn:35609511542 SIEGEL PTY LTD |


**UNSURE (excluded): 24.** The decision is shown so a human can settle them.

| sample_id | source | reference | decision | outcome | target | why unsure |
|---|---|---|---|---|---|---|
| Sb4743f3f9e | asic_credit | BLUE AEGIS PTY LTD | link | EXACT_ABN | urn:abn:68694439024 ROYGO FINANCE PTY LTD | Credit register prints ABN 68694439024 for BLUE AEGIS PTY LTD (licence 2026-10-07) but ASIC and ABR both name that ACN/ABN 'ROYGO FINANCE PTY LTD' (registered 2026-01-16, no former names). Either a rename not yet in the snapshots or a wrong number on the register; cannot tell from the data. |
| S4f3270aeed | gleif_l1 | MACQUARIE BANK LIMITED | link | NAME_NORMALISED_EXACT | urn:abn:46008583542 MACQUARIE BANK LIMITED | GLEIF BRANCH LEI: Macquarie Bank Limited London branch (UK BR002678). Head entity MACQUARIE BANK LIMITED (ACN 008583542) is in the graph. Foreign branch: policy question. |
| Sd654d50c27 | gleif_l1 | GENETIC TECHNOLOGIES LIMITED | abstain | JURISDICTION_MISMATCH | urn:abn:17009212328 GENETIC TECHNOLOGIES LIMITED | GENETIC TECHNOLOGIES LIMITED on the NZ register (NZBN 9429000018333, Remuera). Could be the ASX-listed Australian company (ACN 009212328) registered in NZ as an overseas company, or an unrelated NZ company of the same name. Cannot tell. |
| S478544e8fa | gleif_l1 | APA Group | link | NAME_FUZZY | urn:abn:99091344704 APA GROUP LIMITED | 'APA Group' (stapled group, LEI legal form 'COMPANY'). APA GROUP LIMITED (ACN 091344704) is one company inside the stapled structure; whether the LEI is for that company or the stapled group is unclear. |
| S892cfa9d66 | gleif_l1 | PO VALLEY OPERATIONS PTY LTD | link | NAME_NORMALISED_EXACT | urn:abn:46083354269 PO VALLEY OPERATIONS PTY LIMITED | GLEIF BRANCH LEI: Po Valley Operations Pty Ltd, Italian branch (Rome). Head entity PO VALLEY OPERATIONS PTY LIMITED (ACN 083354269) in the graph. Foreign branch: policy question. |
| S523009f69e | gleif_l1 | 43 DEGREES SOUTH PTY LIMITED | abstain | JURISDICTION_MISMATCH | urn:abn:79613231664 43 DEGREES SOUTH PTY LTD | AMENDED DURING CENSUS (original blind label NONE). '43 DEGREES SOUTH PTY LIMITED' on the NZ register (8491629, Methven NZ). The census showed 'Pty' companies on the NZ register are often Australian companies registered in NZ as overseas companies (Siegel, Revolut Payments NZ), so this may be the Tasmanian 43 DEGREES SOUTH PTY LTD (ACN 613231664) registered in NZ. Cannot confirm either way: UNSURE. |
| Sf434544ae8 | gleif_l1 | AUSTRALIA AND NEW ZEALAND BANKING GROUP LIMITED | link | NAME_NORMALISED_EXACT | urn:abn:11005357522 AUSTRALIA AND NEW ZEALAND BANKING GROUP LIMITED | GLEIF BRANCH LEI: ANZ Paris branch (French registry). Head entity AUSTRALIA AND NEW ZEALAND BANKING GROUP LIMITED (ACN 005357522) in the graph. Foreign branch: policy question. |
| Se6684695e2 | gleif_l1 | Jacqueline Kim Stein ATF Stein Family Trust | abstain | BELOW_THRESHOLD | urn:abn:38245244171 The Trustee for The Stein Family Trust | 'Jacqueline Kim Stein ATF Stein Family Trust', Perth WA 6026, no number. Graph has three 'Stein Family Trust' trusts (6027, 6065, 6163) plus 'J Stein Family Trust' (6210); 6027 is adjacent to 6026 but nothing confirms the trustee. Cannot decide. |
| Se095d115bc | gleif_l1 | ELGAS LIMITED | abstain | JURISDICTION_MISMATCH | urn:abn:85002749260 ELGAS LIMITED | ELGAS LIMITED on the NZ register (NZBN 9429032428322, Penrose Auckland) with HQ North Ryde NSW, the address of the Australian ELGAS LIMITED (ACN 002749260). Possibly the Australian company's NZ overseas registration, possibly a separate NZ company. Cannot tell. |
| S77b2d58655 | gleif_l1 | MACQUARIE CORPORATE HOLDINGS PTY LIMITED | link | NAME_NORMALISED_EXACT | urn:abn:54096705109 MACQUARIE CORPORATE HOLDINGS PTY LIMITED | GLEIF BRANCH LEI: Macquarie Corporate Holdings Pty Limited, London branch (UK BR009622). Head entity (ACN 096705109) in the graph. Foreign branch: policy question. |
| S9dd137b8d6 | gleif_l1 | BEIERSDORF AUSTRALIA LTD | link | NAME_NORMALISED_EXACT | urn:abn:98000025623 BEIERSDORF AUSTRALIA LTD | GLEIF BRANCH LEI: Beiersdorf Australia Ltd, New Zealand branch (Auckland). Head entity BEIERSDORF AUSTRALIA LTD (ACN 000025623) in the graph. Foreign branch: policy question. |
| Sd4cc1897b9 | gleif_l1 | KOMATSU AUSTRALIA CORPORATE FINANCE PTY LTD | link | NAME_NORMALISED_EXACT | urn:abn:84067959666 KOMATSU AUSTRALIA CORPORATE FINANCE PTY LTD | GLEIF BRANCH LEI: Komatsu Australia Corporate Finance Pty Ltd, New Zealand branch (Auckland). Head entity (ACN 067959666) in the graph. Foreign branch: policy question. |
| S6d39c186cb | gleif_l1 | QBE INSURANCE INTERNATIONAL LIMITED | link | NAME_NORMALISED_EXACT | urn:abn:11000000948 QBE INSURANCE (INTERNATIONAL) LTD | GLEIF BRANCH LEI: QBE Insurance International Limited, French branch (RA000189). Head entity QBE INSURANCE (INTERNATIONAL) LTD (ACN 000000948) is in the graph. Foreign branch: policy question. |
| Sd4ca6b45f5 | gleif_l1 | China Construction Bank Corporation | link | NAME_NORMALISED_EXACT | urn:abn:24125167553 China Construction Bank Corporation | GLEIF record is the New Zealand BRANCH of China Construction Bank Corporation (Chinese bank). The graph party 'China Construction Bank Corporation' (ABN 24125167553, foreign company ARBN 125167553) is the same legal person's Australian registration. A branch is not a separate legal person but has its own LEI; whether to link a foreign branch to the AU-registered head entity is a policy decision. |
| S0eea39a327 | gleif_l1 | PRIMELINE PTY LTD ATF DONALD FAMILY TRUST | abstain | BELOW_THRESHOLD | urn:abn:29029528159 The trustee for DONALD FAMILY TRUST | GLEIF 'PRIMELINE PTY LTD ATF DONALD FAMILY TRUST', Beaumaris VIC 3193, no registration number, LEI lapsed. The only VIC 'DONALD FAMILY TRUST' in the graph (ABN 29029528159, VIC 3187) is in the graph because a different LEI (984500C9B89PQ0F4FD58, 'The trustee for DONALD FAMILY TRUST', Brighton VIC 3186, created 2001) names it. Different LEIs, different street addresses, trustee not stated for the ABN; 'Donald Family Trust' is a common name. Cannot confirm; leaning different. |
| Sbc8714c9b7 | gleif_l1 | ATTACH2 PTY LIMITED | abstain | JURISDICTION_MISMATCH | urn:abn:98634198691 ATTACH2 PTY LTD | 'ATTACH2 PTY LIMITED' on the NZ register (6254636, c/o PwC Wellington). 'Pty' suggests an Australian company registered in NZ as an overseas company, i.e. ATTACH2 PTY LTD (ACN 634198691, QLD), but the NZ number may predate the 2019 ACN. Cannot confirm. |
| Se9aea98759 | gleif_l1 | HEIDELBERG GRAPHIC EQUIPMENT LIMITED | abstain | JURISDICTION_MISMATCH | urn:abn:19004395779 HEIDELBERG GRAPHIC EQUIPMENT LIMITED | HEIDELBERG GRAPHIC EQUIPMENT LIMITED on the NZ register (Auckland). Possibly the Australian company (ACN 004395779) registered in NZ as an overseas company, possibly a separate NZ subsidiary of the same name. Cannot tell. |
| Sa9bfcee9a2 | gleif_l1 | THE HART SUPERANNUATION FUND | abstain | BELOW_THRESHOLD | urn:abn:51996950901 HART SUPERANNUATION FUND | AMENDED AFTER JOIN (original blind label NOT_IN_GRAPH). GLEIF 'THE HART SUPERANNUATION FUND', 5 Masthead Quay, postcode 4566 (Noosaville QLD) but region coded AU-NSW. The blind note said all graph Hart funds were WA; that was wrong: the candidate list also held HART SUPERANNUATION FUND, ABN 51996950901, Booral NSW 2425, stated by another LEI (25490012J71UB7JQBW08). A NSW region on a QLD address hints the fund moved from NSW, so the two LEIs may be one SMSF; equally a common name. Cannot decide: UNSURE. |
| S6c778ae0f2 | gleif_l1 | UniSuper | link | NAME_NORMALISED_EXACT | urn:abn:54006027121 UNISUPER LIMITED | AMENDED AFTER JOIN (blind label NOT_IN_GRAPH): the blind file listed this candidate, but my compact viewer dropped its alias / via columns, so I missed it. LEI legal name 'UniSuper', c/o UniSuper Limited, entity created 1983-01-01, registered 2012. Could be the fund (whose trustee is UniSuper Limited, not in the graph) or UNISUPER LIMITED (ACN 006027121, in the graph). Not decidable from the record. |
| S06f15a18dd | gleif_l1 | CMC MARKETS STOCKBROKING LIMITED | link | NAME_NORMALISED_EXACT | urn:abn:69081002851 CMC MARKETS STOCKBROKING LIMITED | GLEIF BRANCH LEI: CMC Markets Stockbroking Limited (NZ Branch), registered on the NZ register. Head entity CMC MARKETS STOCKBROKING LIMITED (ACN 081002851) is in the graph. Foreign branch of an Australian company: same policy question as the v2 branch rows. |
| S4e1d59192b | gleif_l1 | Phil Asker Pty Ltd | link | NAME_NORMALISED_EXACT | urn:abn:82063895876 CAPTAIN'S CHOICE PTY LTD | AMENDED AFTER JOIN (blind label NOT_IN_GRAPH): the blind file listed this candidate, but my compact viewer dropped its alias / via columns, so I missed it. Name swap: on 2017-04-11 ACN 063895876 (then PHIL ASKER PTY LTD, now CAPTAIN'S CHOICE PTY LTD, in the graph) and ACN 005001874 (then Captain's Choice, now PHIL ASKER PTY LTD, not in the graph) exchanged names. The LEI was registered 2013 and lapsed, which points to 063895876; its current legal name points to 005001874. Cannot decide. |
| Sa7bcb6093c | gleif_l1 | SMEC International Pty Limited | link | NAME_NORMALISED_EXACT | urn:abn:32065440619 SMEC INTERNATIONAL PTY. LIMITED | GLEIF record is an international BRANCH (Indian registry RA000394 F06919, Gurgaon) of SMEC International Pty Limited; the head entity SMEC INTERNATIONAL PTY. LIMITED (ACN 065440619) is in the graph. A branch is not a separate legal person, but GLEIF models it as its own LEI with an IS_INTERNATIONAL_BRANCH_OF edge. Whether it should link to the head company is a policy decision for a human. |
| Sbdadceffa8 | gleif_l1 | Shane Thomas McEwan & Dianne McEwan ATF Lifestyle Superannuation Fund | abstain | BELOW_THRESHOLD | urn:abn:93667727032 LIFESTYLE SUPERANNUATION FUND | 'Shane Thomas McEwan & Dianne McEwan ATF Lifestyle Superannuation Fund', c/o United Global Capital, Level 7 Melbourne. The VIC 'LIFESTYLE SUPERANNUATION FUND' (ABN 93667727032, 3013) is in the graph because another LEI (984500C594FDBD6D8939, Level 7 North Tower 459 Collins St) states it. Same adviser address and name, but many clients' SMSFs share an adviser address and the name is generic; trustees not visible for the ABN. Cannot decide. |
| Sd338fb78fa | gleif_l1 | Luerssen Australia international PTY LTD | abstain | JURISDICTION_MISMATCH | urn:abn:40637189345 LUERSSEN AUSTRALIA INTERNATIONAL PTY LTD | 'Luerssen Australia international PTY LTD', jurisdiction Saudi Arabia (Riyadh registry). A 'Pty Ltd' registered in Saudi Arabia is likely the Australian LUERSSEN AUSTRALIA INTERNATIONAL PTY LTD (ACN 637189345) registered there as a foreign company (a branch), but this cannot be confirmed. |


## 4. Blocking recall, own check on labelled records

Of 308 labelled records whose true party is in the graph, the true party was among the stored candidates of `m-94f4f6b2-d37e44c6` for 308 (100.0%). 

Identifier-stripped run `m-94f4f6b2-515e5260`: true party among stored candidates for 69 of 79 labelled in-graph records (87.3%); missing: S147859486f, S42c468870f, S47a42a9617, S4ea917a14d, S6740209833, S721db5a18a, Sa853a29164, Sc9228d8fbb, Sd6e62e590f, Sedd80fd6b9.


## 5. Name path without identifiers, and the threshold sweep

AFSL and credit records re-matched with every identifier stripped. Truth is the ABN (else ACN) the register itself prints on the record, looked up in the canonical identifier table: independent of the matcher's decisions. `blocking recall` = the true party is among the run's stored candidates. Recall here is over records that have identifier truth.

| version | source | threshold | truth records | links | correct | stale keys remapped | wrong | precision | recall | blocking recall | abstentions |
|---|---|---|---|---|---|---|---|---|---|---|---|
| mr-94f4f6b2-44a30657 | asic_afsl | 0.85 | 6913 | 6665 | 6664 | 248 | 1 | 100.0% | 96.4% | 99.39% | AMBIGUOUS 31, BELOW_THRESHOLD 208, NO_CANDIDATE 6, PARTY_TYPE_CONFLICT 3 |
| m-94f4f6b2-515e5260 | asic_afsl | 0.9 | 6913 | 6665 | 6664 | 248 | 1 | 100.0% | 96.4% | 99.39% | AMBIGUOUS 31, BELOW_THRESHOLD 208, NO_CANDIDATE 6, PARTY_TYPE_CONFLICT 3 |
| mr-94f4f6b2-d97495df | asic_afsl | 0.9 | 6913 | 6665 | 6664 | 248 | 1 | 100.0% | 96.4% | 99.39% | AMBIGUOUS 31, BELOW_THRESHOLD 208, NO_CANDIDATE 6, PARTY_TYPE_CONFLICT 3 |
| mr-94f4f6b2-b15857e2 | asic_afsl | 0.95 | 6913 | 6665 | 6664 | 248 | 1 | 100.0% | 96.4% | 99.39% | AMBIGUOUS 31, BELOW_THRESHOLD 208, NO_CANDIDATE 6, PARTY_TYPE_CONFLICT 3 |
| mr-94f4f6b2-44a30657 | asic_credit | 0.85 | 4525 | 3997 | 3997 | 159 | 0 | 100.0% | 88.3% | 98.48% | AMBIGUOUS 15, BELOW_THRESHOLD 502, NO_CANDIDATE 8, PARTY_TYPE_CONFLICT 3 |
| m-94f4f6b2-515e5260 | asic_credit | 0.9 | 4525 | 3997 | 3997 | 159 | 0 | 100.0% | 88.3% | 98.48% | AMBIGUOUS 15, BELOW_THRESHOLD 502, NO_CANDIDATE 8, PARTY_TYPE_CONFLICT 3 |
| mr-94f4f6b2-d97495df | asic_credit | 0.9 | 4525 | 3997 | 3997 | 159 | 0 | 100.0% | 88.3% | 98.48% | AMBIGUOUS 15, BELOW_THRESHOLD 502, NO_CANDIDATE 8, PARTY_TYPE_CONFLICT 3 |
| mr-94f4f6b2-b15857e2 | asic_credit | 0.95 | 4525 | 3997 | 3997 | 159 | 0 | 100.0% | 88.3% | 98.48% | AMBIGUOUS 15, BELOW_THRESHOLD 502, NO_CANDIDATE 8, PARTY_TYPE_CONFLICT 3 |


Labelled-sample view of `m-94f4f6b2-515e5260` (the same labels, this version's decisions):

| source | decision | labelled | links | correct | wrong | precision (95% CI) | true target in graph | missed | recall (95% CI) | weighted P / R |
|---|---|---|---|---|---|---|---|---|---|---|
| asic_afsl | abstain | 19 | 0 | 0 | 0 | n/a (n/a) | 12 | 12 | 0.0% (0.0 to 24.3) | n/a / 0.0% |
| asic_afsl | link | 31 | 31 | 31 | 0 | 100.0% (89.0 to 100.0) | 31 | 0 | 100.0% (89.0 to 100.0) | 100.0% / 100.0% |
| asic_credit | abstain | 17 | 0 | 0 | 0 | n/a (n/a) | 10 | 10 | 0.0% (0.0 to 27.8) | n/a / 0.0% |
| asic_credit | link | 26 | 26 | 26 | 0 | 100.0% (87.1 to 100.0) | 26 | 0 | 100.0% (87.1 to 100.0) | 100.0% / 100.0% |


## 6. Rows a human should check first

1. Every ACCC and banned-organisation **link** (a wrong one publishes an accusation): S0a82ad361a, S104fa9a54f, S187082f660, S32382bf8a7, S3c90842232, S692aa3e1e1, S8006ed7bce, S8087a23aee, S89dd867cee, Sa11bd4967b, Sb61dd676d5, Sb85857f6d3, Sdd84b09f46, Sf2baeceeac, Sf2c6b1af9a, Sf326e19dac, Sf8e48f5b66, Sfd483c527e, Sff4c7d6ae4.
2. Every ACCC and banned-organisation abstention labelled with a party in the graph: none.
3. Every wrong link in section 3 and every UNSURE row.
4. The non-blind census rows (labeller column says NOT blind), starting with the ones labelled as a party (foreign-company registrations, branches).
5. Ten random blind labels of each class (party / NONE / NOT_IN_GRAPH) to estimate the labeller's own error rate.


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

