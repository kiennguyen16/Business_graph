# Blind-test rehearsal for `resolve_results.jsonl`

**This set is mine.** The brief's `dirty_references.jsonl` (200 rows, 12 not
in the graph) was not supplied. To rehearse the blind run, an AI labeller that did not build the matcher
built a stand-in of the same shape from the raw registers, wrote the answer key separately, ran the
resolver once and scored it. Nothing in the matcher, its thresholds or its gates was changed after
seeing these results. The numbers below say how v3 behaves on *my* idea of a dirty reference; the
real file will differ.

## The set

`make_substitute.py` (seed 20261118, deterministic for a given database; two runs compared byte for
byte) writes `dirty_references_substitute.jsonl` (`reference_id`, `reference`) and `answer_key.jsonl`
(expected canonical key or `NOT_IN_GRAPH`, category, true name, source record, corruptions applied).
No link, candidate or abstention table was read to build it.

| category | n | truth taken from |
|---|---|---|
| afsl_licensee / credit_licensee | 28 / 22 | the licence record's own ABN, else ACN, joined to `identifier` (exactly one party) |
| gleif_au | 28 | the LEI record's stated ABN / ACN, AU legal address |
| banned_org / accc_recipient | 10 / 5 | stated ACN / ABN (only 5 distinct ACCC recipients have one that is in the graph) |
| national_company | 14 | hand list (CBA x3 incl. "CBA" and a typo, Westpac x2, Telstra x2, NAB, ANZ, BHP, Woolworths, Wesfarmers, Qantas, Rio Tinto), ABN checked |
| hard_negative_in_graph | 8 | near-names that are other parties: Commonwealth Superannuation Corporation (x2), CBA Officers Super, CBA Staff Golf Club WA, Westpac Tasmanian staff club, Telstra Energy (Markets), ANZ Securities, Wesfarmers Transport |
| abr_company / abr_trust / abr_trading_name | 45 / 18 / 10 | WA / TAS active ABR parties whose normalised name (or alias) belongs to one party only |
| absent (NOT_IN_GRAPH) | 12 | 6 ASIC-registered companies outside the slice (2 stating their real ABN), 3 NZ namesakes (Westpac New Zealand, ANZ Bank New Zealand, Woolworths New Zealand), 3 invented names; each checked absent by ABN, ACN and normalised name in `party_canonical`, `alias` and the name index |

Corruptions: case changes, legal form dropped or rewritten ("P/L", "Pty", "Pty. Ltd.", "Proprietary
Limited", "Ltd."), "&" / "and", one-word typos (52 rows), trustee wording ("ATF", "Trustee for",
bare trust name), trading names, appended state / city / postcode / street text (30 rows), an embedded
ABN or ACN in 41 rows (20.5%), 7 of them with a broken check digit, acronyms. 7 in-graph references
are sole traders or individuals (person parties).

## Results (matcher `m-94f4f6b2-d37e44c6`, `data/snap_v3_rehearsal.duckdb`, measured 2026-11-18)

- rows: 200, order matches the input: True, rows with an error: 0
- precision of resolved: 128/128 (100.0%)
- recall over in-graph references: 128/188 (68.1%)
- correct abstention on NOT_IN_GRAPH: 12/12 (100.0%); of those with an empty candidate list: 12/12 (100.0%)
- wrong links: 0
- latency per reference (ms, measured): p50 233.5, p95 442.8, max 595.9

| category | n | resolved | correct | wrong | in-graph abstained | absent abstained (empty list) |
|---|---|---|---|---|---|---|
| abr_company | 45 | 30 | 30 | 0 | 15 |  |
| abr_trading_name | 10 | 6 | 6 | 0 | 4 |  |
| abr_trust | 18 | 14 | 14 | 0 | 4 |  |
| absent_invented | 3 | 0 | 0 | 0 | 0 | 3/3 (3) |
| absent_nz_namesake | 3 | 0 | 0 | 0 | 0 | 3/3 (3) |
| absent_out_of_slice | 6 | 0 | 0 | 0 | 0 | 6/6 (6) |
| accc_recipient | 5 | 4 | 4 | 0 | 1 |  |
| afsl_licensee | 28 | 22 | 22 | 0 | 6 |  |
| banned_org | 10 | 7 | 7 | 0 | 3 |  |
| credit_licensee | 22 | 14 | 14 | 0 | 8 |  |
| gleif_au | 28 | 19 | 19 | 0 | 9 |  |
| hard_negative_in_graph | 8 | 5 | 5 | 0 | 3 |  |
| national_company | 14 | 7 | 7 | 0 | 7 |  |

