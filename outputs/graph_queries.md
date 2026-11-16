# Graph queries

Draft. Ultimate parent, two graph-only questions, traversal caps and the selection-criteria
projection, with query text, results on real data, runtimes and the cycle behaviour.

Code: `src/bizgraph/services/traversal.py` (TraversalService), `src/bizgraph/services/projection.py`
(ProjectionService), CLI `bizgraph ultimate-parent | entity | project`, tests `tests/test_services.py`.

## 0. What these numbers ran on

| Input | Status |
|---|---|
| GLEIF L1 (59,606 records) and L2 (4,420 Ownership facts: 2,058 DIRECT, 2,362 ULTIMATE, 1,389 with a percentage), ASIC AFSL, credit, liquidators, banned organisations | real, snapshot graphs exported from `data/scratch_rdf.duckdb` |
| Canonical graph and links graph `urn:graph:links:m-a722497c-34f01a62` | real but partial: the 10,209 links of one resolution scratch run (AFSL, credit, banned orgs) and the 10,954 canonical parties they point at. GLEIF L1 records were not resolved in that run |
| `licence_event` | real: computed with `licence_history.events_from_files` from the 6 archived AFSL snapshot files (2025-04-14 to 2026-11-10), 2,015 events |
| ACCC infringement notices | real (20 notices from the register extract) but loaded by a scratch stopgap: the RDF exporter does not emit `bg:InfringementNotice` yet (section 6). Attributed by exact ACN/ABN only: 8 of 20 attributed, to 6 parties |
| Store | Fuseki 5 / TDB2, 1.46M triples, union default graph, 2 GB heap, one laptop. Runtimes are wall clock from the Python client and include HTTP |

Node identity. Facts point at source records; party roles live only in the links graph. A node
is the canonical party when a link attributes the record, else when exactly one canonical party
carries the same LEI, ABN or ACN (labelled `lei_equality` / `abn_equality` / `acn_equality`;
an identifier shared by two parties attributes nothing), else the record itself
(`urn:src:gleif_l1:{lei}`). In this run 320 of 3,826 ownership nodes became parties that way;
with GLEIF resolved by the matcher they would come from links.

## 1. Ultimate parent

### Algorithm (`TraversalService.ultimate_parent`, pure core `walk_chain`)

```
start = resolve(key)                      # LEI, ABN, ACN, party IRI or record IRI
visited = {start: 0}; chain = [start]
loop:
    parents = one_hop(node, as_of)        # SPARQL below, plus party-level bg:owned/bg:owner
    dedupe by parent node
    none            -> TOP_REACHED (NO_PARENT if depth 0)
    choose_parent:  one parent -> follow ("single")
                    a parent > 50%  -> follow ("majority")
                    all % known, one strictly highest -> follow ("plurality")
                    otherwise -> AMBIGUOUS, stop, report every candidate
    depth == max_depth (default 10) -> TRUNCATED, stop
    parent in visited -> CYCLE, stop, cycle_path = chain[visited[parent]:] + [parent]
    append, continue
then cross-check against GLEIF's own IS_ULTIMATELY_CONSOLIDATED_BY edge
```

Every edge on the returned `OwnershipChain` carries the fact IRI, relationship kind, percentage,
validity interval, relationship status, source graph, the L2 source record and the rule used.

### One hop (the query sent per node)

```sparql
SELECT ?rec ?f ?g ?kind ?other ?pct ?from ?to ?status ?src WHERE {
  VALUES ?rec { <urn:src:gleif_l1:4ZHCHI4KYZG2WVRT8631> }
  VALUES ?kind { bg:IS_DIRECTLY_CONSOLIDATED_BY bg:SHAREHOLDING }
  GRAPH ?g {
    ?f a bg:Ownership ; bg:relationshipKind ?kind ; bg:aboutRecord ?rec ; bg:counterpartyRecord ?other .
    OPTIONAL { ?f bg:ownershipPercentage ?pct }
    OPTIONAL { ?f bg:validFrom ?from }  OPTIONAL { ?f bg:validTo ?to }
    OPTIONAL { ?f bg:relationshipStatus ?status }
    OPTIONAL { ?f prov:wasDerivedFrom ?src }
  }
  FILTER ((!BOUND(?from) || ?from <= "2026-11-17"^^xsd:date) && (!BOUND(?to) || ?to >= "2026-11-17"^^xsd:date))
  FILTER (!BOUND(?status) || ?status != "INACTIVE")
}
```

