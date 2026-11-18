# Performance

> **Version note.** Load, export, SHACL and storage figures were measured on the v3 store. The final
> matcher v4 (`m-b5e50f74`) uses the same pipeline and data. Measured v4 resolve latency on the 200 messy
> rehearsal references (`outputs/resolve_results.jsonl`, `latency_ms`): p50 285 ms, p95 419 ms, max 668 ms
> (v3 on its 200-string recipe: p50 188 ms, p95 224 ms). The cost estimate below scales with latency, so
> at v4's p50 it is about USD 0.016 per 1,000 resolutions.

**Measured unless marked estimated.** Windows laptop; matcher `m-94f4f6b2-d37e44c6`. Portable Java 21 / Jena 5.5.0, one JVM at a time, 3 GB heap. No memory failures.

| Source | Ingest s | Final match s | Export s | TDB2 load s |
|---|---:|---:|---:|---:|
| abr | 376.44 | n/a | 27.49 | 168.00 |
| accc_notice | 1.38 | 0.61 | 0.02 | 2.06 |
| asic_afsl | 3.49 | 5.51 | 1.18 | 5.50 |
| asic_banned_org | 0.94 | 0.39 | 0.03 | 2.25 |
| asic_company | 448.95 | n/a | 8.27 | 29.27 |
| asic_credit | 2.06 | 4.58 | 0.27 | 4.67 |
| asic_liquidator | 1.07 | 5.72 | 0.04 | 2.92 |
| gleif_l1 | 16.74 | 147.31 | 2.46 | 12.12 |
| gleif_l2 | 1.13 | n/a | 0.29 | 3.91 |

Ingest values are latest `source_snapshot.wall_clock_s`; ABR uses external wall time **6m16.443s, 4 workers**, including conflict preflight (adapter alone 249.99s). `data/logs/final_refresh_20261117_1739.log` measures canonical build **2m15.082s**, match-all **3m31.250s**, and the final per-source matches above. Earlier v3 timings in `outputs/resolution_run_20261117.md`: AFSL 4.9s, credit 3.9s, banned 0.4s, liquidators 4.8s, GLEIF L1 131.8s, ACCC 0.5s; these precede the final refresh.

All 13 graphs: export **93.74s**, sequential offline bulk load via `scripts/bulk_load.sh` **348.35s**. Canonical export/load 38.79/102.87s. Offline count verification **11.44s**, 29,848,624 triples; all counts match. Counts were verified offline rather than through Fuseki HTTP. SHACL **42.09s**, plus 24.24s sample assembly; 3,860,680 triples conform (scope in `shacl_report.md`).

Allocated disk bytes (Windows GetCompressedFileSizeW): DuckDB **4,828,704,768** (4.50 GiB); TDB2 **14,803,088,844** (13.79 GiB). Logical sizes: 4,828,704,768 / 14,803,088,844 bytes.

ASIC scope: canonical party ACNs, canonical `asic_record_id`, canonical identifier-table ACNs, ACNs from non-ABR/non-ASIC sources (Tier 2/3), GLEIF trustee ACNs, and quarantined ASIC record IDs. Result: 260,810 records. `all_asic_company=True` exports the full register.

**Estimated cloud cost:** assume AWS EC2 m6i.xlarge (4 vCPU, 16 GiB), Linux, **USD 0.20/hour**, purely a pricing assumption, not a current quote. Measured warm resolve p50 **188 ms**, p95 **224 ms** imply estimated serial throughput 5.32 / 4.46 resolutions/s, assuming equal cloud latency. Cost per 1,000 = 1,000 x latency / 3,600 x 0.20: **USD 0.0104 / 0.0124** at p50/p95. Embeddings run locally, so API cost is **USD 0**; storage, network, idle time and cold start are excluded.
