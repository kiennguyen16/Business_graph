# Identifier coverage, Tier 2 sources

Measured 2026-11-16 by running each adapter's `parse` + `to_record`
(`src/bizgraph/sources/adapters/tier2.py`) over the real files in `data/raw/`. Revised after an
independent audit (`tests/independent/test_tier2_contract.py`, `audit_tier2.py`) showed identifiers
being trusted when they belonged to a different party; the counts below are after those fixes.

An identifier is counted only if the adapter **emits** it, which means two things: it passes its
check (ABN mod 89, ACN / ARBN / ARSN mod 10, LEI ISO 7064 mod 97-10, NZBN GS1 mod 10; AFSL, ACL,
liquidator and NZ company numbers are format-checked only) **and** the adapter is satisfied the
number is this entity's own (see "Identifiers we refuse to trust"). Percentages are of accepted
records.

| Source (snapshot file) | Rows | Rejected | ABN | ACN (any) | ACN stated by source | ABN or ACN | ARBN | LEI | Other keys | No business key | Person | Org | Unknown |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `asic_afsl` (afs_lic_202611.csv) | 6,551 | 0 | 6,351 (96.9%) | 6,374 (97.3%) | 170 (2.6%) | 6,521 (99.5%) | 28 (0.4%) | 0 | AFSL 6,551 (100%) | 2 (0.0%) | 52 | 6,499 | 0 |
| `asic_credit` (credit_lic_202611.csv) | 4,308 | 0 | 3,846 (89.3%) | 3,875 (89.9%) | 388 (9.0%) | 4,234 (98.3%) | 0 | 0 | ACL 4,308 (100%); AFSL 310 (7.2%) | 74 (1.7%) | 368 | 3,940 | 0 |
| `asic_banned_org` (bd_org_202611.csv) | 15 | 0 | 0 | 15 (100%) | 15 (100%) | 15 (100%) | 0 | 0 | none | 0 | 0 | 15 | 0 |
| `asic_liquidator` (liquidator_202611.csv) | 660 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | LIQUIDATOR_NO 660 (100%) | 660 (100%) | 660 | 0 | 0 |
| `gleif_l1`, AU entities | 54,082 | 0 | 14,163 (26.2%) | 34,132 (63.1%) | 34,132 (63.1%) | 48,295 (89.3%) | 26 | 54,082 (100%) | ARSN 2,585 (4.8%) | 0 | 200 | 53,870 | 12 |
| `gleif_l1`, NZ entities | 4,281 | 0 | 0 | 0 | 0 | 0 | 0 | 4,281 (100%) | NZBN 1,026 (24.0%); NZ company no. 1,319 (30.8%) | 0 | 0 | 4,279 | 2 |
| `gleif_l1`, out-of-region counterparties | 1,243 | 0 | 0 | 0 | 0 | 0 | 0 | 1,243 (100%) | none | 0 | 0 | 1,243 | 0 |
| `gleif_l2` (AU/NZ filtered RR) | 8,065 | 129 | n/a | n/a | n/a | n/a | n/a | both ends valid on 7,936 (100% of accepted) | n/a | n/a | n/a | n/a | 7,936 (edges) |

"ABN or ACN" is the number the brief asks for: the share of records the exact path can attach to the
Tier 1 backbone without any name matching. "No business key" means no ABN, ACN, ARBN, ARSN, LEI,
NZBN or NZ company number (licence and liquidator numbers do not join to Tier 1).

## Before and after the audit fixes