`?rec` holds every record of the node (for a party: its linked records, its GLEIF record by LEI
and GLEIF records carrying its ABN/ACN). With no `as_of` the walk is "current": INACTIVE
relationships are excluded. With an explicit `as_of` only the validity interval decides,
because `relationshipStatus` describes the snapshot, not the date asked about. When the node is
a party, a second query follows `bg:owned` / `bg:owner` in the links graph so ownership from
non-GLEIF sources (shareholdings) is walked too; a fact seen at both levels counts once.

### The property-path version, and why it is not enough

```sparql
SELECT DISTINCT ?ancestor WHERE {
  <urn:src:gleif_l1:...> (^bg:aboutRecord/bg:counterpartyRecord)+ ?ancestor .
  FILTER NOT EXISTS { ?ancestor ^bg:aboutRecord/bg:counterpartyRecord ?higher }
}
```

It returns the right top for Macquarie Bank (3 ms), but: (1) it cannot filter the intermediate
`bg:Ownership` node on relationship kind or validity, so DIRECT, ULTIMATE and expired edges are
mixed; (2) SPARQL 1.1 has no depth bound; (3) it returns no path, depth or percentages;
(4) it cannot choose between two parents; (5) on a cycle `+` terminates (set semantics) but
every node in the cycle has a parent, so the "no higher ancestor" filter returns nothing and the
cycle is invisible. The synthetic test `test_property_path_version_runs_but_misses_the_cycle`
shows exactly that: empty result where the walk reports `CYCLE A -> B -> C -> A`.

### What happens when the chain does not terminate

* Cycle (A owns B owns C owns A, or a record that owns itself): the visited set catches the
  first repeat. Status `CYCLE`, `cycle_detected = true`, `cycle_path` lists the loop, the
  ultimate parent is `None` (a cycle has no top; we do not pick one). Cost is bounded by the
  cycle length. Two records of the same party "owning" each other are an identity collapse,
  not a cycle, and are skipped.
* Long or runaway chain: `max_depth` (default 10, CLI `--max-depth`) stops the walk with
  `TRUNCATED` and the last node reached; nothing is called ultimate.
* Several parents and no majority: `AMBIGUOUS`, stop, all candidate edges returned. We do not
  pick by name or by order.
* Group-level reports (section 2.2) leave chains that end in CYCLE, TRUNCATED or AMBIGUOUS out
  of every group and count them in `unresolved`.

Real data: **no cycles**. All 2,058 DIRECT chains end `TOP_REACHED`; the independent
property-path check `?x (^bg:aboutRecord/bg:counterpartyRecord)+ ?x` also finds 0
self-ancestors (45 ms). No node has more than one DIRECT parent (GLEIF allows one), so the
majority rule and the ambiguity stop are exercised only by the synthetic tests and by future
shareholding sources.

### Worked example: a Macquarie entity

```
$ bizgraph ultimate-parent 3538003NQP2Z8ZI0KA94
[TOP_REACHED] depth=3: マッコーリーエナジージャパン株式会社 [urn:src:gleif_l1:3538003NQP2Z8ZI0KA94]
  -> MACQUARIE INTERNATIONAL FINANCE LIMITED [urn:src:gleif_l1:5493008TTI1STFXDYD31]
  -> MACQUARIE BANK LIMITED [urn:abn:46008583542]
  -> MACQUARIE GROUP LIMITED [urn:abn:94122169279]
  edges: IS_DIRECTLY_CONSOLIDATED_BY from 2020-05-21, 2000-05-23, 1983-04-26; rule=single each;
         facts urn:fact:gleif_l2:{child}%7CIS_DIRECTLY_CONSOLIDATED_BY%7C{parent} in
         urn:graph:source:gleif_l2:2026-11-16
GLEIF ultimate: MACQUARIE GROUP LIMITED -> agree
10 queries, 102 ms
```

The two Australian nodes resolve to canonical parties (`acn_equality`); the Japanese and UK
entities stay GLEIF records.

### Top 10 deepest chains (real GLEIF, as of 2026-11-17)

Depth distribution over all 2,058 entities with a direct parent: depth 1: 1,811, depth 2: 215,
depth 3: 32. Nothing deeper exists in this slice.

