# Evaluation of matcher version `m-1465a4ba-e5444596`


## 1. Sample and labels

242 labelled records: 171 labelled blind (evidence file only, no score or decision), 71 labelled in a census that was not blind (see notes, section N2). UNSURE: 12, excluded from every metric.

| source | NONE | NOT_IN_GRAPH | UNSURE | party in graph | total |
|---|---|---|---|---|---|
| accc_notice | 2 | 11 | 0 | 7 | 20 |
| asic_afsl | 0 | 5 | 0 | 25 | 30 |
| asic_banned_org | 0 | 3 | 0 | 12 | 15 |
| asic_credit | 0 | 3 | 1 | 25 | 29 |
| asic_liquidator | 0 | 2 | 0 | 1 | 3 |
| gleif_l1 | 53 | 16 | 11 | 65 | 145 |


Strata of `m-1465a4ba-e5444596` that hold labelled records (stratum = source | decision | match type or abstain reason | score band | segment; segment is `foreign` / `au` for GLEIF legal jurisdiction):

| stratum | population | labelled |
|---|---|---|
| accc_notice\|abstain\|BELOW_THRESHOLD\|far\| | 10 | 10 |
| accc_notice\|abstain\|NO_CANDIDATE\|none\| | 3 | 3 |
| accc_notice\|link\|EXACT_ACN\|id\| | 7 | 7 |
| asic_afsl\|abstain\|BELOW_THRESHOLD\|far\| | 30 | 4 |
| asic_afsl\|abstain\|BELOW_THRESHOLD\|near0.05\| | 2 | 1 |
| asic_afsl\|link\|EXACT_ABN\|id\| | 6351 | 19 |
| asic_afsl\|link\|EXACT_ACN\|id\| | 168 | 6 |
| asic_banned_org\|abstain\|BELOW_THRESHOLD\|far\| | 3 | 3 |
| asic_banned_org\|link\|EXACT_ACN\|id\| | 12 | 12 |
| asic_credit\|abstain\|BELOW_THRESHOLD\|far\| | 58 | 1 |
| asic_credit\|abstain\|BELOW_THRESHOLD\|near0.05\| | 11 | 1 |
| asic_credit\|abstain\|BELOW_THRESHOLD\|near0.10\| | 4 | 1 |
| asic_credit\|abstain\|NO_CANDIDATE\|none\| | 1 | 1 |
| asic_credit\|link\|EXACT_ABN\|id\| | 3846 | 18 |
| asic_credit\|link\|EXACT_ACN\|id\| | 387 | 6 |
| asic_credit\|link\|NAME_NORMALISED_EXACT\|ge0.97\| | 1 | 1 |
| asic_liquidator\|abstain\|BELOW_THRESHOLD\|far\| | 622 | 1 |
| asic_liquidator\|abstain\|BELOW_THRESHOLD\|near0.05\| | 10 | 1 |
| asic_liquidator\|abstain\|BELOW_THRESHOLD\|near0.10\| | 26 | 1 |
| gleif_l1\|abstain\|AMBIGUOUS\|near0.05\|au | 34 | 4 |
| gleif_l1\|abstain\|AMBIGUOUS\|near0.05\|foreign | 36 | 4 |
| gleif_l1\|abstain\|BELOW_THRESHOLD\|far\|au | 4574 | 8 |
| gleif_l1\|abstain\|BELOW_THRESHOLD\|far\|foreign | 4686 | 3 |
| gleif_l1\|abstain\|BELOW_THRESHOLD\|near0.05\|au | 322 | 1 |
| gleif_l1\|abstain\|BELOW_THRESHOLD\|near0.05\|foreign | 238 | 1 |
| gleif_l1\|abstain\|BELOW_THRESHOLD\|near0.10\|au | 400 | 1 |
| gleif_l1\|abstain\|BELOW_THRESHOLD\|near0.10\|foreign | 159 | 1 |
| gleif_l1\|abstain\|IDENTIFIER_CONFLICT\|near0.05\|au | 3 | 3 |
| gleif_l1\|abstain\|NO_CANDIDATE\|none\|foreign | 608 | 3 |
| gleif_l1\|abstain\|PARTY_TYPE_CONFLICT\|far\|au | 41 | 3 |
| gleif_l1\|link\|EXACT_ABN\|id\|au | 14115 | 10 |
| gleif_l1\|link\|EXACT_ACN\|id\|au | 33809 | 12 |
| gleif_l1\|link\|NAME_FUZZY\|ge0.97\|au | 12 | 5 |
| gleif_l1\|link\|NAME_FUZZY\|ge0.97\|foreign | 3 | 3 |
| gleif_l1\|link\|NAME_NORMALISED_EXACT\|ge0.97\|au | 166 | 11 |
| gleif_l1\|link\|NAME_NORMALISED_EXACT\|ge0.97\|foreign | 72 | 72 |


3 strata with 330 decisions have no labelled record (mostly exact-path strata and small bands); they do not enter the weighted estimates. Top by size:

| stratum | population |
|---|---|
| gleif_l1\|abstain\|NO_CANDIDATE\|none\|au | 326 |
| asic_liquidator\|abstain\|NO_CANDIDATE\|none\| | 2 |
| gleif_l1\|link\|EXACT_ABN\|id\|foreign | 2 |


## 2. Precision and recall

Precision = links to the labelled true party / links. Recall = links to the true party / records whose true party is in the graph (NONE and NOT_IN_GRAPH records are not in the recall denominator; an abstention on them is correct). `sample` columns are raw counts in the labelled sample with Wilson 95% intervals. `weighted` re-weights each labelled record by population / labelled of its stratum (post-stratification), so oversampled strata (near-threshold abstentions, the foreign census) do not dominate; strata with no labelled record are missing from it.

### By source pair