### Wrong links


Latency is the `Matcher.resolve` call per row on a Windows laptop (CPU, embeddings loaded once, after a
warm-up call); process start and model load (about 20 s) are not included. Wall clock for the 200
rows was 48 s.

**Wrong links: none.** Every resolved row is correct, the 12 absent references all abstain with an
empty candidate list, and no hard negative links to its famous namesake (CSC never goes to CBA;
"Westpac New Zealand Limited" and "ANZ Bank New Zealand Ltd" abstain).

### Where recall goes (60 in-graph abstentions; reported, not tuned)

Resolved / total by corruption, sampled rows only (a row can carry several):

| corruption | resolved | | corruption | resolved |
|---|---|---|---|---|
| "P/L" for Pty Ltd | 2 / 21 | | embedded valid ABN / ACN | 31 / 31 |
| appended address / city | 12 / 30 | | embedded ABN, bad check digit | 3 / 5 |
| one-word typo | 25 / 52 | | embedded ACN, bad check digit | 0 / 2 |
| legal form dropped | 14 / 19 | | trustee wording | 13 / 16 |
| "Pty" only | 12 / 16 | | upper-cased | 22 / 24 |

Patterns seen in the abstention explanations, each a candidate normaliser improvement:

1. **"P/L" is not read as a legal form**: the token stays in the name and the candidate fails the
   missing-token gate (19 of 21 rows abstain).
2. **City names before a state** ("Wesfarmers Ltd, Perth WA", "BHP Group Ltd., Melbourne VIC",
   "Commonwealth Bank of Aust., Sydney NSW") leave PERTH / MELBOURNE / SYDNEY (and the legal form
   before the comma) in the name: missing-token gate.
3. **CORP inside a name** is not expanded to CORPORATION ("Westpac Banking Corp Tasmanian Staff
   Social Club", "Commonwealth Bank Officers Superannuation Corp Pty Ltd", "Commonwealth Super Corp").
   "Westpac Banking Corp" alone resolves (trailing weak form stripped).
4. **Acronyms**: "CBA" scores 0.70 NAME_FUZZY and abstains; "(NAB)" in parentheses blocks NAB;
   "ANZ Banking Group Limited" matches only an other_name of ANZ and the formal-name rule refuses it.
5. **Business names held by individuals**: "whinam environmental services" and "Ann & Waynes Food"
   find the right party by NAME_NORMALISED_EXACT and are blocked by the person / organisation veto
   (PARTY_TYPE_CONFLICT), because the text reads as an organisation.
6. **Trust vs company kind**: "HOME TRADER SUPER FUND" (the GLEIF name of HOME TRADER SUPER FUND PTY
   LTD) is refused as trust-or-fund vs company.

All six are abstentions, the safe error. A customer sees "not found" rather than a wrong company.

## Running it on the supplied file

`outputs/resolve_results.jsonl` currently holds this rehearsal run on my substitute set, not the
brief's references; the command below overwrites it.

```
.venv/Scripts/bizgraph resolve-file dirty_references.jsonl outputs/resolve_results.jsonl --db data/bizgraph.duckdb
```

(`.venv/bin/bizgraph` on Linux / macOS; `--db` may also go before the command, and defaults to
`BIZGRAPH_DB` / settings.) The input schema is detected, not assumed: JSONL, a JSON array (or an
object wrapping one), CSV / TSV with a header, or one reference per line; a UTF-8 BOM, blank lines
and non-UTF-8 (cp1252) text are handled. The id is the first of `id`, `reference_id`, `ref_id`,
`rid`, `key` (else the row number); the text is the first of `reference`, `text`, `query`, `raw`,
`input`, else `name`, `company`, `entity_name`, with `abn` / `acn` / `lei` / `state` / `postcode`
appended when given as separate fields. A row that cannot be read is written as abstained with an
`error`; output order is input order. Each output row starts with the brief's fields
(`reference_id`, `candidates` [canonical_key, name, score, match_type, evidence, path], `decision`,
`latency_ms`) followed by the decision detail and an `input` echo of the original row. The command
prints counts by decision and p50 / p95 latency. `--limit N` and `--k N` are available.

To score my substitute again: run the command above on
`outputs/rehearsal/dirty_references_substitute.jsonl`, then
`.venv/Scripts/python outputs/rehearsal/score.py outputs/resolve_results.jsonl outputs/rehearsal/answer_key.jsonl`.