| # | Chain (child -> ... -> top) | GLEIF ultimate |
|---|---|---|
| 1 | IFM Real Estate Fiduciary -> IFM Investors -> IFM Holdings -> Industry Super Holdings | agree |
| 2 | Merrill Lynch Equities (Australia) -> Merrill Lynch Markets (Australia) -> Merrill Lynch (Australasia) -> Bank of America Global Holdings, LLC | disagree (Bank of America Corp, outside the slice) |
| 3 | Interpath Services -> Bunzl Outsourcing Services -> Bunzl Australasia -> Bunzl plc | agree |
| 4 | Cromwell SPV Finance -> Trustee for Cromwell Diversified Property Trust -> Cromwell Property Securities -> Cromwell Corporation | agree |
| 5 | Centium Software -> Events Software Bidco -> Midco -> Holdco | agree |
| 6 | Crestone Wealth -> LGT Crestone Holdings -> LGT Holding (Australia) -> LGT Investment Holding (Singapore) | disagree |
| 7 | CDPT Finance -> Trustee for Cromwell Diversified Property Trust -> Cromwell Property Securities -> Cromwell Corporation | agree |
| 8 | Macquarie Energy Japan -> Macquarie International Finance -> Macquarie Bank -> Macquarie Group | agree |
| 9 | CSCAL Nominees -> Citigroup Securities Clearing Australia -> Citigroup Pty -> Citibank Overseas Investment Corp | disagree (Citigroup Inc.) |
| 10 | Morgan Stanley Australia Securities (Nominee) -> Morgan Stanley Australia Securities -> Morgan Stanley (Australia) Securities Holdings -> Morgan Stanley International Holdings Inc. | disagree |

### Cross-check against GLEIF ULTIMATE edges

| Outcome | Chains |
|---|---|
| agree (our top is GLEIF's ultimate parent) | 1,645 |
| disagree, GLEIF's ultimate is off our chain | 278 |
| disagree, GLEIF's ultimate is on our chain but not the top | 1 |
| GLEIF reports no ultimate parent | 134 |

The 278 are a **slice boundary**, not a traversal fault: the L2 slice holds relationships of
the AU/NZ entities (1,515 AU and 271 NZ children), so the walk stops at the first foreign
intermediate whose own parent relationship was not loaded (Citibank Overseas Investment Corp
instead of Citigroup Inc., Allianz Australia Insurance instead of Allianz SE). The one
`disagree_on_chain` is a source inconsistency: Apromore Pty Ltd's GLEIF ultimate is still
Apromore Holding, while the direct chain continues to Salesforce, Inc. Both are reported, not
silently reconciled.

### Runtime

| Operation | Measured |
|---|---|
| `ultimate_parent`, online (one-hop queries + GLEIF cross-check), 100 random entities | p50 30 ms, p95 66 ms, max 82 ms; 4 to 10 queries each |
| Load every ownership edge for reports (`OwnershipIndex`, 12 queries) | 527 ms |
| Walk all 2,058 chains in memory with the same `walk_chain` | 26 ms |
| Online and in-memory walks agree on status and top | 100 of 100 sampled |

## 2. Questions only the graph can answer

### 2.1 Parties within 2 hops of a banned or disqualified party (`near_flagged`, `within_hops`)

Seeds: every `bg:Ban` fact's record, attributed to a party through the links graph when a link
exists, and widened by exact ABN/ACN/LEI equality to other records of the same company
(labelled `same_identifier`, never shown as a resolver link). Expansion per node, any
relationship whose roles the ontology marks `bg:traversalPolicy "expand"`:

```sparql
# phase 1: which relationships touch the node's records (record level)
SELECT ?f ?other ?dir WHERE {
  VALUES ?x { <record IRIs of the node> }
  { ?f bg:aboutRecord ?x ; bg:counterpartyRecord ?other . BIND("out" AS ?dir) }
  UNION { ?f bg:counterpartyRecord ?x ; bg:aboutRecord ?other . BIND("in" AS ?dir) }
  UNION { ?f bg:aboutRecord ?x ; bg:counterpartyAcn ?acn . ?other bg:acn ?acn ; a bg:SourceRecord . BIND("out" AS ?dir) }
  UNION { ?x bg:acn ?acn . ?f bg:counterpartyAcn ?acn ; bg:aboutRecord ?other . BIND("in" AS ?dir) }
}
# party level: any two-party role pair in the links graph (owner/owned, trust/trustee, member/affiliatedWith)
SELECT ?f ?r1 ?other WHERE {
  VALUES ?r1 { bg:owner bg:owned bg:trust bg:trustee bg:member bg:affiliatedWith } VALUES ?r2 { ...same... }
  GRAPH <urn:graph:links:{v}> { ?f ?r1 <party> ; ?r2 ?other . FILTER(?other != <party>) }
}
# phase 2: attributes of exactly those facts (type, kind, validity), then in Python:
# drop IS_ULTIMATELY_CONSOLIDATED_BY (derived, would jump across a group), apply validity on as_of
```

Breadth-first to `hops`, visited set, fan-out cap per node (`neighbours_per_node`, default 50,
ranked active first, then ownership before trusteeship before affiliation, then recent first)
and a node cap (`max_nodes`, default 200). Dropped neighbours are counted in
`truncated_counts`.

**Real result: 0 parties.** 15 banned organisations, none of whose ACNs appears on any GLEIF,
AFSL, credit or liquidator record, so they have no relationship to walk; 9 suspended credit
licensees (the same question with flag `suspended`): 0 as well. That is a finding about the
data (the banned-organisation list is mostly long-defunct entities, and no person-level
director data is in the open sources), not about the traversal. On the synthetic graph the
question returns HOLDCO at 1 hop (80 per cent shareholding) and THE FAMILY TRUST at 2 hops
(HOLDCO is its trustee), and stops before a party 3 hops out
(`test_within_two_hops_of_banned_party`). Runtime: 160 to 270 ms for all seeds; `within_hops(2)`
p50 40 ms, p95 99 ms over 30 nodes; Macquarie Group at 2 hops: 45 nodes, 209 ms.

### 2.2 The better question: which licensees are controlled from where, and who shares a group with a flagged entity (`group_exposure`)

"Which AFSL/ACL holders are ultimately controlled from outside Australia and New Zealand,
through how many hops, and which licensed entities sit in the same corporate group as an
entity carrying a regulatory flag (ban, ACCC notice, suspended licence, licence
CANCELLED_OR_LAPSED in the last 3 months)?"

Why only the graph answers it: group membership is a variable-depth walk up the ownership
forest (bounded, cycle-safe) and back down; the licence sits on one entity, the flag on
another, the controller's country on a third; the three come from three registers (ASIC,
GLEIF L1, GLEIF L2) that share no key except through resolved identity. In SQL it is a
recursive CTE with cycle handling per group, joined through the link table, per question.

