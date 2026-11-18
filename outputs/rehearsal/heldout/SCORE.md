- rows: 200, order matches the input: True, rows with an error: 0
- precision of resolved: 152/152 (100.0%)
- recall over in-graph references: 152/188 (80.9%)
- correct abstention on NOT_IN_GRAPH: 12/12 (100.0%); of those with an empty candidate list: 12/12 (100.0%)
- wrong links: 0
- latency per reference (ms, measured): p50 281.7, p95 367.3, max 754.4

| category | n | resolved | correct | wrong | in-graph abstained | absent abstained (empty list) |
|---|---|---|---|---|---|---|
| abr_company | 45 | 38 | 38 | 0 | 7 |  |
| abr_trading_name | 10 | 8 | 8 | 0 | 2 |  |
| abr_trust | 18 | 14 | 14 | 0 | 4 |  |
| absent_invented | 3 | 0 | 0 | 0 | 0 | 3/3 (3) |
| absent_nz_namesake | 3 | 0 | 0 | 0 | 0 | 3/3 (3) |
| absent_out_of_slice | 6 | 0 | 0 | 0 | 0 | 6/6 (6) |
| accc_recipient | 5 | 5 | 5 | 0 | 0 |  |
| afsl_licensee | 28 | 23 | 23 | 0 | 5 |  |
| banned_org | 10 | 8 | 8 | 0 | 2 |  |
| credit_licensee | 22 | 17 | 17 | 0 | 5 |  |
| gleif_au | 28 | 22 | 22 | 0 | 6 |  |
| hard_negative_in_graph | 8 | 7 | 7 | 0 | 1 |  |
| national_company | 14 | 10 | 10 | 0 | 4 |  |

### Wrong links

None.

### In-graph references abstained on

| id | category | reference | reason | expected is candidate 1 | expected in list |
|---|---|---|---|---|---|
| R004 | national_company | CBA | BELOW_THRESHOLD | False | False |
| R007 | abr_trading_name | ootrend developments | BELOW_THRESHOLD | False | False |
| R009 | credit_licensee | LEEDGE HOME LOANS PROPRIETARY LIMITED | BELOW_THRESHOLD | False | False |
| R014 | banned_org | Moanrch Fx Group Pty Ltd | BELOW_THRESHOLD | False | False |
| R018 | afsl_licensee | BERYLLIUM ADVSSERS Proprietary Limited, Brisbane QLD | BELOW_THRESHOLD | False | False |
| R019 | gleif_au | PICKUP HULDINGS | BELOW_THRESHOLD | False | False |
| R025 | hard_negative_in_graph | Commonwealth Super Corp, Canberra ACT | BELOW_THRESHOLD | False | False |
| R032 | abr_company | Desborough, Perth WA 6076, ABN 75 602 301 495 | PARTY_TYPE_CONFLICT | True | True |
| R062 | abr_company | FRONTIER LEATHER PTY LTD - Western Australia | BELOW_THRESHOLD | False | False |
| R064 | credit_licensee | australia finance capital pty ltd | BELOW_THRESHOLD | False | False |
| R067 | afsl_licensee | BENNETTO FINANCE PTY LTD - Tasmania | BELOW_THRESHOLD | False | False |
| R072 | abr_trading_name | B Leegal Lawyers | BELOW_THRESHOLD | False | False |
| R078 | national_company | comonwealth bank | BELOW_THRESHOLD | False | False |
| R086 | gleif_au | KONZAG GRAIES PTY LTD, 26 LEWIS STREET, Adelaide SA 5606 | BELOW_THRESHOLD | False | False |
| R093 | banned_org | GLOBAL FINANCE GROUP Pty | BELOW_THRESHOLD | False | False |
| R097 | gleif_au | THORNEEY TECHNOLOGIES - Victoria | BELOW_THRESHOLD | False | False |
| R098 | afsl_licensee | WEALTHSTREAM FINANCIAL GROIP PTY LTD | BELOW_THRESHOLD | False | False |
| R101 | gleif_au | FINNDEX GROUP Ltd, (ACN 128588764) | NO_CANDIDATE | False | False |
| R102 | abr_trust | The Trustee For The Niimmervoll & Hardman Investment Trust | BELOW_THRESHOLD | False | False |
| R104 | credit_licensee | trustee for stringer kings meadow trust and the trustee for the viney kigs meadwo trust (TAS) | BELOW_THRESHOLD | False | False |
| R105 | credit_licensee | chandra, yunita | BELOW_THRESHOLD | False | False |
| R110 | national_company | ANZ Banking Group Limited | BELOW_THRESHOLD | False | False |
| R111 | credit_licensee | dash, jason richard ABN 91465907143 | BELOW_THRESHOLD | False | False |
| R120 | abr_trust | atf machar triding trust, WA | BELOW_THRESHOLD | False | False |
| R123 | national_company | National Australia Bank Ltd (NAB) | BELOW_THRESHOLD | False | False |
| R137 | afsl_licensee | INESTA CUSTODIAN (1) PTY LTD | BELOW_THRESHOLD | False | False |
| R140 | abr_trust | Falcucic Family Trust | NO_CANDIDATE | False | False |
| R145 | abr_company | WESTO FOOD PTY LTD | BELOW_THRESHOLD | False | False |
| R153 | abr_company | PIKEAIR Pty - Western Australia | BELOW_THRESHOLD | False | False |
| R163 | abr_trust | ATF Iso Tech Poperty Trust | BELOW_THRESHOLD | False | False |
| R164 | abr_company | NEandCO KITCHENS P/L | BELOW_THRESHOLD | False | False |
| R168 | abr_company | BalePark Investments Pty Ltd | NO_CANDIDATE | False | False |
| R175 | afsl_licensee | Salter, Geoffrey Gordon | BELOW_THRESHOLD | False | False |
| R177 | abr_company | BLACK RIDGE FABRICATION PTY LTD - Western Australia | BELOW_THRESHOLD | False | False |
| R190 | gleif_au | deutsche securities austtalia limited | BELOW_THRESHOLD | False | False |
| R199 | gleif_au | FRESDA PTY. LIMITED, C/- GUILLAN EVANS & CO, Sydney NSW 2232 | BELOW_THRESHOLD | False | False |
