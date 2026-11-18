# SHACL and published-store report

Date: 2026-11-18. Matcher: `m-94f4f6b2-d37e44c6`. Input: `data/snap_v3_publish.duckdb`, opened read-only.

**Conforms: true.** Jena 5.5.0 on portable Java 21 validated 3,860,680 input triples in 42.09 s (measured), with 0 results and no memory failures. One JVM at a time, maximum heap 3 GB.

## Validation scope

CRC32 of UTF-8 N-Triples subject token (including angle brackets) modulo 1024 = 0; retain every triple of chosen subjects. Add complete canonical and source descriptions referenced from full small graphs, then source descriptions referenced by selected canonical parties. Small graphs and ontology included in full. No orphan type-only sampling.

Every small graph, including v3 links and licence history, is included in full in one union. The large-graph hash samples are expanded with complete subject descriptions needed by the small graphs and canonical provenance. This checks cross-graph roles without creating partially described typed subjects. Global identifier uniqueness outside the selected canonical subjects is not proven.

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
| `urn:graph:links:m-94f4f6b2-d37e44c6` | full | 0 | 87,264 | 505,831 |
| `urn:graph:derived:licence_history` | full | 0 | 1,393 | 13,126 |
| `urn:graph:canonical` | sample plus reference closure | 1,034 | 62,974 | 768,715 |
| `urn:graph:source:abr:2026-11-11` | sample plus reference closure | 1,064 | 58,361 | 739,913 |
| `urn:graph:source:asic_company:2026-11-09` | sample plus reference closure | 236 | 43,421 | 515,330 |

Sample assembly took 24.24 s (measured). Raw union: `data/rdf/published/shacl_work/final_union.nt`; raw Jena report: `data/rdf/published/shacl_work/final_report.ttl`.

```text
tools/jdk-21.0.13+9/bin/java.exe -Xmx3g -cp "tools/apache-jena-5.5.0/lib/*" shacl.shacl validate --shapes ontology/shapes.ttl --data data/rdf/published/shacl_work/final_union.nt
```

## Offline store verification

All 13 graph counts exactly match their exports: **29,848,624 triples**. The offline query took 11.44 s (measured). Only the latest source snapshots and the requested matcher version are published.

| Named graph | Stored triples |
|---|---:|
| `urn:graph:canonical` | 11,789,763 |
| `urn:graph:derived:licence_history` | 13,126 |
| `urn:graph:links:m-94f4f6b2-d37e44c6` | 505,831 |
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

Run with `tools/jdk-21.0.13+9/bin/java.exe -Xmx3g -cp "tools/apache-jena-5.5.0/lib/*" tdb2.tdbquery --loc=data/tdb2 --query=data/rdf/published/graph_counts.rq --results=JSON`. No Fuseki HTTP server was started, per the revised instruction. Every JVM exited before the next started.

Loading used a newly created empty `data/tdb2`.

## Load-report definitions and tests

`outputs/load_report.csv` has exactly the requested six columns. Nodes are distinct IRI subjects; edges are distinct IRI-valued triples excluding `rdf:type`. Counts are computed from the exported triples whose store counts were verified above. Ingest rejection totals are taken from each latest source snapshot; ASIC export trimming is a publication scope choice, not an ingest rejection. Canonical, links and licence history rows use the `derived:` prefix; ontology is not an input-source row.

Regression coverage includes canonical ACN, enrichment record ID, Tier 2 ACN, Tier 3 ACN, GLEIF trustee ACN, identifier-table ACN, quarantine evidence, exclusion of unrelated companies, and the export-all override.

`.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_rdf_export.py tests/test_ontology.py` completed with **104 passed, 1 skipped** in 64.65 s. The live Fuseki test was skipped because no HTTP server was running.
