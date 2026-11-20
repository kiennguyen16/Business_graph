# SHACL and published-store report

Date: 2026-11-20. Matcher: `m-b5e50f74-d37e44c6` (v4, final). The full store was first validated and loaded on 2026-11-18 with v3 (`m-94f4f6b2-d37e44c6`); v4 changes only the links graph, so v4 was checked by swapping that graph (see "v4 revalidation" below).

**Conforms: true.** Jena 5.5.0 on portable Java 21 validated 3,862,238 input triples in 36.72 s (measured), with 0 results and no memory failures. One JVM at a time, maximum heap 3 GB. The v3 union (3,860,680 triples, 42.09 s) also conformed with 0 results.

## v4 revalidation

Only `urn:graph:links:*` depends on the matcher; ontology, source, canonical and licence history graphs come from the same snapshots and are unchanged (their stored counts below are identical to v3).

* **Export.** `bizgraph publish --graph urn:graph:links:m-b5e50f74-d37e44c6`: 505,808 triples (v3: 505,831) in 14.46 s.
* **SHACL union.** From the v3 union, every triple of the v3 links graph was removed (505,831, matched line by line), all 505,808 v4 links triples were added, and the complete descriptions of 123 subjects that v4 links reference but the v3 union did not describe were added by the same closure rule (55 canonical parties, 752 triples; their 55 ABR and 13 ASIC company source records, 673 and 156 triples). Result: 3,862,238 triples, no duplicates, assembled in 20.53 s.
* **Store.** The v4 links graph was bulk loaded into the existing `data/tdb2` (13.31 s) and the v3 links graph dropped with `DROP GRAPH` (9.31 s). Counts were then re-verified offline (12.10 s).

## Validation scope

CRC32 of UTF-8 N-Triples subject token (including angle brackets) modulo 1024 = 0; retain every triple of chosen subjects. Add complete canonical and source descriptions referenced from full small graphs, then source descriptions referenced by selected canonical parties. Small graphs and ontology included in full. No orphan type-only sampling.

Every small graph, including the links graph and licence history, is included in full in one union. The large-graph hash samples are expanded with complete subject descriptions needed by the small graphs and canonical provenance. This checks cross-graph roles without creating partially described typed subjects. Global identifier uniqueness outside the selected canonical subjects is not proven.

| Graph | Mode | Hash-selected subjects | Total included subjects | Included triples |
|---|---|---:|---:|---:|
| `urn:graph:ontology` | full | 0 | 162 | 929 |
| `urn:graph:source:accc_notice:2026-11-17` | full | 0 | 41 | 426 |
| `urn:graph:source:asic_afsl:2026-11-11` | full | 0 | 13,103 | 149,492 |
| `urn:graph:source:asic_banned_org:2026-11-09` | full | 0 | 31 | 221 |
| `urn:graph:source:asic_credit:2026-11-15` | full | 0 | 8,617 | 127,460 |
| `urn:graph:source:asic_liquidator:2026-11-09` | full | 0 | 1,821 | 14,383 |
| `urn:graph:source:gleif_l1:2026-11-16` | full | 0 | 59,717 | 940,056 |
| `urn:graph:source:gleif_l2:2026-11-16` | full | 0 | 13,097 | 84,798 |
| `urn:graph:links:m-b5e50f74-d37e44c6` | full | 0 | 87,264 | 505,808 |
| `urn:graph:derived:licence_history` | full | 0 | 1,393 | 13,126 |
| `urn:graph:canonical` | sample plus reference closure | 1,034 | 63,029 | 769,467 |
| `urn:graph:source:abr:2026-11-11` | sample plus reference closure | 1,064 | 58,416 | 740,586 |
| `urn:graph:source:asic_company:2026-11-09` | sample plus reference closure | 236 | 43,434 | 515,486 |

The v3 union differed only in the links row (505,831 triples) and the closure of the three sampled graphs (62,974 / 58,361 / 43,421 subjects). v3 sample assembly took 24.24 s; the v4 swap took 20.53 s. Raw v4 union: `data/rdf/v4/shacl_work/final_union_v4.nt`; raw Jena report: `data/rdf/v4/shacl_work/final_report_v4.ttl`.

```text
tools/jdk-21.0.13+9/bin/java.exe -Xmx3g -cp "tools/apache-jena-5.5.0/lib/*" shacl.shacl validate --shapes ontology/shapes.ttl --data data/rdf/v4/shacl_work/final_union_v4.nt
```

## Offline store verification

All 13 graph counts exactly match their exports: **29,848,601 triples** (v3: 29,848,624). The offline query took 12.10 s (measured). Only the latest source snapshots and the selected matcher version are published.

| Named graph | Stored triples |
|---|---:|
| `urn:graph:canonical` | 11,789,763 |
| `urn:graph:derived:licence_history` | 13,126 |
| `urn:graph:links:m-b5e50f74-d37e44c6` | 505,808 |
| `urn:graph:ontology` | 929 |
| `urn:graph:source:abr:2026-11-11` | 13,098,624 |
| `urn:graph:source:accc_notice:2026-11-17` | 426 |
| `urn:graph:source:asic_afsl:2026-11-11` | 149,492 |
| `urn:graph:source:asic_banned_org:2026-11-09` | 221 |
| `urn:graph:source:asic_company:2026-11-09` | 3,123,515 |
| `urn:graph:source:asic_credit:2026-11-15` | 127,460 |
| `urn:graph:source:asic_liquidator:2026-11-09` | 14,383 |
| `urn:graph:source:gleif_l1:2026-11-16` | 940,056 |
| `urn:graph:source:gleif_l2:2026-11-16` | 84,798 |

```sparql
SELECT ?g (COUNT(*) AS ?triples)
WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g ORDER BY ?g
```

Run with `tools/jdk-21.0.13+9/bin/java.exe -Xmx3g -cp "tools/apache-jena-5.5.0/lib/*" tdb2.tdbquery --loc=data/tdb2 --query=data/rdf/published/graph_counts.rq --results=JSON`. Counts were verified offline with tdbquery; no Fuseki server was needed. Every JVM exited before the next started.

Loading used a newly created empty `data/tdb2`.

## Load-report definitions and tests

`outputs/load_report.csv` has six columns. Nodes are distinct IRI subjects; edges are distinct IRI-valued triples excluding `rdf:type`. Counts are computed from the exported triples whose store counts were verified above. Ingest rejection totals are taken from each latest source snapshot; ASIC export trimming is a publication scope choice, not an ingest rejection. Canonical, links and licence history rows use the `derived:` prefix; ontology is not an input-source row.

Regression coverage includes canonical ACN, enrichment record ID, Tier 2 ACN, Tier 3 ACN, GLEIF trustee ACN, identifier-table ACN, quarantine evidence, exclusion of unrelated companies, and the export-all override.

`.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_rdf_export.py tests/test_ontology.py` completed with **104 passed, 1 skipped** in 64.65 s. The live Fuseki test was skipped because no HTTP server was running.