| source_pair | labelled | links | correct | wrong | precision (95% CI) | true target in graph | missed | recall (95% CI) | weighted P / R |
|---|---|---|---|---|---|---|---|---|---|
| accc_notice->abr | 7 | 7 | 7 | 0 | 100.0% (64.6 to 100.0) | 7 | 0 | 100.0% (64.6 to 100.0) | 100.0% / 100.0% |
| accc_notice->none | 13 | 0 | 0 | 0 | n/a (n/a) | 0 | 0 | n/a (n/a) | n/a / n/a |
| asic_afsl->abr | 20 | 20 | 20 | 0 | 100.0% (83.9 to 100.0) | 20 | 0 | 100.0% (83.9 to 100.0) | 100.0% / 100.0% |
| asic_afsl->asic_company | 5 | 5 | 5 | 0 | 100.0% (56.6 to 100.0) | 5 | 0 | 100.0% (56.6 to 100.0) | 100.0% / 100.0% |
| asic_afsl->none | 5 | 0 | 0 | 0 | n/a (n/a) | 0 | 0 | n/a (n/a) | n/a / n/a |
| asic_banned_org->abr | 12 | 12 | 12 | 0 | 100.0% (75.7 to 100.0) | 12 | 0 | 100.0% (75.7 to 100.0) | 100.0% / 100.0% |
| asic_banned_org->none | 3 | 0 | 0 | 0 | n/a (n/a) | 0 | 0 | n/a (n/a) | n/a / n/a |
| asic_credit->abr | 19 | 18 | 18 | 0 | 100.0% (82.4 to 100.0) | 19 | 1 | 94.7% (75.4 to 99.1) | 100.0% / 99.7% |
| asic_credit->asic_company | 6 | 6 | 6 | 0 | 100.0% (61.0 to 100.0) | 6 | 0 | 100.0% (61.0 to 100.0) | 100.0% / 100.0% |
| asic_credit->none | 3 | 0 | 0 | 0 | n/a (n/a) | 0 | 0 | n/a (n/a) | n/a / n/a |
| asic_liquidator->abr | 1 | 0 | 0 | 0 | n/a (n/a) | 1 | 1 | 0.0% (0.0 to 79.3) | n/a / 0.0% |
| asic_liquidator->none | 2 | 0 | 0 | 0 | n/a (n/a) | 0 | 0 | n/a (n/a) | n/a / n/a |
| gleif_l1->abr | 104 | 99 | 55 | 44 | 55.6% (45.7 to 65.0) | 61 | 6 | 90.2% (80.2 to 95.4) | 99.8% / 99.8% |
| gleif_l1->asic_company | 4 | 4 | 4 | 0 | 100.0% (51.0 to 100.0) | 4 | 0 | 100.0% (51.0 to 100.0) | 100.0% / 100.0% |
| gleif_l1->none | 26 | 0 | 0 | 0 | n/a (n/a) | 0 | 0 | n/a (n/a) | n/a / n/a |


### By tier

| tier | labelled | links | correct | wrong | precision (95% CI) | true target in graph | missed | recall (95% CI) | weighted P / R |
|---|---|---|---|---|---|---|---|---|---|
| tier 2 | 210 | 164 | 120 | 44 | 73.2% (65.9 to 79.4) | 128 | 8 | 93.8% (88.2 to 96.8) | 99.9% / 99.8% |
| tier 3 | 20 | 7 | 7 | 0 | 100.0% (64.6 to 100.0) | 7 | 0 | 100.0% (64.6 to 100.0) | 100.0% / 100.0% |


### By tier and path (exact vs name)

| tier | source | path_group | labelled | links | correct | wrong | precision (95% CI) | true target in graph | missed | recall (95% CI) | weighted P / R |
|---|---|---|---|---|---|---|---|---|---|---|---|
| tier 2 | asic_afsl | abstain | 5 | 0 | 0 | 0 | n/a (n/a) | 0 | 0 | n/a (n/a) | n/a / n/a |
| tier 2 | asic_afsl | exact | 25 | 25 | 25 | 0 | 100.0% (86.7 to 100.0) | 25 | 0 | 100.0% (86.7 to 100.0) | 100.0% / 100.0% |
| tier 2 | asic_banned_org | abstain | 3 | 0 | 0 | 0 | n/a (n/a) | 0 | 0 | n/a (n/a) | n/a / n/a |
| tier 2 | asic_banned_org | exact | 12 | 12 | 12 | 0 | 100.0% (75.7 to 100.0) | 12 | 0 | 100.0% (75.7 to 100.0) | 100.0% / 100.0% |
| tier 2 | asic_credit | abstain | 4 | 0 | 0 | 0 | n/a (n/a) | 1 | 1 | 0.0% (0.0 to 79.3) | n/a / 0.0% |
| tier 2 | asic_credit | exact | 23 | 23 | 23 | 0 | 100.0% (85.7 to 100.0) | 23 | 0 | 100.0% (85.7 to 100.0) | 100.0% / 100.0% |
| tier 2 | asic_credit | name | 1 | 1 | 1 | 0 | 100.0% (20.7 to 100.0) | 1 | 0 | 100.0% (20.7 to 100.0) | 100.0% / 100.0% |
| tier 2 | asic_liquidator | abstain | 3 | 0 | 0 | 0 | n/a (n/a) | 1 | 1 | 0.0% (0.0 to 79.3) | n/a / 0.0% |
| tier 2 | gleif_l1 | abstain | 31 | 0 | 0 | 0 | n/a (n/a) | 5 | 5 | 0.0% (0.0 to 43.4) | n/a / 0.0% |
| tier 2 | gleif_l1 | exact | 22 | 22 | 22 | 0 | 100.0% (85.1 to 100.0) | 22 | 0 | 100.0% (85.1 to 100.0) | 100.0% / 100.0% |
| tier 2 | gleif_l1 | name | 81 | 81 | 37 | 44 | 45.7% (35.3 to 56.5) | 38 | 1 | 97.4% (86.5 to 99.5) | 72.9% / 96.8% |
| tier 3 | accc_notice | abstain | 13 | 0 | 0 | 0 | n/a (n/a) | 0 | 0 | n/a (n/a) | n/a / n/a |
| tier 3 | accc_notice | exact | 7 | 7 | 7 | 0 | 100.0% (64.6 to 100.0) | 7 | 0 | 100.0% (64.6 to 100.0) | 100.0% / 100.0% |


