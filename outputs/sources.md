# Source licence review

Reviewed 2026-11-16. Every source named in the brief, plus Wikidata. Quotes are copied from the
official page or the official dataset metadata on that date. This is an engineering reading of the
published terms, not legal advice.

## Summary

| Source | Tier | Licence as published | Commercial use | Used here |
|---|---|---|---|---|
| ABR bulk extract | 1 | CC BY 3.0 AU | Yes, with attribution | Yes |
| ASIC company register | 1 | CC BY 3.0 AU | Yes, with attribution | Yes |
| ASIC AFS licensee | 2 | CC BY 3.0 AU | Yes, with attribution | Yes (`asic_afsl`) |
| ASIC credit licensee | 2 | CC BY 3.0 AU | Yes, with attribution | Yes (`asic_credit`) |
| ASIC banned and disqualified organisations | 2 | CC BY 3.0 AU | Yes, with attribution | Yes (`asic_banned_org`) |
| ASIC liquidator | 2 | CC BY 3.0 AU | Yes, with attribution | Yes (`asic_liquidator`) |
| GLEIF golden copy L1 + L2 | 2 | CC0 1.0 | Yes | Yes (`gleif_l1`, `gleif_l2`) |
| ACCC infringement notices register | 3 | CC BY 4.0 (site-wide) | Yes, with attribution (third-party content excluded) | Not in this scope |
| TGA ARTG | 3 | All rights reserved, personal / internal use only | **No** (without written permission) | Not in this scope |
| annualreports.com | 3 | No licence granted; site terms are a disclaimer only | **Unclear, treat as no** | Not in this scope |
| Wikidata | any | CC0 (structured data) | Yes | Not in this scope |

Answer to WRITEUP question 7 in one line: **TGA ARTG** cannot go into a commercial product without
TGA's written permission, and **annualreports.com** grants no reuse licence at all (the annual reports
themselves are each company's copyright), so neither should ship in a commercial product as-is.

## Method

1. data.gov.au datasets: read the CKAN metadata through the official API
   (`https://data.gov.au/data/api/3/action/package_show?id=<dataset>`, fields `license_id`,
   `license_title`, `license_url`) and cross-checked the dataset page, which shows the licence on
   every resource (CSV, TSV, XLSX, help PDF).
2. Other sites: fetched the site's own copyright / terms / legal page and its `robots.txt`, and
   quoted the operative sentence.
3. Verdict rule: CC0 = yes; CC BY = yes with attribution; "personal or internal use" or "no
   commercial purposes" = no; no licence stated = unclear, treated as no for a product.

## ASIC and ABR datasets (data.gov.au)

All five ASIC datasets and the ABR extract return the same CKAN licence:

> `license_id: cc-by`, `license_title: Creative Commons Attribution 3.0 Australia`,
> `license_url: http://creativecommons.org/licenses/by/3.0/au/`

The dataset pages show "Licence Creative Commons Attribution 3.0 Australia" on every resource.
Attribution: "Source: ASIC" / "Source: Australian Business Register", with a link to the licence.

| Source | Dataset URL | Publisher (CKAN organisation) | File used |
|---|---|---|---|
| ABR bulk extract | https://data.gov.au/data/dataset/abn-bulk-extract (tool page: https://abr.business.gov.au/Tools/BulkExtract) | Australian Business Register | `public_split_1_10.zip`, `public_split_11_20.zip` |
| ASIC company register | https://data.gov.au/data/dataset/asic-companies | ASIC | `company_202611.zip` |
| ASIC AFS licensee | https://data.gov.au/data/dataset/asic-afs-licensee | ASIC | `afs_lic_202611.csv` |
| ASIC credit licensee | https://data.gov.au/data/dataset/asic-credit-licensee | ASIC | `credit_lic_202611.csv` |
| ASIC banned and disqualified organisations | https://data.gov.au/data/dataset/asic-banned-disqualified-org | ASIC | `bd_org_202611.csv` |
| ASIC liquidator | https://data.gov.au/data/dataset/asic-liquidator | ASIC | `liquidator_202611.csv` |

Notes:
* The ABR tool page (`abr.business.gov.au/Tools/BulkExtract`) is rendered client-side and carried no
  readable licence text when fetched; the data.gov.au record for the same extract is the licence of
  record.
* CC BY 3.0 AU permits commercial use. The obligations are attribution, a link to the licence, and
  not implying endorsement. The registers contain personal information about individuals
  (licensees who are sole traders, liquidators); the licence does not remove Privacy Act obligations
  for a product that republishes it.

## GLEIF golden copy (Level 1 and Level 2)

* URL: https://www.gleif.org/en/lei-data/gleif-golden-copy (files via
  `https://goldencopy.gleif.org/api/v2/golden-copies/publishes/latest`)
* Terms page: https://www.gleif.org/en/meta/lei-data-terms-of-use
* Quote: "The data available through the Access Service are provided under the CC0 licence, see
  CC0 1.0 Universal (CC0 1.0)."
