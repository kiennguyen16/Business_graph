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