### By match type (links only)

| source | outcome | labelled | links | correct | wrong | precision (95% CI) | true target in graph | missed | recall (95% CI) | weighted P / R |
|---|---|---|---|---|---|---|---|---|---|---|
| accc_notice | EXACT_ACN | 7 | 7 | 7 | 0 | 100.0% (64.6 to 100.0) | 7 | 0 | 100.0% (64.6 to 100.0) | 100.0% / 100.0% |
| asic_afsl | EXACT_ABN | 19 | 19 | 19 | 0 | 100.0% (83.2 to 100.0) | 19 | 0 | 100.0% (83.2 to 100.0) | 100.0% / 100.0% |
| asic_afsl | EXACT_ACN | 6 | 6 | 6 | 0 | 100.0% (61.0 to 100.0) | 6 | 0 | 100.0% (61.0 to 100.0) | 100.0% / 100.0% |
| asic_banned_org | EXACT_ACN | 12 | 12 | 12 | 0 | 100.0% (75.7 to 100.0) | 12 | 0 | 100.0% (75.7 to 100.0) | 100.0% / 100.0% |
| asic_credit | EXACT_ABN | 17 | 17 | 17 | 0 | 100.0% (81.6 to 100.0) | 17 | 0 | 100.0% (81.6 to 100.0) | 100.0% / 100.0% |
| asic_credit | EXACT_ACN | 6 | 6 | 6 | 0 | 100.0% (61.0 to 100.0) | 6 | 0 | 100.0% (61.0 to 100.0) | 100.0% / 100.0% |
| asic_credit | NAME_NORMALISED_EXACT | 1 | 1 | 1 | 0 | 100.0% (20.7 to 100.0) | 1 | 0 | 100.0% (20.7 to 100.0) | 100.0% / 100.0% |
| gleif_l1 | EXACT_ABN | 10 | 10 | 10 | 0 | 100.0% (72.2 to 100.0) | 10 | 0 | 100.0% (72.2 to 100.0) | 100.0% / 100.0% |
| gleif_l1 | EXACT_ACN | 12 | 12 | 12 | 0 | 100.0% (75.7 to 100.0) | 12 | 0 | 100.0% (75.7 to 100.0) | 100.0% / 100.0% |
| gleif_l1 | NAME_FUZZY | 4 | 4 | 1 | 3 | 25.0% (4.6 to 69.9) | 2 | 1 | 50.0% (9.5 to 90.5) | 40.0% / 50.0% |
| gleif_l1 | NAME_NORMALISED_EXACT | 77 | 77 | 36 | 41 | 46.8% (36.0 to 57.8) | 36 | 0 | 100.0% (90.4 to 100.0) | 75.0% / 100.0% |


### GLEIF name-path links by jurisdiction segment

| segment | labelled | links | correct | wrong | precision (95% CI) | true target in graph | missed | recall (95% CI) | weighted P / R |
|---|---|---|---|---|---|---|---|---|---|
| au | 12 | 12 | 10 | 2 | 83.3% (55.2 to 95.3) | 11 | 1 | 90.9% (62.3 to 98.4) | 87.3% / 96.3% |
| foreign | 69 | 69 | 27 | 42 | 39.1% (28.5 to 50.9) | 27 | 0 | 100.0% (87.5 to 100.0) | 38.7% / 100.0% |


Overall (all labelled, sample counts): 171 links, 44 wrong, precision 74.3% (67.2 to 80.2); recall 94.1% over 135 in-graph records.


## 3. Every wrong link and every miss in the labelled set

**Wrong links: 44.**