* Verdict: **yes**. CC0 confirmed. No attribution required (good practice: cite GLEIF). The same
  page reserves GLEIF's right to suspend or modify the access service if use undermines the GLEIS
  principles; that limits access, not the licence of data already obtained.

## ACCC infringement notices register

* URL: https://www.accc.gov.au/public-registers/infringement-notices-register
* Terms page: https://www.accc.gov.au/copyright (the footer "Disclaimer and copyright" link)
* Quote: "All material presented on this website is provided under a Creative Commons Attribution
  4.0 International licence (or CC BY 4.0 licence), except for: the Commonwealth Coat of Arms ...
  all logos used by the ACCC ... content supplied by third parties [and] material where it is
  expressly stated otherwise."
* Attribution required: "Source: ACCC (c) Commonwealth of Australia".
* The register page itself carries no contrary statement. `robots.txt` (fetched) does not disallow
  `/public-registers/`, but does disallow faceted listing URLs (`/*?f[*`, `/*&f[*`) and `/search`,
  so a collector should page through the plain listing rather than filter facets.
* Verdict: **yes, with attribution**. Register entries are ACCC-authored summaries, so CC BY 4.0
  applies. Linked third-party documents (for example a company's own undertakings) would be
  excluded. Polite, rate-limited collection of the register pages is consistent with the terms.

## TGA Australian Register of Therapeutic Goods

* URL: https://www.tga.gov.au/resources/artg
* Terms page: https://www.tga.gov.au/copyright ("Last updated 10 September 2025")
* Quotes: "you can download, display, print and reproduce the whole or part of this content in an
  unaltered form for: your own personal use [or] internal use within your organisation." and
  "You must not use the whole or any part of the content on this website for any commercial
  purposes." and, under "Commercial and other use": "You are not permitted to re-transmit,
  distribute or commercialise the material without our prior written approval."
* Verdict: **no** for a commercial product without TGA's written permission. Use in this take-home
  is internal evaluation, which the notice allows, but it must be flagged as a source that could not
  ship. No ARTG extract was found on data.gov.au under an open licence.

## annualreports.com

* URL: https://www.annualreports.com/Companies?exch=7
* Terms page: the site has no terms-of-use page; the footer "Legal" link goes to
  https://www.annualreports.com/Disclaimer, which contains only a content disclaimer, warranty
  disclaimer and limitation of liability. Quote: "AnnualReports.com solely provides investment
  information to its users and is not intended to provide investment advice." No licence is
  granted anywhere on the page. `/TermsOfUse` returns no terms.
* `robots.txt` disallows all crawling of `/HostedData/*.pdf` (the annual report PDFs) for every
  user agent, and blocks several AI crawlers (`GPTBot`, `ChatGPT-User`, `OAI-SearchBot`) entirely.
* The reports themselves are each listed company's copyright; annualreports.com is a re-host.
* Verdict: **unclear, treat as no**. No reuse licence; automated PDF download is disallowed by
  `robots.txt`. A small, manual sample for evaluation is the most this supports. For a product, the
  same reports should come from the issuer's own site or the ASX announcements platform under their
  own terms.

## Wikidata

* URL: https://query.wikidata.org/ ; licensing page https://www.wikidata.org/wiki/Wikidata:Licensing
* Quote: structured data in the main, Property, Lexeme and EntitySchema namespaces "is released into
  the public domain under Creative Commons Zero"; "Text in other namespaces is copyrighted and
  available under the Creative Commons Attribution-ShareAlike 4.0 License."
* Verdict: **yes**. CC0 confirmed for the statements we would query (aliases, websites, parent
  organisation). Wikimedia's query service has a usage policy (User-Agent, rate limits) that applies
  to access, not to reuse.

## ACCC fetch log

Collector rules: `robots.txt` first, only allowed paths (plain listing `?page=N` and entry pages under
`/public-registers/infringement-notices-register/`, never facet `?f[...]` URLs or `/search`), at least
2 s between requests, descriptive generic User-Agent (`bizgraph-research-bot/0.1 (non-commercial
evaluation; polite crawler)`), raw HTML cached under `data/raw/accc_notice/` (`listing/`, `notices/`).

| When (AEDT) | URL | Result |
|---|---|---|
| 2026-11-17 | https://www.accc.gov.au/robots.txt | 200, saved to `data/raw/accc_notice/robots.txt`. No `Crawl-delay`; `/public-registers/` allowed; `/*?f[*`, `/*&f[*`, `/search` disallowed (unchanged from the licence review above) |
| 2026-11-17 | https://www.accc.gov.au/public-registers/infringement-notices-register | **403 Access Denied** from the CDN (Akamai, reference in `data/raw/accc_notice/fetch_403_20261117.html.txt`) |

Outcome of the automated attempt: **nothing collected**. The register is allowed by `robots.txt`
and the content is CC BY 4.0, but the site's CDN refuses automated clients that identify themselves
honestly. Disguising the client as a browser to get past that block was not done: the block
expresses the operator's intent even though `robots.txt` does not. No further automated requests
were made.

### Sample obtained through the user's browser (2026-11-17)

| When (AEDT) | What | Result |
|---|---|---|
| 2026-11-17 | Register landing page and the 20 entry pages it links (the most recent notices), opened in the user's own browser session, about 3 s apart | 20 notices, saved as `data/raw/accc_notice/extract_20261117.txt` |

* Scope: landing-page notices only. The "View all" listing is built from facet URLs (`?f[0]=...`)
  that `robots.txt` disallows, so it was not opened; `/search` was not used.
* Format: raw HTML could not be transferred out of the browser session, so the page fields were
  recorded exactly as displayed, one notice per line (`slug|field=value|...`, Drupal field machine
  names `infringe-date-paid`, `infringe-number`, `infringe-section`, `name`, `acn`, `abn`,
  `reference-number`, plus the listing title `list_title`). The file header records this.
* Coverage: dates paid 16 June 2026 to 5 November 2026; 20 entries for 14 distinct recipients (one
  company can have several entries: Venue Smart 3, Dysck, HSK United, Marshall Freeman, Vacaciones
  eDreams 2 each). All recipients are organisations; none is multi-party. The 20 entries list 40 infringement notice numbers.
* Identifiers stated on the page: ACN only 13, ABN only 4, both 1 (WeFlex, ABN tail equals ACN),
  none 2 (Vacaciones eDreams, S.L., a Spanish company showing only a CIF in `reference-number`).
  All 19 stated numbers pass their checksum.
* No entry page states a penalty amount; the only date is the date the notice was paid.
* Licence: CC BY 4.0, attribution "Source: ACCC (c) Commonwealth of Australia". A copy is a test
  fixture (`tests/fixtures/tier3/accc_notice/extract_20261117.txt`).

The adapter also still parses cached HTML entry pages (`data/raw/accc_notice/notices/*.html`), so
pages saved later with the same rules can be added without code changes.

## ASIC licence history (AFSL and credit snapshots)

The AFS licensee file lists current licences only and the credit file lists approved / suspended
licences only, so cancellations have to be inferred by diffing snapshots
(`src/bizgraph/pipeline/licence_history.py`).

Where the history comes from: data.gov.au does **not** keep older files. CKAN `package_show` for
`asic-afs-licensee` and `asic-credit-licensee` lists only the current resource (one CSV, TSV, XLSX
each; the AFSL file is replaced weekly, see `package_activity_list`). The resource download URL
ignores its filename and always serves the current file (checked: `.../download/afs_lic_202610.csv`
returns the November file by ETag), and old package revisions (`activity_show`) need an editor
login. Older files were therefore taken from the **Internet Archive Wayback Machine** captures of
the same data.gov.au download URLs (`https://web.archive.org/web/<timestamp>id_/<url>`), which are
byte copies of the CC BY 3.0 AU files. Saved with the original dated filename plus the capture
date:

| File | Snapshot date used | Rows | sha256 (16) |
|---|---|---|---|
| `data/raw/asic_afsl/history/afs_lic_202504__wb20250414.csv` | 2025-04-14 | 6,469 | a5d0b89f0fc63dac |
| `data/raw/asic_afsl/history/afs_lic_202511__wb20251129.csv` | 2025-11-29 | 6,459 | 97d69eba3f146f42 |
| `data/raw/asic_afsl/history/afs_lic_202512__wb20251208.csv` | 2025-12-08 | 6,463 | e9a827bdfb9772f8 |
| `data/raw/asic_afsl/history/afs_lic_202602__wb20260224.csv` | 2026-02-24 | 6,486 | 8df4bc5422f82771 |
| `data/raw/asic_afsl/history/afs_lic_202610__wb20261102.csv` | 2026-11-02 | 6,541 | 64daf180ce2235e7 |
| `data/raw/asic_afsl/history/afs_lic_202611__wb20261110.csv` | 2026-11-10 | 6,548 | 6c23e63645a1479b |
| `data/raw/asic_afsl/afs_lic_202611.csv` (current, already present) | 2026-11-11 (CKAN last_modified) | 6,551 | |
| `data/raw/asic_credit/history/credit_lic_202510__wb20251021.csv` | 2025-10-21 | 4,469 | b61983d76d8fab14 |
| `data/raw/asic_credit/history/credit_lic_202511__wb20251129.csv` | 2025-11-29 | 4,478 | 8ec0c093f7e28794 |
| `data/raw/asic_credit/credit_lic_202611.csv` (current, already present) | 2026-11-15 (CKAN last_modified) | 4,308 | |

The snapshot date is the archive capture date (an upper bound for the file's publication date).
The `202510` credit capture was stored gzip-encoded and was decompressed after download.

Gaps that matter for "cancelled in the last 3 months": there is **no AFSL capture between
2026-02-24 and 2026-11-02**, and no credit capture between 2025-11-29 and 2026-11-15. A licence
that vanished in that window gets `event_date` 2026-11-02 (AFSL) or 2026-11-15 (credit), with
`observed_after` showing the true lower bound; only the 2026-11-02 to 2026-11-11 AFSL steps are
week-precise. From now on, loading every weekly file (ASIC publishes each Wednesday) closes this.
Wayback captures are irregular, so this history is opportunistic, not complete.
