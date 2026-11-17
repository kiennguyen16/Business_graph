# Graph queries

Ultimate parent, the graph-only questions, traversal caps and the selection-criteria projection, with
query text, results on the final data, runtimes and what the traversal does when an ownership chain
cycles. Every number below was measured on 2026-11-18 against the full v3 store.

Code: `src/bizgraph/services/traversal.py` (TraversalService), `src/bizgraph/services/projection.py`
(ProjectionService), CLI `bizgraph ultimate-parent | entity | project`, tests `tests/test_services.py`.
The demo (`demo/app.py`, Traversals and Projection pages) calls the same methods.

## 0. What these numbers ran on

| Input | Value |
|---|---|
| Store | `data/snap_v3_demo.duckdb` (read-only copy of the final store), matcher version `m-94f4f6b2-d37e44c6` (v3) |
| Graphs | exported from that store by `RdfExporter` (`demo/export_graphs.py --nq`), bulk loaded with `scripts/bulk_load.sh` into a fresh TDB2 store: 13,626,485 quads, load 160 s |
| Per graph (triples) | canonical 11,789,763; links v3 505,831; gleif_l1 940,056; gleif_l2 84,798; asic_afsl 149,492; asic_credit 127,460; asic_liquidator 14,383; accc_notice 426; asic_banned_org 221; derived licence_history 13,126; ontology 929 |
| GLEIF slice | L2 now includes the foreign parents reached from AU/NZ children (transitive, bounded): 8,306 L2 records; DIRECT edges valid today: 2,236 |
| Server | Fuseki 5.5.0 / TDB2, union default graph, `-Xmx3g`, one laptop. Runtimes are wall clock from the Python client and include HTTP. p50 over 3 to 5 runs unless stated |