| sample_id | source | record_id | reference | match_type | score | linked to | true target | blind | evidence |
|---|---|---|---|---|---|---|---|---|---|
| S2507215567 | gleif_l1 | 5493006MGV6N1FOSU745 | HONEYWELL LIMITED | NAME_FUZZY | 1.0 | urn:abn:74000646882 HONEYWELL LTD | NONE | yes | New Zealand company HONEYWELL LIMITED (NZ company no. 528871, Auckland). The Australian HONEYWELL LTD (ACN 000646882) and the Honeywell Pty Ltds in the graph are different legal entities. |
| Sa4237531f6 | gleif_l1 | 21380086HA69B5QKA858 | THE MORA FAMILY TRUSTS | NAME_FUZZY | 0.9909 | urn:abn:38723391793 The Trustee for Mora Family Trust | NONE | yes | 'THE MORA FAMILY TRUSTS', New Zealand jurisdiction, Mount Maunganui NZ. The WA 'Mora Family Trust' (ABN 38723391793, 6056) is a different trust in a different country. |
| S50fcd855cc | gleif_l1 | 984500F38F7A2D2A6976 | Browning Family Super (''The Fund'') | NAME_FUZZY | 1.0 | urn:abn:51037296725 THE BROWNING FAMILY SUPER FUND | The Trustee for Browning Family Super | yes | GLEIF 'Browning Family Super', Silver Sands WA 6210, no number. ABR 'The Trustee for Browning Family Super', SMSF, WA 6210: same name and postcode. The other Browning super funds are in 6023 and 6158. |
| S6231099e50 | gleif_l1 | 213800KLGOHTJBOPQM08 | BERGER FAMILY TRUST | NAME_NORMALISED_EXACT | 0.97 | urn:abn:36947016725 THE BERGER FAMILY TRUST | NONE | no | NZ-jurisdiction trust administered from Liverpool UK. WA Berger family trust unrelated. |
| S19fad621a1 | gleif_l1 | 549300UMSTWSP7MVD483 | First Sentier Global Listed Infrastructure Fund | NAME_NORMALISED_EXACT | 0.97 | urn:abn:36755365249 THE TRUSTEE FOR FIRST SENTIER GLOBAL LISTED INFRASTRUCTURE FUND | NONE | no | New Zealand unit trust (legal form 'New Zealand Unit Trust', Auckland). The Australian First Sentier fund of the same name (ABN 36755365249) is a different trust. |
| S4f9d7e3b8a | gleif_l1 | 213800MA64OXHU32MZ47 | WANAKA TRUST | NAME_NORMALISED_EXACT | 0.97 | urn:abn:33787323883 The Trustee for THE WANAKA TRUST | NONE | no | NZ-jurisdiction trust administered in Port Vila, Vanuatu. WA Wanaka trust unrelated. |
| S90da9cb89f | gleif_l1 | 98450009ID1873885A04 | SDC Trust | NAME_NORMALISED_EXACT | 0.97 | urn:abn:23397064742 The Trustee for SDC Trust | NONE | no | NZ trust (Dunedin). WA SDC Trust unrelated. |
| Se56441e5c4 | gleif_l1 | 5299002L1XZHCTTRSW46 | CIVMEC LIMITED | NAME_NORMALISED_EXACT | 0.97 | urn:abn:19672407171 CIVMEC LIMITED | NONE | no | Singapore company CIVMEC LIMITED (201011837H). The graph's CIVMEC LIMITED (ACN 672407171, registered 2023, formerly CIVMEC AUSTRALIA LIMITED) is the new Australian holding company: a different legal entity. |
| Sfc267cf461 | gleif_l1 | 213800UP8J4MPSTQ5Z67 | WHITE TRUST | NAME_NORMALISED_EXACT | 0.97 | urn:abn:86571311285 The trustee for The White Trust | NONE | no | NZ trust (formerly A-Line Foreign Trust, Auckland). WA White trusts unrelated. |
| Sd0f0539414 | gleif_l1 | 254900LQYADJLQXM5N43 | Turtle Trust | NAME_NORMALISED_EXACT | 0.97 | urn:abn:47501149115 The Trustee for THE TURTLE TRUST | NONE | no | NZ discretionary trust (Landmark Fiduciary, Auckland / Geneva). WA Turtle trusts unrelated. |
| Se1175eb24d | gleif_l1 | 529900YF3OCCIJP2AJ84 | The Bolivar Trust | NAME_NORMALISED_EXACT | 0.97 | urn:abn:23792933990 BOLIVAR TRUST | NONE | no | NZ-jurisdiction trust with a Geneva address. TAS Bolivar Trust unrelated. |
| Sd0823f1a70 | gleif_l1 | 213800YOEO5OQ72G2R82 | RIO TINTO PLC | NAME_NORMALISED_EXACT | 0.97 | urn:abn:96004458404 RIO TINTO LIMITED | NONE | no | UK plc RIO TINTO PLC (00719885). RIO TINTO LIMITED (ACN 004458404) is the separate Australian company of the dual-listed structure: a different legal entity. |
| S8e75232824 | gleif_l1 | 213800H9WEXP18WLOO50 | THE O'CONNOR TRUST | NAME_NORMALISED_EXACT | 0.97 | urn:abn:90943528643 O'CONNOR TRUST | NONE | no | NZ trust (c/o Armour Trust Company, Auckland). WA O'Connor trusts unrelated. |
| S1ce7672bd1 | gleif_l1 | 213800YPF8WK2Y1YUP16 | RANNOCH TRUST | NAME_NORMALISED_EXACT | 0.97 | urn:abn:82733812760 The trustee for Rannoch Trust | NONE | no | NZ trust (Takapuna). TAS 'Rannoch Trust' is a different trust. |
| Sd318987833 | gleif_l1 | 213800VWJO283EZ3VB97 | THE JUNO TRUST | NAME_NORMALISED_EXACT | 0.97 | urn:abn:93125716460 The Trustee for The Juno Trust | NONE | no | NZ trust (Infides, Wellington). WA Juno Trust unrelated. |
| S68874c9af6 | gleif_l1 | 213800B3QDM7F2KJRC12 | MIDDLETON TRUST | NAME_NORMALISED_EXACT | 0.97 | urn:abn:53299240842 THE TRUSTEE FOR MIDDLETON TRUST | NONE | no | NZ trust (New Zealand Trust Corporation, Auckland). WA Middleton trusts unrelated. |
| S3356dc44fd | gleif_l1 | YJKE4YIT6BWQHVEW0D14 | THE TORO COMPANY | NAME_NORMALISED_EXACT | 0.97 | urn:abn:82008490159 HAVEN LICENSING PTY. LIMITED | NONE | no | The Toro Company (Delaware, HQ Minnesota). No Australian registration in the graph; the link target HAVEN LICENSING PTY LIMITED (via a business name) is a different entity. |
| S26ad4bd012 | gleif_l1 | 98450059AZDD5CB65510 | The Marvic Family Trust | NAME_NORMALISED_EXACT | 0.97 | urn:abn:83623505814 The Trustee for Marvic Family Trust | NONE | no | NZ trust (Mount Maunganui). WA Marvic Family Trust is a different trust. |
| S25817eff25 | gleif_l1 | 529900Z1EE9387L6R032 | The Geoff Trust | NAME_NORMALISED_EXACT | 0.97 | urn:abn:65924597583 The Trustee for THE GEOFF TRUST | NONE | no | NZ-jurisdiction trust, Swiss trustee (Geneva). WA 'Geoff ...' trusts unrelated. |
| S85b96f5fca | gleif_l1 | 254900HOREGPW1P48193 | KALOS TRUST | NAME_NORMALISED_EXACT | 0.97 | urn:abn:84915549353 KALOS TRUST | NONE | no | NZ trust (Auckland). WA Kalos Trust unrelated. |
| Sc364ede196 | gleif_l1 | 254900SWCZN4CKLFZV83 | VanEck Investments Limited | NAME_NORMALISED_EXACT | 0.97 | urn:abn:22146596116 VANECK INVESTMENTS LIMITED | NONE | no | Irish company VanEck Investments Limited (CRO 545342, Dublin). VANECK INVESTMENTS LIMITED in the graph is an Australian public company (ACN 146596116): a different legal entity. |
| S8abb29025d | gleif_l1 | 254900AFLC58ODCNXV49 | Stanwell Limited | NAME_NORMALISED_EXACT | 0.97 | urn:abn:37078848674 STANWELL CORPORATION LIMITED | NONE | no | NZ company Stanwell Limited (NZBN 9429030001954, Auckland). STANWELL CORPORATION LIMITED (QLD government generator, ACN 078848674) is unrelated. |
| Sf72b92f04c | gleif_l1 | 984500J06DCA983A8426 | FARMLANDS MATHIAS INTERNATIONAL | NAME_NORMALISED_EXACT | 0.97 | urn:abn:12097363472 FARMLANDS MATHIAS INTERNATIONAL PTY LTD | NONE | no | NZ company FARMLANDS MATHIAS INTERNATIONAL (NZBN 9429036791743, Auckland). FARMLANDS MATHIAS INTERNATIONAL PTY LTD (ACN 097363472, VIC) is a separate Australian company. |
| Sfd2e244e76 | gleif_l1 | 529900COYGJUS6P2JL28 | Felix Trust | NAME_NORMALISED_EXACT | 0.97 | urn:abn:14158371374 The trustee for Felix Trust | NONE | no | NZ-jurisdiction trust, Swiss trustee (Geneva). WA Felix Trust unrelated. |
| S4be6ec020e | gleif_l1 | 254900KU2D736EFUPK46 | Prism Global Group Plc | NAME_NORMALISED_EXACT | 0.97 | urn:abn:65630730415 PZM LTD | NONE | no | UK plc Prism Global Group Plc (14476793). Not in the graph; PRISM GLOBAL GROUP MARKET SERVICES PTY LTD and the link target PZM LTD are different entities. |
| S01e262198d | gleif_l1 | 2138001KJ9UCWA9BI657 | THE ELEVEN TRUST | NAME_NORMALISED_EXACT | 0.97 | urn:abn:24691486289 The Trustee for The Eleven Trust | NONE | no | NZ-jurisdiction trust with a Swiss trustee (Geneva). No Australian entity; the WA 'Eleven' trusts are unrelated. |
| S44151ac8c2 | gleif_l1 | 549300DFWSDH2YVXFB41 | THE CF TRUST | NAME_NORMALISED_EXACT | 0.97 | urn:abn:17392044669 The Trustee for CF Trust | NONE | no | NZ fund/trust (Auckland). WA 'CF Trust' unrelated. |
| S3edec911f8 | gleif_l1 | 5493005HF4FUC48VS377 | BHP BILLITON FINANCE PLC | NAME_NORMALISED_EXACT | 0.97 | urn:abn:82008519319 BHP BILLITON FINANCE LIMITED | NONE | no | UK plc BHP Billiton Finance plc (Companies House 06683534). BHP BILLITON FINANCE LIMITED (ACN 008519319) is a different legal entity in the same group. |
| Sc2cd9dfe25 | gleif_l1 | 8945009I9Y4G8PGIHB51 | The Kanda Trust | NAME_NORMALISED_EXACT | 0.97 | urn:abn:66733056218 The Trustee for KANDA TRUST | NONE | no | New Zealand family trust (Auckland). WA Kanda Trust unrelated. |
| Sa4a7e2ebdd | gleif_l1 | 2138007CKQT9UOJ4Q861 | THE SLATTER FAMILY TRUST | NAME_NORMALISED_EXACT | 0.97 | urn:abn:14906817859 The Trustee for Slatter Family Trust | NONE | no | NZ trust (c/o Armour Trust Company, Auckland). TAS Slatter Family Trust unrelated. |
| S197243b01f | gleif_l1 | 5299004RWZD1R6ZW1115 | BOC LIMITED | NAME_NORMALISED_EXACT | 0.97 | urn:abn:95000029729 BOC LIMITED | NONE | no | NZ company BOC LIMITED (NZBN 9429040953946, Penrose Auckland). The Australian BOC LIMITED (ACN 000029729) is a separate company in the same group. |
| S1145bc36b8 | gleif_l1 | 549300YBEM9WY8VF8M82 | EATON INDUSTRIES COMPANY | NAME_NORMALISED_EXACT | 0.97 | urn:abn:66103014571 Eaton Industries Pty Ltd | NONE | no | NZ company (NZ co. 284932, Christchurch, unlimited 'Company' form). EATON INDUSTRIES PTY LTD (VIC, ACN 103014571) is a different legal entity. |
| Sd31849b0c6 | gleif_l1 | 2138009KNM1C2KMGLD89 | AQUARIUS TRUST | NAME_NORMALISED_EXACT | 0.97 | urn:abn:74769650979 The trustee for Aquarius Trust | NONE | no | NZ trust (Lakeview Trust Services, Auckland). TAS Aquarius Trust unrelated. |
| Sd6411ba517 | gleif_l1 | 2138006KKHGGG8XKSY05 | THE LUNA TRUST | NAME_NORMALISED_EXACT | 0.97 | urn:abn:60234210752 The trustee for Luna Trust | NONE | no | NZ trust (New Zealand Trust Corporation, Auckland). WA Luna trusts unrelated. |
| Sa04330b27a | gleif_l1 | 254900ENNBJ4E3CJ4876 | Jota Investments Pty LTd ATF the Arkad Trust | NAME_NORMALISED_EXACT | 0.97 | urn:abn:48700271312 The Trustee for ARKAD TRUST | NOT_IN_GRAPH | yes | 'Jota Investments Pty Ltd ATF the Arkad Trust', Medindie SA 5081, no number. Graph Arkad trusts are in TAS (7005) and WA (6726): different trusts; the SA trust is outside the slice. |
| Se4b2edfe65 | gleif_l1 | 254900UBCXV403DBTT64 | The Moonbeam Trust | NAME_NORMALISED_EXACT | 0.97 | urn:abn:21690985842 The Trustee for Moonbeam Trust | NONE | no | NZ-jurisdiction trust, Swiss trustee (Zurich). WA Moonbeam Trust unrelated. |
| S9c7bb1b41b | gleif_l1 | 3789005B3DE4B33A4B13 | Sanlam Private Wealth (Pty) Ltd | NAME_NORMALISED_EXACT | 0.97 | urn:abn:18136960775 SANLAM PRIVATE WEALTH PTY LTD | NONE | no | South African company Sanlam Private Wealth (Pty) Ltd (2000/023234/07). SANLAM PRIVATE WEALTH PTY LTD (ACN 136960775, formerly Calibre Investments) is a different, Australian company. |
| S8336ae54aa | gleif_l1 | 213800F3PYOQ65I11369 | THE HILLCREST TRUST. | NAME_NORMALISED_EXACT | 0.97 | urn:abn:44880044573 THE HILLCREST TRUST | NONE | no | NZ trust (c/o Armour Trust Company, Auckland). WA Hillcrest trust unrelated. |
| S554fe50f43 | gleif_l1 | 8945006G6H6YVJL0MT73 | The Aston Family Trust | NAME_NORMALISED_EXACT | 0.97 | urn:abn:75448532953 The trustee for the aston family trust | NONE | no | NZ trust (Intrust Trustees (New Zealand) Limited as trustee, Auckland). WA aston family trust unrelated. |
| Sbf4755330f | gleif_l1 | 549300BMWNY2916W5G72 | STUDIOCANAL | NAME_NORMALISED_EXACT | 0.97 | urn:abn:64096774015 STUDIOCANAL PTY LIMITED | NONE | no | French company STUDIOCANAL (RCS 056 801 293). STUDIOCANAL PTY LIMITED (ACN 096774015, formerly Hoyts Distribution) is an Australian subsidiary: a different legal entity. |
| S7bc0b1b271 | gleif_l1 | 2138003W81KT4G3WAV31 | THE CAMEL TRUST | NAME_NORMALISED_EXACT | 0.97 | urn:abn:84245082804 The Trustee for The Camel Trust | NONE | no | NZ trust (Takapuna). WA Camel Trust unrelated. |
| Seb9017e622 | gleif_l1 | 9845004A552AE622BF30 | PRICEWATERHOUSECOOPERS | NAME_NORMALISED_EXACT | 0.97 | urn:abn:52780433757 PRICEWATERHOUSECOOPERS | NONE | no | PricewaterhouseCoopers New Zealand partnership (Auckland). The Australian PwC partnership (ABN 52780433757) is a different partnership. |
| S3e36c3ca85 | gleif_l1 | 213800Q4HPTHV9PTOJ16 | THE MCCORT FAMILY TRUST | NAME_NORMALISED_EXACT | 0.97 | urn:abn:92163071512 The Trustee for The McCort Family Trust | NONE | no | NZ trust (c/o Armour Trust Company, Auckland). WA McCort Family Trust is a different trust. |
| Se42e561d1d | gleif_l1 | 984500E3D7DAM4DOF718 | Fortlake Sigma Opportunities Fund | NAME_NORMALISED_EXACT | 0.97 | urn:abn:41547102160 THE TRUSTEE FOR FORTLAKE SIGMA OPPORTUNITIES FUND | NONE | no | Cayman Islands mutual fund (formerly AltD Feeder Fund Limited). The Australian listed unit trust of the same name (ABN 41547102160) is a different vehicle. |