Method: load every DIRECT edge once (`OwnershipIndex`), walk every chain with the same bounded
`walk_chain`, group members by top, then one query for licences and flags on all members
(records of the member, records sharing its ABN/ACN, and `bg:licensee` / `bg:bannedParty` /
`bg:noticeRecipient` roles in the links graph), one for the tops' `bg:country`, and
`licence_event` from DuckDB joined by holder ABN/ACN.

Real result (624 ms, 14 queries, 3,127 group members in 1,069 groups):

* **119 licensees are controlled from outside AU/NZ**: US 44, GB 15, DE 9, FR 6, HK 5, SG 5,
  JP 4, CH 4. Group tops: AU 397, US 148, DE 79, GB 77, NZ 72, JP 39.

| Licensee | Licence | Hops | Controller (top of bounded chain) | Country |
|---|---|---|---|---|
| Merrill Lynch Equities (Australia) Ltd | AFSL 235132 | 3 | Bank of America Global Holdings, LLC | US |
| Iberdrola Australia Energy Markets Pty Ltd | AFSL 321435 | 2 | Iberdrola SA | ES |
| ICAP Futures (Australia) Pty Ltd | AFSL 234579 | 2 | TP ICAP Asia Pacific Holdings Ltd | GB |
| Schroder Investment Management Australia Ltd | AFSL 226473 | 2 | Schroder International Holdings Ltd | GB |
| TP ICAP (Australia) Pty Ltd | AFSL 234593 | 2 | TP ICAP Asia Pacific Holdings Ltd | GB |
| Goldman Sachs Australia Pty Ltd | AFSL 243346 | 2 | Goldman Sachs Holdings (Hong Kong) Ltd | HK |
| Goldman Sachs Financial Markets Pty Ltd | AFSL 247147 | 2 | Goldman Sachs Holdings (Hong Kong) Ltd | HK |