Node identity. Facts point at source records; party roles live only in the links graph
`urn:graph:links:m-94f4f6b2-d37e44c6`. A node is the canonical party when a link attributes the
record (or exactly one canonical party carries the record's LEI / ABN / ACN), else the record itself
(`urn:src:gleif_l1:{lei}`). With GLEIF L1 resolved by v3, all 2,108 party nodes in the ownership
index come from links; the other 1,769 nodes are foreign GLEIF records with no Australian party.

## 1. Ultimate parent

### Algorithm (`TraversalService.ultimate_parent`, pure core `walk_chain`)

The bounding lives in Python, not in SPARQL. Each hop is one query; the walk owns depth, the visited
set and the choice between parents.

```
start = resolve(key)                       # LEI, ABN, ACN, party IRI or record IRI
visited = {start: 0}; chain = [start]
loop:
    parents = one_hop(node, as_of)         # record-level SPARQL below, plus party-level bg:owned/bg:owner
    dedupe by parent node (same parent through several facts counts once, highest % kept)
    none                    -> TOP_REACHED (NO_PARENT if depth 0)
    choose_parent:          one parent -> follow ("single")
                            a parent > 50%  -> follow ("majority")
                            all % known, one strictly highest -> follow ("plurality")
                            otherwise -> AMBIGUOUS: stop, return every candidate edge
    depth == max_depth (10) -> TRUNCATED: stop, nothing is called ultimate
    parent in visited       -> CYCLE: stop, cycle_path = chain[visited[parent]:] + [parent],
                               ultimate_parent = None
    append, continue
then cross-check the top against GLEIF's own IS_ULTIMATELY_CONSOLIDATED_BY edge for the start
```

Every edge on the returned `OwnershipChain` carries the fact IRI, relationship kind, percentage,
validity interval, relationship status, source graph, the L2 source record, the level (record or
party) and the rule that chose it.

### One hop, record level (the query sent per node)

```sparql
SELECT ?rec ?f ?g ?kind ?other ?pct ?from ?to ?status ?src WHERE {
  VALUES ?rec { <urn:src:gleif_l1:5493002Q4UIXQGSO4I28> }
  VALUES ?kind { bg:IS_DIRECTLY_CONSOLIDATED_BY bg:SHAREHOLDING }
  GRAPH ?g {
    ?f a bg:Ownership ; bg:relationshipKind ?kind ; bg:aboutRecord ?rec ; bg:counterpartyRecord ?other .
    OPTIONAL { ?f bg:ownershipPercentage ?pct }
    OPTIONAL { ?f bg:validFrom ?from }  OPTIONAL { ?f bg:validTo ?to }
    OPTIONAL { ?f bg:relationshipStatus ?status }
    OPTIONAL { ?f prov:wasDerivedFrom ?src }
  }
  FILTER ((!BOUND(?from) || ?from <= "2026-11-18"^^xsd:date) && (!BOUND(?to) || ?to >= "2026-11-18"^^xsd:date))
  FILTER (!BOUND(?status) || ?status != "INACTIVE")
}
```

`?rec` holds every record of the node (for a party: its linked records, the records it was derived
from, its GLEIF record by LEI and GLEIF records carrying its ABN / ACN). With no `as_of` the walk is
"current" and INACTIVE relationships are excluded; with an explicit `as_of` only the validity interval
decides, because `relationshipStatus` describes the snapshot, not the date asked about.

### One hop, party level (only when the node is a party)

```sparql
SELECT ?f ?g ?kind ?otherParty ?pct ?from ?to ?status ?src WHERE {
  GRAPH <urn:graph:links:m-94f4f6b2-d37e44c6> { ?f bg:owned <urn:abn:80787808096> ; bg:owner ?otherParty . }
  OPTIONAL { GRAPH ?g { ?f a bg:Ownership .
    OPTIONAL { ?f bg:relationshipKind ?kind } OPTIONAL { ?f bg:ownershipPercentage ?pct }
    OPTIONAL { ?f bg:validFrom ?from } OPTIONAL { ?f bg:validTo ?to }
    OPTIONAL { ?f bg:relationshipStatus ?status } OPTIONAL { ?f prov:wasDerivedFrom ?src } } }
  FILTER ((!BOUND(?from) || ?from <= "2026-11-18"^^xsd:date) && (!BOUND(?to) || ?to >= "2026-11-18"^^xsd:date))
}
```

This follows ownership from sources that only exist as party roles (shareholdings) and the role
edges the exporter derives from links. A fact seen at both levels counts once.

### The property-path version, and why it is not enough

```sparql
SELECT DISTINCT ?ancestor WHERE {
  <START> (^bg:aboutRecord/bg:counterpartyRecord)+ ?ancestor .
  FILTER NOT EXISTS { ?ancestor ^bg:aboutRecord/bg:counterpartyRecord ?higher }
}
```

It returns the right top for the Macquarie chain, but: (1) it cannot filter the intermediate
`bg:Ownership` node on relationship kind or validity, so DIRECT, ULTIMATE and expired edges are mixed;
(2) SPARQL 1.1 has no depth bound; (3) it returns no path, depth or percentages; (4) it cannot choose
between two parents; (5) on a cycle `+` terminates (set semantics) but every node in the cycle has a
parent, so the "no higher ancestor" filter returns nothing and the cycle is invisible; (6) it works on
records only, so it cannot see a loop that exists only after resolution (section 1.2).

### 1.1 Worked examples

**Citigroup, 6 hops** (`bizgraph ultimate-parent 5493002Q4UIXQGSO4I28`):

```
[TOP_REACHED] depth=6:
  CSCAL Nominees Pty Limited [urn:abn:30123717680]                         party (link)
  -> CITIGROUP SECURITIES CLEARING AUSTRALIA LIMITED [urn:abn:52001355906] party (link)
  -> CITIGROUP PTY LIMITED [urn:abn:88004325080]                           party (link)
  -> CITIBANK OVERSEAS INVESTMENT CORPORATION [urn:src:gleif_l1:CYSD4L2598RQ9BPPCB72]  record
  -> Citibank, National Association [urn:src:gleif_l1:E57ODZWZ7FF32TWEFA76]           record
  -> CITICORP LLC [urn:src:gleif_l1:549300PSHWOM1D1JVL23]                               record
  -> CITIGROUP INC. [urn:src:gleif_l1:6SHGI4ZSSLCXXQSBB395]                             record
edges: 6 x IS_DIRECTLY_CONSOLIDATED_BY, ACTIVE, rule=single each, valid from 2017-10-02
       (2017-07-12 for CITIGROUP PTY -> CITIBANK OVERSEAS), no percentage published,
       facts urn:fact:gleif_l2:{child}%7CIS_DIRECTLY_CONSOLIDATED_BY%7C{parent}
       in urn:graph:source:gleif_l2:2026-11-16
GLEIF ultimate: CITIGROUP INC. -> agree
26 queries, p50 369 ms (first, cold, run 852 ms)
```

The three Australian nodes are canonical parties through v3 links; the four foreign ones have no
Australian registration and stay GLEIF records. Before the slice was extended the walk stopped at
CITIBANK OVERSEAS INVESTMENT CORPORATION and the GLEIF cross-check said `disagree_off_chain`.

**Macquarie, 3 hops** (`bizgraph ultimate-parent 3538003NQP2Z8ZI0KA94`):

```
[TOP_REACHED] depth=3: マッコーリーエナジージャパン株式会社 [urn:src:gleif_l1:3538003NQP2Z8ZI0KA94]
  -> MACQUARIE INTERNATIONAL FINANCE LIMITED [urn:abn:62092985263]
  -> MACQUARIE BANK LIMITED [urn:abn:46008583542]
  -> MACQUARIE GROUP LIMITED [urn:abn:94122169279]
edges: IS_DIRECTLY_CONSOLIDATED_BY from 2020-05-21, 2000-05-23, 1983-04-26; rule=single each
GLEIF ultimate: MACQUARIE GROUP LIMITED -> agree
20 queries, p50 228 ms
```

### 1.2 Cycles: the one in the data, and how the traversal reports it

Whole-slice run (`ownership_index()` then `all_chains()`): the index loads every DIRECT edge valid
today in 12 queries (3,720 ms); walking all 2,236 children in memory takes 20 ms.

| Status | Chains |
|---|---|
| TOP_REACHED | 2,235 |
| CYCLE | **1** |
| AMBIGUOUS / TRUNCATED | 0 / 0 |

**The cycle.** GLEIF says the fund `Hudson Superfund` (LEI 549300NDURDQU6FNEL59, category GENERAL) is
directly consolidated by `Hudson Life Inv PL ATF Hudson SF` (LEI 5493007743QNCRI21297, category FUND),
i.e. its trustee acting for the fund, ACTIVE since 2022-04-18. v3 links both GLEIF records to the same
ABR party, `The Trustee for Hudson Superfund` (urn:abn:80787808096): the trustee record carries the
fund's ABN (EXACT_ABN, 1.0) and the fund record's name is unique (NAME_NORMALISED_EXACT, 0.97). The
links graph therefore holds `bg:owned` and `bg:owner` pointing at the same party, and the party-level
hop returns the node as its own parent:

```
$ bizgraph ultimate-parent 80787808096
[CYCLE] depth=1: The Trustee for Hudson Superfund [urn:abn:80787808096]
  CYCLE: urn:abn:80787808096 -> urn:abn:80787808096
  cycle_detected=True, ultimate_parent=None
  edge IS_DIRECTLY_CONSOLIDATED_BY urn:abn:80787808096 -> urn:abn:80787808096, ACTIVE, from 2022-04-18,
       fact urn:fact:gleif_l2:549300NDURDQU6FNEL59%7CIS_DIRECTLY_CONSOLIDATED_BY%7C5493007743QNCRI21297
12 queries, 102 ms
```

What the traversal does with it:

* `ultimate_parent` stops at the first repeated node, returns status `CYCLE`, the loop in
  `cycle_path`, the edge that closed it, and **no ultimate parent** (a cycle has no top; we do not pick
  one). Cost is bounded by the loop length.
* `group_exposure` and every group report leave the chain out of all groups and count it in
  `unresolved` (`{'CYCLE': 1}` below), so the party is not attributed to any controller.
* The record level has no loop: an independent check for any record that is its own ancestor,
  `?f a bg:Ownership ; bg:aboutRecord ?x . ?x (^bg:aboutRecord/bg:counterpartyRecord)+ ?x`, returns
  nothing (250 ms), and the property path from the party's records returns no top (17 ms). The cycle
  exists only after resolution collapses fund and trustee into one party.
* The record-level hop already drops "two records of one party owning each other" as an identity
  collapse; the party-level hop (role edges in the links graph, no record to compare) does not, which
  is why this case surfaces as CYCLE. Both readings are defensible (a trust consolidated by its own
  trustee is not an ownership chain), and the cycle report is the safe one: nothing downstream treats
  it as a group. To change it, apply the same identity-collapse rule to party-level rows in
  `TraversalService._edges_from_rows`.
* The earlier v2 store produced two CYCLE chains; with v3 links one of them no longer collapses.
  Synthetic tests cover a real A -> B -> C -> A loop, the depth cap and the ambiguous case.

### 1.3 Depth distribution and the deepest chains (as of 2026-11-18)

Depth over the 2,235 chains that reach a top: 1: 1,758, 2: 358, 3: 87, 4: 17, 5: 13, **6: 2**. The
GLEIF cross-check: 2,024 agree, 139 have no GLEIF ultimate edge, 70 `disagree_off_chain`, 3
`disagree_on_chain`.

| Depth | Chain (child -> ... -> top) | GLEIF |
|---|---|---|
| 6 | CSCAL Nominees -> Citigroup Securities Clearing Australia -> Citigroup Pty -> Citibank Overseas Investment Corp -> Citibank, N.A. -> Citicorp LLC -> Citigroup Inc. | agree |
| 6 | Goldman Sachs Australia Nominee Holdings -> Goldman Sachs Australia -> Goldman Sachs Holdings ANZ -> Goldman Sachs Holdings (Hong Kong) -> Goldman Sachs Holdings (Asia Pacific) -> Goldman Sachs (Asia) Corporate Holdings LLC -> The Goldman Sachs Group, Inc. | agree |
| 5 | Goldman Sachs Financial Markets -> Goldman Sachs Holdings ANZ -> ... -> The Goldman Sachs Group, Inc. | agree |
| 5 | Goldman Sachs Australia -> Goldman Sachs Holdings ANZ -> ... -> The Goldman Sachs Group, Inc. | agree |
| 5 | Goldman Sachs Australia Services -> Goldman Sachs Holdings ANZ -> ... -> The Goldman Sachs Group, Inc. | agree |
| 5 | Citibank Australia Staff Superannuation -> Citigroup Pty -> Citibank Overseas Investment Corp -> Citibank, N.A. -> Citicorp LLC -> Citigroup Inc. | agree |
| 5 | Citicorp Nominees -> Citigroup Pty -> ... -> Citigroup Inc. | agree |
| 5 | Citisecurities -> Citigroup Pty -> ... -> Citigroup Inc. | agree |
| 5 | Dervat Nominees -> Citigroup Global Markets Australia -> Citigroup Global Markets Australia Holdings -> Citigroup Financial Products Inc. -> Citigroup Global Markets Holdings Inc. -> Citigroup Inc. | agree |
| 5 | Calex Nominees -> Citigroup Global Markets Australia -> ... -> Citigroup Inc. | agree |

## 2. Questions only the graph can answer

### 2.1 Parties within 2 hops of a banned (or noticed, or suspended) party (`near_flagged`, `within_hops`)

Seeds: every `bg:Ban` fact's record (or `bg:InfringementNotice`, or a licence with a suspended
status), attributed to a party through the links graph, and widened by exact ABN / ACN / LEI equality
to other records of the same company (labelled `same_identifier`, never shown as a resolver link).
Expansion per node over any relationship whose roles the ontology marks
`bg:traversalPolicy "expand"`:

```sparql
# phase 1: which relationships touch the node's records (record level)
SELECT ?f ?other ?dir WHERE {
  VALUES ?x { <record IRIs of the node> }
  { ?f bg:aboutRecord ?x ; bg:counterpartyRecord ?other . BIND("out" AS ?dir) }
  UNION { ?f bg:counterpartyRecord ?x ; bg:aboutRecord ?other . BIND("in" AS ?dir) }
  UNION { ?f bg:aboutRecord ?x ; bg:counterpartyAcn ?acn . ?other bg:acn ?acn ; a bg:SourceRecord . BIND("out" AS ?dir) }
  UNION { ?x bg:acn ?acn . ?f bg:counterpartyAcn ?acn ; bg:aboutRecord ?other . BIND("in" AS ?dir) }
}
# party level: any two-party role pair in the links graph
SELECT ?f ?r1 ?other WHERE {
  VALUES ?r1 { bg:owner bg:owned bg:trust bg:trustee bg:member bg:affiliatedWith } VALUES ?r2 { ...same... }
  GRAPH <urn:graph:links:m-94f4f6b2-d37e44c6> { ?f ?r1 <party> ; ?r2 ?other . FILTER(?other != <party>) }
}
# phase 2: attributes of exactly those facts (type, kind, validity), then in Python: drop
# IS_ULTIMATELY_CONSOLIDATED_BY (derived, would jump across a group), apply validity on as_of
```