**Missed (abstained although the true party is in the graph): 7.**

| sample_id | source | reference | abstain reason | best candidate | true target |
|---|---|---|---|---|---|
| Sb45e875585 | asic_credit | WHYTE, BENJAMIN JOHN | BELOW_THRESHOLD | urn:abn:15745649351 | urn:abn:15745649351 BENJAMIN JOHN WHYTE |
| S287b774c23 | asic_liquidator | LEDGER, ALAN EDSON | BELOW_THRESHOLD | urn:abn:57650942525 | urn:abn:57650942525 ALAN EDSON LEDGER |
| Sc7278ab6c2 | gleif_l1 | The Trustee For Hunter Investment Trust | AMBIGUOUS | urn:abn:56260271442 | urn:abn:56260271442 The Trustee for HUNTER INVESTMENT TRUST |
| Sa37a3fb195 | gleif_l1 | THE BROPHY FAMILY TRUST | AMBIGUOUS | urn:abn:40351214606 | urn:abn:87797459300 The Trustee for The Brophy Family Trust |
| S5b3bfb8bd7 | gleif_l1 | Vali Aftabigilvan | PARTY_TYPE_CONFLICT | urn:abn:72623363291 | urn:abn:72623363291 VALI AFTABIGILVAN |
| Sb31125f61a | gleif_l1 | Flourish Counselling CQ | PARTY_TYPE_CONFLICT | urn:abn:40128382931 | urn:abn:40128382931 PATRICA ANN FARRINGTON-LAWS |
| S65fbd332a9 | gleif_l1 | Konsol, Bichara | PARTY_TYPE_CONFLICT | urn:abn:84461938326 | urn:abn:84461938326 BICHARA KONSOL |