* Licence concentration by group: Perpetual 10 licences across 8 licensed members (18
  members), QIC 7 across 7, Macquarie Group 6 across 5 (48 members, depth 3), Industry Super
  Holdings 5, Westpac 5, ANZ 4, NAB 4.
* **Flag exposure: 0 groups** in this slice. No flagged entity (ban, suspended licence,
  attributed ACCC notice, recent AFSL cancellation) is a GLEIF group member. The synthetic test
  checks the positive case.

Caveats, stated rather than hidden: the controller is the top of the loaded chain, so at the
slice boundary it is a foreign intermediate (Goldman Sachs Holdings (Hong Kong) rather than The
Goldman Sachs Group, Inc.); the country still reads foreign in every such case. The country is
GLEIF L1 `bg:country` as exported; EQT Holdings Limited comes out as `GI`, which looks wrong
for an ASX-listed Australian company and suggests the adapter maps a non-legal address
(flagged in section 6). Licences found by `same_identifier:acn` are exact ACN equality between
the GLEIF record and the licence record, not matcher links.

## 3. Capping what a traversal returns (`TraversalBudget`, `entity_view`)

Every fact type has a quota; items are ranked active before historical, then most recent
first; categories are ordered regulatory first: bans, notices, licences, parents, GLEIF
ultimate parents, trusteeships, affiliations, subsidiaries, products. `truncated_counts` and
`truncation_note()` say what was dropped.

| Category | Default cap |
|---|---|
| identifiers / source records | 30 / 20 |
| bans / notices | 20 / 20 (never the thing to drop) |
| licences | 10 |
| parents / GLEIF ultimate parents | 5 / 5 |
| trusteeships / affiliations | 10 / 10 |
| subsidiaries | 15 |
| products (ARTG sponsorships) | 5 |
| neighbours per node / nodes per neighbourhood | 50 / 200 |

So the brief's "three licences, 400 ARTG products and nine subsidiaries" becomes: all three
licences, all nine subsidiaries, the 5 most recent active products, and
`"395 more products truncated"`.

```
$ bizgraph entity 46008583542 --cap subsidiaries=5
MACQUARIE BANK LIMITED [urn:abn:46008583542] (party, attribution=canonical)
identifiers: abn=46008583542, aclNumber=237502, acn=008583542, afslNumber=237502, lei=4ZHCHI4KYZG2WVRT8631
source records: urn:src:gleif_l1:4ZHCHI4KYZG2WVRT8631, urn:src:asic_afsl:237502, urn:src:asic_credit:237502
licences (2):
  active  2010-12-24.. ACL 237502 [record+link] urn:fact:asic_credit:237502
  active  2004-03-01.. AFSL 237502 [record+link] urn:fact:asic_afsl:237502
parents (1):
  active  1983-04-26.. MACQUARIE GROUP LIMITED [record] urn:fact:gleif_l2:4ZHCH...%7CIS_DIRECTLY_CONSOLIDATED_BY%7CACMHD...
ultimate_parents (1):
  active  1983-04-26.. MACQUARIE GROUP LIMITED [record] urn:fact:gleif_l2:4ZHCH...%7CIS_ULTIMATELY_CONSOLIDATED_BY%7CACMHD...
subsidiaries (15):
  active  2018-05-12.. MACQUARIE AEROSPACE INVESTMENTS LIMITED
  active  2017-10-26.. PUMA Masterfund S-4
  active  2017-07-27.. Macquarie Investments LLC
  active  2017-07-22.. Mac Fund One Trust
  active  2017-05-12.. Puma Series 2015-3
truncated: 10 more subsidiaries truncated
```

Runtime: `entity_view` p50 29 ms, p95 43 ms over 80 entities (40 parties, 40 records).
Facts are fetched in two phases (which facts touch the node, then `VALUES ?f` for their
attributes); a single query with the attribute block after a UNION made Jena scan every typed
fact (5 s instead of 30 ms).

## 4. Selection criteria to dataset (`ProjectionService`)

### The brief's example as a named spec

```json
{
  "name": "accc_notice_and_afsl_cancelled_3m",
  "match": {"all": [
    {"id": "accc_notice", "fact": "notice", "regulator": "ACCC"},
    {"id": "afsl_cancelled", "fact": "licence_event", "event_type": "CANCELLED_OR_LAPSED",
     "licence_kind": "AFSL", "window": {"last": "P3M"}}
  ]},
  "min_confidence": 0.0
}
```