Python bounding: breadth-first to `hops`, visited set, fan-out cap per node (`neighbours_per_node`,
default 50, ranked active first, then ownership before trusteeship before affiliation, then recent
first) and a node cap (`max_nodes`, default 200); dropped neighbours are counted in
`truncated_counts`.

| Flag | Seeds | Records bridged by identity | Parties within 2 hops | Queries | p50 |
|---|---|---|---|---|---|
| ban (ASIC banned organisations) | 15 | 0 | **0** | 67 | 363 ms |
| ACCC infringement notice | 18 | 15 | **0** | 60 | 421 ms |
| suspended credit licence | 9 | 2 | **0** | 37 | 545 ms |

**0 is the real answer, not a failure.** None of the 15 banned organisations' ACNs appears on any
GLEIF, AFSL, credit or liquidator record, so there is no relationship to walk; the noticed companies
and suspended licensees are not members of any GLEIF group either. The open data has no
person-level director or shareholder edges, which is where this question would normally find its
answer. On the synthetic graph the question returns HOLDCO at 1 hop (80 per cent shareholding) and
THE FAMILY TRUST at 2 hops, and stops before a party 3 hops out
(`test_within_two_hops_of_banned_party`).

`within_hops` on its own: Macquarie Group Limited at 2 hops reaches 49 nodes in 74 queries, p50
334 ms, nothing truncated. Over 30 sampled linked parties: p50 26 ms, p95 33 ms.