**UNSURE (excluded): 12.** The decision is shown so a human can settle them.

| sample_id | source | reference | decision | outcome | target | why unsure |
|---|---|---|---|---|---|---|
| Sd4ca6b45f5 | gleif_l1 | China Construction Bank Corporation | link | NAME_NORMALISED_EXACT | urn:abn:24125167553 China Construction Bank Corporation | GLEIF record is the New Zealand BRANCH of China Construction Bank Corporation (Chinese bank). The graph party 'China Construction Bank Corporation' (ABN 24125167553, foreign company ARBN 125167553) is the same legal person's Australian registration. A branch is not a separate legal person but has its own LEI; whether to link a foreign branch to the AU-registered head entity is a policy decision. |
| Sa7bcb6093c | gleif_l1 | SMEC International Pty Limited | link | NAME_NORMALISED_EXACT | urn:abn:32065440619 SMEC INTERNATIONAL PTY. LIMITED | GLEIF record is an international BRANCH (Indian registry RA000394 F06919, Gurgaon) of SMEC International Pty Limited; the head entity SMEC INTERNATIONAL PTY. LIMITED (ACN 065440619) is in the graph. A branch is not a separate legal person, but GLEIF models it as its own LEI with an IS_INTERNATIONAL_BRANCH_OF edge. Whether it should link to the head company is a policy decision for a human. |
| Sa9bfcee9a2 | gleif_l1 | THE HART SUPERANNUATION FUND | link | NAME_FUZZY | urn:abn:51996950901 HART SUPERANNUATION FUND | AMENDED AFTER JOIN (original blind label NOT_IN_GRAPH). GLEIF 'THE HART SUPERANNUATION FUND', 5 Masthead Quay, postcode 4566 (Noosaville QLD) but region coded AU-NSW. The blind note said all graph Hart funds were WA; that was wrong: the candidate list also held HART SUPERANNUATION FUND, ABN 51996950901, Booral NSW 2425, stated by another LEI (25490012J71UB7JQBW08). A NSW region on a QLD address hints the fund moved from NSW, so the two LEIs may be one SMSF; equally a common name. Cannot decide: UNSURE. |
| Sbdadceffa8 | gleif_l1 | Shane Thomas McEwan & Dianne McEwan ATF Lifestyle Superannuation Fund | link | NAME_FUZZY | urn:abn:93667727032 LIFESTYLE SUPERANNUATION FUND | 'Shane Thomas McEwan & Dianne McEwan ATF Lifestyle Superannuation Fund', c/o United Global Capital, Level 7 Melbourne. The VIC 'LIFESTYLE SUPERANNUATION FUND' (ABN 93667727032, 3013) is in the graph because another LEI (984500C594FDBD6D8939, Level 7 North Tower 459 Collins St) states it. Same adviser address and name, but many clients' SMSFs share an adviser address and the name is generic; trustees not visible for the ABN. Cannot decide. |
| Sd654d50c27 | gleif_l1 | GENETIC TECHNOLOGIES LIMITED | link | NAME_NORMALISED_EXACT | urn:abn:17009212328 GENETIC TECHNOLOGIES LIMITED | GENETIC TECHNOLOGIES LIMITED on the NZ register (NZBN 9429000018333, Remuera). Could be the ASX-listed Australian company (ACN 009212328) registered in NZ as an overseas company, or an unrelated NZ company of the same name. Cannot tell. |
| S523009f69e | gleif_l1 | 43 DEGREES SOUTH PTY LIMITED | link | NAME_FUZZY | urn:abn:79613231664 43 DEGREES SOUTH PTY LTD | AMENDED DURING CENSUS (original blind label NONE). '43 DEGREES SOUTH PTY LIMITED' on the NZ register (8491629, Methven NZ). The census showed 'Pty' companies on the NZ register are often Australian companies registered in NZ as overseas companies (Siegel, Revolut Payments NZ), so this may be the Tasmanian 43 DEGREES SOUTH PTY LTD (ACN 613231664) registered in NZ. Cannot confirm either way: UNSURE. |
| Se6684695e2 | gleif_l1 | Jacqueline Kim Stein ATF Stein Family Trust | abstain | AMBIGUOUS | urn:abn:38245244171 The Trustee for The Stein Family Trust | 'Jacqueline Kim Stein ATF Stein Family Trust', Perth WA 6026, no number. Graph has three 'Stein Family Trust' trusts (6027, 6065, 6163) plus 'J Stein Family Trust' (6210); 6027 is adjacent to 6026 but nothing confirms the trustee. Cannot decide. |
| Se095d115bc | gleif_l1 | ELGAS LIMITED | link | NAME_NORMALISED_EXACT | urn:abn:85002749260 ELGAS LIMITED | ELGAS LIMITED on the NZ register (NZBN 9429032428322, Penrose Auckland) with HQ North Ryde NSW, the address of the Australian ELGAS LIMITED (ACN 002749260). Possibly the Australian company's NZ overseas registration, possibly a separate NZ company. Cannot tell. |
| S0eea39a327 | gleif_l1 | PRIMELINE PTY LTD ATF DONALD FAMILY TRUST | link | NAME_FUZZY | urn:abn:29029528159 The trustee for DONALD FAMILY TRUST | GLEIF 'PRIMELINE PTY LTD ATF DONALD FAMILY TRUST', Beaumaris VIC 3193, no registration number, LEI lapsed. The only VIC 'DONALD FAMILY TRUST' in the graph (ABN 29029528159, VIC 3187) is in the graph because a different LEI (984500C9B89PQ0F4FD58, 'The trustee for DONALD FAMILY TRUST', Brighton VIC 3186, created 2001) names it. Different LEIs, different street addresses, trustee not stated for the ABN; 'Donald Family Trust' is a common name. Cannot confirm; leaning different. |
| Sbc8714c9b7 | gleif_l1 | ATTACH2 PTY LIMITED | link | NAME_NORMALISED_EXACT | urn:abn:98634198691 ATTACH2 PTY LTD | 'ATTACH2 PTY LIMITED' on the NZ register (6254636, c/o PwC Wellington). 'Pty' suggests an Australian company registered in NZ as an overseas company, i.e. ATTACH2 PTY LTD (ACN 634198691, QLD), but the NZ number may predate the 2019 ACN. Cannot confirm. |
| Se9aea98759 | gleif_l1 | HEIDELBERG GRAPHIC EQUIPMENT LIMITED | link | NAME_NORMALISED_EXACT | urn:abn:19004395779 HEIDELBERG GRAPHIC EQUIPMENT LIMITED | HEIDELBERG GRAPHIC EQUIPMENT LIMITED on the NZ register (Auckland). Possibly the Australian company (ACN 004395779) registered in NZ as an overseas company, possibly a separate NZ subsidiary of the same name. Cannot tell. |
| Sb4743f3f9e | asic_credit | BLUE AEGIS PTY LTD | link | EXACT_ABN | urn:abn:68694439024 ROYGO FINANCE PTY LTD | Credit register prints ABN 68694439024 for BLUE AEGIS PTY LTD (licence 2026-10-07) but ASIC and ABR both name that ACN/ABN 'ROYGO FINANCE PTY LTD' (registered 2026-01-16, no former names). Either a rename not yet in the snapshots or a wrong number on the register; cannot tell from the data. |