Also named: `accc_notice_in_window_and_afsl_cancelled_3m` (notice in the last 12 months) and
`banned_and_licensed` (ban attributed at confidence >= 0.95, any licence). Specs take `all`,
`any`, `not` (inside `all` only), per-predicate `min_confidence`, windows as ISO durations
(`P3M`, `P90D`) or explicit dates, and `columns` with wildcards (`"afsl_cancelled__*"`).

### Plan (`bizgraph project accc_notice_and_afsl_cancelled_3m --explain`)

The planner sends `notice`, `ban` and `licence` to SPARQL (fact in a source graph, party from
the role edge in one links graph, link match type and confidence alongside) and `licence_event`
and `party` attribute filters to DuckDB. Inside `all`, graph predicates run first and the
surviving parties are pushed into the SQL step as a key table.

```sparql
SELECT ?party ?fact ?g ?rec ?link ?mt ?conf ?from ?to ?reg ?amt ?desc WHERE {
  GRAPH ?g { ?fact a bg:InfringementNotice ; bg:aboutRecord ?rec .
    OPTIONAL { ?fact bg:validFrom ?from } OPTIONAL { ?fact bg:validTo ?to } }
  GRAPH <urn:graph:links:m-a722497c-34f01a62> {
    ?fact bg:noticeRecipient ?party .
    OPTIONAL { ?link bg:sourceRecord ?rec ; bg:party ?party .
               OPTIONAL { ?link bg:matchType ?mt } OPTIONAL { ?link bg:confidence ?conf } } }
  OPTIONAL { ?fact bg:regulator ?reg0 } OPTIONAL { ?fact bg:amountAud ?amt }
  OPTIONAL { ?fact bg:description ?desc } OPTIONAL { ?rec bg:sourceId ?srcid }
  BIND(COALESCE(?reg0, IF(?srcid = "accc_notice", "ACCC", ?reg0)) AS ?reg) FILTER(?reg = "ACCC")
}
```

```sql
WITH ev AS (SELECT * FROM licence_event ev WHERE ev.event_type = ? AND ev.licence_kind = ?
            AND ev.event_date BETWEEN ? AND ?),              -- 'CANCELLED_OR_LAPSED','AFSL',2026-08-17,2026-11-17
linked AS (SELECT ev.*, l.link_id, l.canonical_key, l.match_type, l.confidence, 'link' AS attribution
           FROM ev JOIN link l ON l.source = ev.source AND ltrim(l.record_id,'0') = ltrim(ev.licence_no,'0')
            AND l.matcher_version = ? WHERE coalesce(l.confidence, 1.0) >= ?),
by_id AS (... holder_abn_before / holder_acn_before = party_canonical.abn / acn,
          match_type EVENT_HOLDER_ABN / EVENT_HOLDER_ACN, only where no link exists)
SELECT ... event_date, observed_after, holder_name_before, record_iri, link_id, match_type, confidence, attribution
FROM (linked UNION ALL by_id) JOIN party_canonical ... [AND canonical_key IN (SELECT canonical_key FROM _proj_restrict)]
```

Output: one row per party: `party`, `canonical_key`, `name`, `abn`, `acn`, `lei`,
`links_graph`, `as_of`, `matched_predicates`, `min_link_confidence`, and per predicate
`{id}__fact`, `__source` (source graph or `duckdb:licence_event`), `__record`, `__link`,
`__match_type`, `__confidence`, `__attribution`, `__n_matches`, and for licence events
`__event_date` and `__observed_after`. CSV or Parquet by extension (`--out`).

### Dates on cancellations are bounds, and both are projected

The AFSL register lists current licences only, so a cancellation is inferred from a licence
that disappears between snapshots. `event_date` is the first snapshot without it (upper bound),
`observed_after` the last snapshot with it (lower bound, exclusive). The archived history has a
gap from 2026-02-24 to 2026-11-02, which matters a lot here:

| Real data, as of 2026-11-17 | Rows |
|---|---|
| AFSL CANCELLED_OR_LAPSED events with `event_date` in the last 3 months | 198 events (197 dated 2026-11-02 with `observed_after` 2026-02-24, 1 dated 2026-11-10 with `observed_after` 2026-11-02) |
| ... attributed to a canonical party in this partial canonical slice | 50 parties, all by holder ABN (`EVENT_HOLDER_ABN`): the cancelled records had left the snapshot that was resolved, so no link exists for them |
| ... with `"certain": true` (lower bound also inside the window) | 1 party: GOLDEN LAYOUT PLUS PTY LTD, AFSL 470050, between 2026-11-02 and 2026-11-10 |
| ACCC notices attributed (exact ACN/ABN) | 6 parties (Cotton On Australia, The Sleeping Giant, HSK United, Digital Imaging Express, Dysck, Bayswood Timber Wholesalers) |
| **Brief's example (notice AND AFSL cancelled in 3 months)** | **0 rows.** None of the 6 noticed companies held an AFSL that lapsed. The synthetic test `test_brief_example_returns_expected_rows` checks the positive case, including a party attributed only by holder ABN and a 0.7-confidence notice link that `min_confidence: 0.8` removes |
| `any` of the two | 56 parties, 79 ms |

So "cancelled in the last 3 months" is true for 1 licence with certainty and for up to 198 by
upper bound; 197 of those could have lapsed as early as late February. The projection does not
pick one reading: it filters on the upper bound by default and always ships both columns.

Runtime: brief example end to end 106 ms (0 rows); AFSL half alone 65 ms (50 rows); CLI
process including Python start-up about 1.8 s.

## 5. Tests (`tests/test_services.py`, 22 tests, about 6 s, no Fuseki)

The same SPARQL runs in-process over an rdflib Dataset with a union default graph
(`LocalEndpoint`). Covered: cycle A -> B -> C -> A terminates with the cycle path; depth cap;
majority and ambiguous parents; the choice rule table; validity filtering (parent before 2010
vs after 2011, nothing before 2000); linked records become parties and the GLEIF cross-check
agrees; LEI-free identifier equality only when unique; the property path misses the cycle;
in-memory and online walks agree; entity-view truncation counts and ranking; 2-hop banned
neighbourhood and the node budget; group exposure and foreign control; window arithmetic; spec
round trip and compilation (engines, SQL parameter order); the brief's example returning
exactly the expected parties with event bounds and provenance; confidence floor; `certain`;
`any` / `not`; party-attribute predicate pushed down after the graph step.

## 6. What the exporter and ontology need to add

1. **Exporter: emit `bg:InfringementNotice`** for `accc_notice` records (validFrom = validTo =
   date issued, `bg:regulator "ACCC"`, `bg:amountAud` when stated, `bg:description`) and
   `bg:noticeRecipient` in the links graph (add `accc_notice` to the role map in
   `_role_triples`). Today the notice predicate can only run on the stopgap graph used above.
   Multi-party notices need one fact per party (`IriFactory.fact(source, rid, n)`).
2. **Exporter: `bg:Affiliation`** for registered liquidators and their firms (the payload has no
   firm field in the current extract), so "within 2 hops via liquidator" has edges to walk.
3. **Licence events in the graph (optional)**: `licence_event` lives only in DuckDB, which is
   why the planner sends it to SQL. If time questions should be answerable in SPARQL alone, emit
   CANCELLED_OR_LAPSED as `bg:validTo` on the AFSL holding plus `bg:validToNotBefore`
   (observed_after); the ontology needs that second property, since `bg:validTo` alone would
   state a precision the data does not have.
4. **Ontology: an interval-uncertainty pair** (`bg:validToNotBefore` / `bg:validFromNotAfter`)
   for the same reason, and say in NOTES that `bg:relationshipStatus` is snapshot status, not
   validity.
5. **GLEIF slice**: load the L2 relationships of foreign parents reached from AU/NZ children
   (transitively, bounded) so chains stop at the real top; 278 chains currently stop at the slice
   boundary.
6. **GLEIF L1 country**: check which address the adapter maps to `bg:country` (EQT Holdings
   Limited exports as `GI`); the legal-address country is the one to use for "controlled from".
7. **Links for GLEIF L1**: the scratch matcher run did not resolve `gleif_l1`, so 315 GLEIF
   records were attributed here by unique ACN equality and 5 by ABN equality. Once the matcher
   links them, `bg:owned` / `bg:owner` role edges carry the attribution and these fall back paths
   go quiet.