### 2.2 Who controls the licensees, and who shares a group with a flag (`group_exposure`)

"Which AFSL / ACL holders are ultimately controlled from outside Australia and New Zealand, through
how many hops, and which licensed entities sit in the same corporate group as an entity carrying a
regulatory flag (ban, ACCC notice, suspended licence, licence CANCELLED_OR_LAPSED in the last 3
months)?"

Why only the graph answers it: group membership is a variable-depth walk up the ownership forest
(bounded, cycle-safe) and back down; the licence sits on one entity, the flag on another, the
controller's country on a third; the three come from different registers (ASIC, GLEIF L1, GLEIF L2)
that share no key except through resolved identity. In SQL it is a recursive CTE with cycle handling
per group, joined through the link table, per question.

Method: load every DIRECT edge once (`OwnershipIndex.load`, the record-level hop query without
`VALUES ?rec`, plus the party-level role query), walk every chain with the same `walk_chain`, group
members by their top (chains ending CYCLE / TRUNCATED / AMBIGUOUS join no group), then one query for
licences and flags on all members (their records, records sharing their ABN / ACN, and the
`bg:licensee` / `bg:bannedParty` / `bg:noticeRecipient` roles), one for the tops' `bg:country`, and
`licence_event` from DuckDB joined by holder ABN / ACN.

Result: 3,258 group members in 1,023 groups, 28 queries, p50 1,069 ms (first run 1,830 ms),
unresolved `{'CYCLE': 1}`. Group tops by country: AU 396, US 156, DE 72, NZ 72, GB 57, JP 41, FR 30,
CA 23.