## 4. Blocking recall, own check on labelled records

Of 135 labelled records whose true party is in the graph, the true party was among the stored candidates of `m-1465a4ba-e5444596` for 135 (100.0%). 

Identifier-stripped run `m-1465a4ba-7bdb4123`: true party among stored candidates for 50 of 50 labelled in-graph records (100.0%).


## 5. Name path without identifiers, and the threshold sweep

AFSL and credit records re-matched with every identifier stripped. Truth is the ABN (else ACN) the register itself prints on the record, looked up in the canonical identifier table: independent of the matcher's decisions. `blocking recall` = the true party is among the run's stored candidates. Recall here is over records that have identifier truth.

| version | source | threshold | truth records | links | correct | wrong | precision | recall | blocking recall | abstentions |
|---|---|---|---|---|---|---|---|---|---|---|
| mr-1465a4ba-d4d0b99c | asic_afsl | 0.85 | 6519 | 6355 | 6355 | 0 | 100.0% | 97.5% | 99.95% | AMBIGUOUS 29, BELOW_THRESHOLD 134, NO_CANDIDATE 1 |
| m-1465a4ba-7bdb4123 | asic_afsl | 0.9 | 6519 | 6081 | 6081 | 0 | 100.0% | 93.3% | 99.95% | AMBIGUOUS 28, BELOW_THRESHOLD 409, NO_CANDIDATE 1 |
| mr-1465a4ba-b680dd47 | asic_afsl | 0.9 | 6519 | 6081 | 6081 | 0 | 100.0% | 93.3% | 99.95% | AMBIGUOUS 28, BELOW_THRESHOLD 409, NO_CANDIDATE 1 |
| mr-1465a4ba-ac8b048f | asic_afsl | 0.95 | 6519 | 6081 | 6081 | 0 | 100.0% | 93.3% | 99.95% | AMBIGUOUS 28, BELOW_THRESHOLD 409, NO_CANDIDATE 1 |
| mr-1465a4ba-d4d0b99c | asic_credit | 0.85 | 4233 | 3804 | 3804 | 0 | 100.0% | 89.9% | 99.81% | AMBIGUOUS 18, BELOW_THRESHOLD 408, PARTY_TYPE_CONFLICT 3 |
| m-1465a4ba-7bdb4123 | asic_credit | 0.9 | 4233 | 3704 | 3704 | 0 | 100.0% | 87.5% | 99.81% | AMBIGUOUS 18, BELOW_THRESHOLD 511 |
| mr-1465a4ba-b680dd47 | asic_credit | 0.9 | 4233 | 3704 | 3704 | 0 | 100.0% | 87.5% | 99.81% | AMBIGUOUS 18, BELOW_THRESHOLD 511 |
| mr-1465a4ba-ac8b048f | asic_credit | 0.95 | 4233 | 3704 | 3704 | 0 | 100.0% | 87.5% | 99.81% | AMBIGUOUS 18, BELOW_THRESHOLD 511 |


Labelled-sample view of `m-1465a4ba-7bdb4123` (the same labels, this version's decisions):

| source | decision | labelled | links | correct | wrong | precision (95% CI) | true target in graph | missed | recall (95% CI) | weighted P / R |
|---|---|---|---|---|---|---|---|---|---|---|
| asic_afsl | abstain | 10 | 0 | 0 | 0 | n/a (n/a) | 5 | 5 | 0.0% (0.0 to 43.4) | n/a / 0.0% |
| asic_afsl | link | 20 | 20 | 20 | 0 | 100.0% (83.9 to 100.0) | 20 | 0 | 100.0% (83.9 to 100.0) | 100.0% / 100.0% |
| asic_credit | abstain | 9 | 0 | 0 | 0 | n/a (n/a) | 6 | 6 | 0.0% (0.0 to 39.0) | n/a / 0.0% |
| asic_credit | link | 19 | 19 | 19 | 0 | 100.0% (83.2 to 100.0) | 19 | 0 | 100.0% (83.2 to 100.0) | 100.0% / 100.0% |


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