| Change | Before | After |
|---|---|---|
| GLEIF RA000014 (ASIC company register) numbers emitted as ACN | 34,387 | 34,132. The other 255: 141 ARSN (pooled fund / ETF / scheme), 57 payload `trustee_acn`, 23 payload `trust_registration_number` (trust, unclear whether trustee ACN or ARSN), 26 ARBN (foreign body), 8 payload `unverified_acn` |
| GLEIF RA001192 (ASIC scheme register) numbers | 2,476 payload only | 2,444 `IdScheme.ARSN`; 24 company-named entities (listed investment companies, CCIVs) to payload `unverified_acn`; 8 fail checksum |
| ANNULLED LEIs emitting ABN/ACN | 5 | 0 (number kept as payload `withheld_registration_number`) |
| Credit trust names with a 9-digit "ACN" | 5 emitted as ACN | 0; payload `unverified_acn` |
| AFSL ACNs derived from ABN | 6,231 | 6,204 |
| AFSL ACNs stated by source | 199 | 170 ACN + 28 ARBN + 1 unverified |
| Credit ACNs derived from ABN / stated | 3,487 / 393 | 3,487 / 388 |
| ARBN identifiers | 0 | AFSL 28, GLEIF 26 |
| AFSL / credit / GLEIF "ABN or ACN" | 100.0% / 98.4% / 89.8% (AU) | 99.5% / 98.3% / 89.3% (AU) |
| Liquidator numbers | payload only | `IdScheme.LIQUIDATOR_NO` on 660 |
| NZ numbers | payload only | `NZBN` 1,033 (all pass the GS1 check), `NZ_COMPANY_NO` 1,327 |
| GLEIF SOLE_PROPRIETOR typing | 212 PERSON | 200 PERSON ('LAST, GIVEN' shape), 14 UNKNOWN ('Mega Clicks', bare 'GIVEN LAST'), 15 ORGANISATION |
| GLEIF `lei_status` | absent | on all 59,606 (ISSUED 31,765, LAPSED 23,748, RETIRED 3,948, DUPLICATE 130, ANNULLED 9, other 6) |
| GLEIF L2 `child_lei` / `parent_lei` | on all 7,936 edges | on the 4,420 consolidation edges only; the 3,516 IS_FUND-MANAGED_BY / IS_SUBFUND_OF / IS_INTERNATIONAL_BRANCH_OF / IS_FEEDER_TO edges carry `start_lei` / `end_lei` only |

Checked against the ASIC company register (`company_202611.zip`):
* AFSL ACNs: 5,476 Pty, 882 public, 16 foreign. Those 16 are foreign companies whose names show no
  foreign form, so they really should be ARBNs; the number still matches the right register entry.
* AFSL ARBNs: 14 are foreign companies in the register, and 14 are International licensees with
  no register entry.
* Credit ACNs: 3,717 Pty, 154 public, 3 foreign, 1 not in the register.

## Identifiers we refuse to trust, and why

| Pattern | Example from the data | Why the number is not this entity's | What we do |
|---|---|---|---|
| Trustee marker in the name (`ATF`, `AS TRUSTEE FOR`, `TRUSTEES OF`, `THE TRUSTEE FOR`) | credit 385338 'TRUSTEES OF HELYER FAMILY TRUST', 142952672 | A trust has no ACN; a 9-digit number in the row is the trustee company's, and an ABN tail is the trust's ABN, not an ACN | ABN kept; no ACN; 9 digits to `unverified_acn`, reason `trustee_marker` |
| Name ends in TRUST / FUND / SCHEME / ETF | 'The Trustee for Austral 151 Trust' (GLEIF, RA000014 620721726 = ARCSIDE PTY LTD) | GLEIF stores the trustee's ACN, or the scheme's ARSN, under the company register | personal trusts (FAMILY, SUPER, trustee marker, or company name) to payload `trustee_acn`; pooled vehicles (ELF ADXG, FUND / ETF / SCHEME / EQUITY / INCOME words) to `IdScheme.ARSN`; anything else `trust_registration_number` |
| GLEIF legal form 7TPC (Trust) or ADXG (Fund) | 'GOODMAN AUSTRALIA INDUSTRIAL TRUST NO. 2' | same as above; verified against the GLEIF ELF code list v1.6 (CC0) | same as above |
| Two legal-form names joined by `&` / `AND` | 'COLLINS PARTNERS ADVISORY PTY LTD & CRADOC NOMINEES PTY LTD' | the ABN belongs to the partnership or joint venture, so its tail is nobody's ACN | no ACN derived, reason `multi_party_name` |
| Foreign body (foreign legal form without PTY, foreign ELF code or jurisdiction, or an "International" address) | AFSL 526358 'RUFFER LLP', 642497630 | ASIC numbers a registered foreign body with an ARBN, which never appears as an ACN in the ABR | stated 9 digits become `IdScheme.ARBN`; an ABN tail is not derived at all (payload `unverified_arbn`) |
| No Australian company legal form | 'WESTPAC BANKING CORPORATION', 'BNP PARIBAS' | an ABN tail passes the ACN check by chance about 1 time in 10 for non-companies | no ACN derived, reason `no_company_legal_form` (the ABN still gives the exact join) |
| Company-named entity on ASIC's scheme register (RA001192) | 'WAM Capital Limited', 'R & L CAPITAL CCIV' | listed investment companies and CCIVs carry their company ACN on that register; it is neither a scheme's ARSN nor a trusted ACN | payload `unverified_acn` |
| ANNULLED LEI | 'The Trustee for RIJA TRUST' | the LEI was issued in error; nothing in it is trusted | LEI only; number in `withheld_registration_number` |
| NZ company number that passes the ACN check | '8819458' | an NZ number, issued by a different register | `IdScheme.NZ_COMPANY_NO`, never ACN |
| ORIC Indigenous Corporation Number | 83 LEIs | not an ACN, and there is no IdScheme for it | payload `oric_icn` |