**128 licensees are controlled from outside AU / NZ**: US 53, GB 12, DE 11, FR 7, JE 6, BM 4, JP 4,
NL 4, CA 4, GI 3, CH 3, VG 3 (22 countries in all). The deepest:

| Licensee | Licence | Hops | Controller (top of the bounded chain) | Country |
|---|---|---|---|---|
| Citigroup Securities Clearing Australia Ltd | AFSL 284956 | 5 | Citigroup Inc. | US |
| Goldman Sachs Australia Pty Ltd | AFSL 243346 | 5 | The Goldman Sachs Group, Inc. | US |
| Goldman Sachs Financial Markets Pty Ltd | AFSL 247147 | 5 | The Goldman Sachs Group, Inc. | US |
| TFS Australia Pty Limited | AFSL 230557 | 4 | Viel et Compagnie-Finance | FR |
| CurrencyFair Australia Pty Ltd | AFSL 402709 | 4 | Standard Chartered PLC | GB |
| Schroder Investment Management Australia Ltd | AFSL 226473 | 4 | Schroders Limited | GB |
| American Express Australia Ltd | ACL + AFSL 291313 | 4 | American Express Company | US |
| Citigroup Global Markets Australia Pty Ltd | AFSL 240992 | 4 | Citigroup Inc. | US |
| Citigroup Pty Limited | ACL + AFSL 238098 | 4 | Citigroup Inc. | US |
| Marex Australia Pty Ltd | AFSL 529155 | 3 | Marex Group Limited | BM |

With the extended GLEIF slice the controllers are now the real tops (Citigroup Inc., The Goldman
Sachs Group) rather than the first foreign intermediate. Known error: the three EQT licensees (Equity
Trustees Limited, Equity Trustees Wealth Services, EQT Responsible Entity Services) count as
controlled from `GI` because EQT Holdings Limited's GLEIF `bg:country` exports as GI; it is an
ASX-listed Australian company, so the true count is 125 (see section 6).

**5 licensed entities share a group with a flagged entity** (all flags are recent licence
cancellations; no ban, notice or suspension sits inside a GLEIF group):

| Group top | Flagged member (flag) | Licensed member in the same group |
|---|---|---|
| TP ICAP Group PLC (JE) | Tullett Prebon (Australia) Pty Ltd: AFSL 224852 CANCELLED_OR_LAPSED, gone between 2026-02-24 and 2026-11-02 | TP ICAP (Australia) Pty Ltd, AFSL 234593 |
| TP ICAP Group PLC | same | TP ICAP Markets (Australia) Pty Ltd, AFSL 312525 |
| TP ICAP Group PLC | same | ICAP Futures (Australia) Pty Ltd, AFSL 234579 |
| Citigroup Inc. (US) | Citigroup Pty Limited: ACL 238098 CANCELLED_OR_LAPSED, gone between 2025-11-29 and 2026-11-15 | Citigroup Securities Clearing Australia Ltd, AFSL 284956 |
| Citigroup Inc. | same | Citigroup Global Markets Australia Pty Ltd, AFSL 240992 |

Attribution of each row: the licences through v3 links, the flag through the event holder's ABN
(`event_holder_identifier`). Both flags carry wide date bounds (the archived register snapshots have
gaps), so "in the last 3 months" is true by the upper bound only; section 4 explains the bounds.

Licence concentration by group (top 5): Perpetual 10 licences across 8 licensed members (18
members), QIC 7 across 7, Macquarie Group 6 across 5 (52 members, depth 3), Industry Super Holdings
5 across 5, Morgan Stanley 5 across 5 (13 members, depth 4).

## 3. Capping what a traversal returns (`TraversalBudget`, `entity_view`)

Every fact type has a quota; items are ranked active before historical, then most recent first;
categories are ordered regulatory first: bans, notices, licences, parents, GLEIF ultimate parents,
trusteeships, affiliations, subsidiaries, products. `truncated_counts` and `truncation_note()` say
what was dropped.

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
MACQUARIE BANK LIMITED [urn:abn:46008583542] (party)
identifiers: abn=46008583542 (asic_afsl, asic_credit, canonical), acn=008583542 (+ gleif_l1),
             afslNumber=237502, aclNumber=237502, lei=4ZHCHI4KYZG2WVRT8631, lei=549300MPRNPO6FWNKN78
source records: urn:src:gleif_l1:4ZHCHI4KYZG2WVRT8631, urn:src:gleif_l1:549300MPRNPO6FWNKN78,
                urn:src:asic_afsl:237502, urn:src:asic_credit:237502
licences (2):
  active  2010-12-24.. ACL 237502   [record+link] urn:fact:asic_credit:237502
  active  2004-03-01.. AFSL 237502  [record+link] urn:fact:asic_afsl:237502
parents (1):
  active  1983-04-26.. MACQUARIE GROUP LIMITED [record+link]
ultimate_parents (1):
  active  1983-04-26.. MACQUARIE GROUP LIMITED [record+link]
subsidiaries (16, 5 shown):
  active  2023-09-25.. SUSTAINABLE FEEDSTOCKS GROUP LIMITED
  active  2018-05-12.. MACQUARIE AEROSPACE INVESTMENTS LIMITED
  active  2017-10-26.. PUMA Masterfund S-4
  active  2017-07-27.. Macquarie Investments LLC
  active  2017-07-22.. Mac Fund One Trust
truncated: 11 more subsidiaries truncated
```

Two LEIs resolve to Macquarie Bank (the second is a GLEIF record for a Macquarie Bank branch
registration), and subsidiaries hang off both; the view unions them.

Runtime: `entity_view` p50 37 ms, p95 51 ms over 40 linked parties. Facts are fetched in two phases
(which facts touch the node, then `VALUES ?f` for their attributes); a single query with the
attribute block after a UNION made Jena scan every typed fact.

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
`banned_and_licensed` (ban attributed at confidence >= 0.95, any licence). Specs take `all`, `any`,
`not` (inside `all` only), per-predicate `min_confidence`, windows as ISO durations (`P3M`, `P90D`) or
explicit dates, and `columns` with wildcards.

### Plan and query text

The planner sends `notice`, `ban` and `licence` to SPARQL (fact in a source graph, party from the
role edge in one links graph, link match type and confidence alongside) and `licence_event` and
`party` attribute filters to DuckDB. Inside `all`, graph predicates run first and the surviving
parties are pushed into the SQL step as a key table.

```sparql
SELECT ?party ?fact ?g ?rec ?link ?mt ?conf ?from ?to ?reg ?amt ?desc WHERE {
  GRAPH ?g { ?fact a bg:InfringementNotice ; bg:aboutRecord ?rec .
    OPTIONAL { ?fact bg:validFrom ?from } OPTIONAL { ?fact bg:validTo ?to } }
  GRAPH <urn:graph:links:m-94f4f6b2-d37e44c6> {
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
            AND ev.event_date BETWEEN ? AND ?),   -- 'CANCELLED_OR_LAPSED', 'AFSL', 2026-08-18, 2026-11-18
linked AS (SELECT ev.*, l.link_id, l.canonical_key, l.match_type, l.confidence, 'link' AS attribution
           FROM ev JOIN link l ON l.source = ev.source AND ltrim(l.record_id,'0') = ltrim(ev.licence_no,'0')
            AND l.matcher_version = ?           -- 'm-94f4f6b2-d37e44c6'
           WHERE coalesce(l.confidence, 1.0) >= ?),
by_id AS (... holder_abn_before / holder_acn_before = party_canonical.abn / acn,
          match_type EVENT_HOLDER_ABN / EVENT_HOLDER_ACN, only where no link exists)
SELECT ... event_date, observed_after, holder_name_before, record_iri, link_id, match_type, confidence, attribution
FROM (linked UNION ALL by_id) JOIN party_canonical ... [AND canonical_key IN (SELECT canonical_key FROM _proj_restrict)]
```

Output: one row per party: `party`, `canonical_key`, `name`, `abn`, `acn`, `lei`, `links_graph`,
`as_of`, `matched_predicates`, `min_link_confidence`, and per predicate `{id}__fact`, `__source`,
`__record`, `__link`, `__match_type`, `__confidence`, `__attribution`, `__n_matches`, and for licence
events `__event_date` and `__observed_after`.

### Results, and why the dates are bounds

The AFSL register lists current licences only, so a cancellation is inferred from a licence that
disappears between archived snapshots. `event_date` is the first snapshot without it (upper bound),
`observed_after` the last snapshot with it (lower bound, exclusive). The archive has a gap from
2026-02-24 to 2026-11-02 (AFSL) and from 2025-11-29 to 2026-11-15 (credit).

| As of 2026-11-18 | Rows | p50 |
|---|---|---|
| ACCC half: parties with an attributed ACCC infringement notice | 5 (The Sleeping Giant, HSK United, Digital Imaging Express, Dysck, Bayswood Timber Wholesalers), all EXACT_ACN links | 41 ms |
| AFSL half: CANCELLED_OR_LAPSED with `event_date` in the last 3 months | 198 parties: 196 dated 2026-11-02 with `observed_after` 2026-02-24, 1 dated 2026-11-10, 1 dated 2026-11-11; 192 attributed by v3 link (EXACT_ABN 184, EXACT_ACN 8), 6 by event holder ABN | 941 ms |
| ... with `"certain": true` (lower bound also inside the window) | 2: Golden Layout Plus Pty Ltd (AFSL 470050, between 2026-11-02 and 2026-11-10), MYCFA Pty Ltd (AFSL 288132, between 2026-11-10 and 2026-11-11) | |
| **Brief's example (notice AND AFSL cancelled in 3 months)** | **0 rows.** None of the 5 noticed companies held an AFSL that lapsed; ACCC notices go to consumer-facing businesses, AFSL lapses to financial-services holders. The synthetic test `test_brief_example_returns_expected_rows` checks the positive case | 961 ms |
| `any` of the two | 203 parties | 909 ms |
| `accc_notice_in_window_and_afsl_cancelled_3m` | 0 | 946 ms |
| `banned_and_licensed` | 0 (no banned organisation holds a licence) | 2,607 ms |

So "cancelled in the last 3 months" is true for 2 licences with certainty and for up to 198 by upper
bound; 196 of those could have lapsed as early as late February. The projection filters on the upper
bound by default and always ships both columns.

## 5. Tests (`tests/test_services.py`, no Fuseki)

The same SPARQL runs in-process over an rdflib Dataset with a union default graph
(`LocalEndpoint`). Covered: cycle A -> B -> C -> A terminates with the cycle path; depth cap;
majority and ambiguous parents; the choice rule table; validity filtering; linked records become
parties and the GLEIF cross-check agrees; LEI-free identifier equality only when unique; the property
path misses the cycle; in-memory and online walks agree; entity-view truncation counts and ranking;
2-hop banned neighbourhood and the node budget; group exposure and foreign control; window
arithmetic; spec round trip and compilation; the brief's example returning exactly the expected
parties with event bounds and provenance; confidence floor; `certain`; `any` / `not`;
party-attribute predicate pushed down after the graph step.

## 6. Open items

1. **Party-level identity collapse** (section 1.2): apply the record-level rule ("two records of one
   party owning each other is not ownership") to party-level role rows too, or keep reporting it as
   CYCLE. Either way the trust-and-trustee pattern (`... ATF ...`) deserves its own relationship
   (`bg:Trusteeship`), not `IS_DIRECTLY_CONSOLIDATED_BY`.
2. **GLEIF L1 country**: EQT Holdings Limited exports `bg:country` GI; check which address the adapter
   maps (legal address country is the one to use for "controlled from"). Until fixed, the
   foreign-control count is overstated by 3.
3. **Liquidator affiliations**: registered liquidators carry no firm field in the current extract, so
   there is no `bg:Affiliation` edge to walk; "within 2 hops" stays at 0 without person-level data.
4. **Licence dates**: closing the archive gaps (weekly snapshots) would turn the 198 "up to" AFSL
   cancellations into dated ones; the bounds are carried end to end so nothing else changes.