DUPLICATE LEIs (130) keep their identifiers: the entity is real, it simply has another LEI too.
`lei_status` is in every payload, so resolution can skip the identifier-conflict check for them.

## Known recall gap

Every guard above trades recall for precision, which is the brief's stated preference. The cost:
* 24 AFSL and 5 credit records with a valid ABN do not get an ABN-derived ACN because the name has
  no "Ltd" (statutory names such as WESTPAC BANKING CORPORATION and COMMONWEALTH BANK OF AUSTRALIA).
  The ABN still joins them exactly.
* 43 AFSL and 1 credit foreign-body ABN tails are not used (payload `unverified_arbn`). Again, the
  ABN still gives the exact join.
* 23 GLEIF trusts on RA000014 hold a number that is either the trustee's ACN or the scheme's
  ARSN (`trust_registration_number`). Settling it needs a lookup against the ASIC register, which
  the adapter does not do.
* The audit also found records whose identifier the source simply did not supply (for example GLEIF
  entities with RA999999). That is the safe direction and is left to the name path.

## Per-source notes

**ASIC AFS licensee.** The register lists current licences only: there is no end date and no
cancelled status, so a cancellation is only visible as a licence disappearing between weekly
snapshots. People appear as "GIVEN LAST" (changed August 2026, per the help file): 52 people and 4
partnerships of individuals (typed organisation). 44 licensees have an "International" address,
which counts towards the foreign-body test.

**ASIC credit licensee.** People appear as "LAST, GIVEN" (368). The person reading of a "LAST, GIVEN"
name is checked before organisation words, so 'CHURCH, JOHN' and 'KIM, SE JIN' are people. No real
row was affected; the change only covers names like these. 310 licensees also carry an AFSL number, emitted as a second
identifier, which gives an exact AFSL-to-ACL join. 47 ACNs had lost their leading zeros (7 and 8
digits); all pass the checksum after zero-padding (`source_zero_padded`). All 69 records with `0`
are individuals.

**ASIC banned and disqualified organisations.** 15 rows, each with a checksum-valid ACN and a Pty Ltd
name; no row is a person or a trust. The adapter applies the same guards (a trust or foreign name
would get no ACN) because a wrong link here publishes an accusation. The record_id keys on the
checksum-valid number even when it is not trusted, so ids stay stable if guard rules change.

**ASIC liquidator.** 660 natural persons; the registered liquidator number is now
`IdScheme.LIQUIDATOR_NO`. No ABN, ACN or LEI. 500 name a firm (`LIQ_FIRM`, name-only).

**GLEIF Level 1.** Slice: legal address, headquarters address or legal jurisdiction in AU or NZ
(58,363 of 3,494,799 golden copy records), plus 1,243 out-of-region LEIs referenced by kept
relationships.

| Registration authority | Meaning | Emitted |
|---|---|---|
| RA000014 | ASIC Register of Companies | ACN 34,132; ARSN 141; ARBN 26; payload: trustee_acn 57, trust_registration_number 23, unverified_acn 8; 35 fail checksum |
| RA000013 | Australian Business Register | ABN 14,038; 31 fail checksum; 5 withheld (ANNULLED) |
| RA000762 / RA000714 | ATO Super Fund Lookup / APRA RSE | ABN 102 / 23 |
| RA001192 | ASIC Register of Australian Registered Schemes | ARSN 2,444; unverified_acn 24; 8 fail checksum |
| RA000466 | NZ Companies Office | NZBN 1,033; NZ company number 1,327 |
| RA000016 | ORIC | payload `oric_icn` 83 |
| RA999999 / RA888888 / foreign registers | none / not applicable / abroad | nothing |

**GLEIF Level 2.** 8,065 relationship records touch an AU/NZ entity; 129 are rejected as
`self_relationship` (funds listed as managed by themselves). Accepted, by type:
IS_FUND-MANAGED_BY 3,241; IS_ULTIMATELY_CONSOLIDATED_BY 2,362; IS_DIRECTLY_CONSOLIDATED_BY 2,058;
IS_SUBFUND_OF 229; IS_INTERNATIONAL_BRANCH_OF 39; IS_FEEDER_TO 7. Only the 4,420 consolidation edges
carry `child_lei` / `parent_lei`. 1,816 AU/NZ entities have a direct accounting-consolidation parent.
