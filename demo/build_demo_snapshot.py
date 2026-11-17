"""Build the trimmed demo bundle that the hosted app runs from (no Fuseki, no 3 GB store).

    python demo/build_demo_snapshot.py [--src data/snap_v3_demo.duckdb] [--out demo/bundle]
                                       [--sample 5000] [--seed 42]

The source file is opened READ-ONLY. Output:

    demo/bundle/demo.duckdb            trimmed store (schema identical to the full one)
    demo/bundle/licence_event.parquet  licence events (the store's table; derived from the archived
                                       register files only when the store has none)
    demo/bundle/rdf/*.nt.gz            published graphs exported FROM the bundle (so graph and
                                       store agree), loaded into rdflib by the app
    demo/bundle/rdf/manifest.json      graph IRI, file, triple count per graph
    demo/bundle/build_info.json        what was kept, sizes, timings

Which parties are kept (set K):
  1. every party linked from a Tier 2/3 source (AFSL, credit, banned orgs, liquidators, ACCC)
     under the demo matcher version, and the best candidate of every Tier 2/3 abstention;
  2. the GLEIF ownership slice: every L1 record that appears in an L2 edge (with v3 this includes
     the foreign parents, so the Citigroup and Macquarie chains walk to their real tops), the
     parties those records are linked to, and parties sharing their LEI / ABN / ACN (the
     traversal's equality attribution);
  3. the holders (ABN / ACN before and after) of every licence event;
  4. every candidate the FULL matcher generates for the demo's example queries, so the Resolve
     page shows the same candidates as against the full store;
  5. the example entities of the Entity and Traversals pages, quarantined parties, and the best
     candidate of every GLEIF abstention refused by a gate (JURISDICTION_MISMATCH, AMBIGUOUS,
     IDENTIFIER_CONFLICT, PARTY_TYPE_CONFLICT, QUARANTINED_TARGET);
  6. a seeded random sample of organisations (default 5,000) so browsing is not only hits.

Links and abstentions (demo matcher version only): all Tier 2/3; for GLEIF, every L1 record in
the ownership slice, every L1 record linked to a kept party (so an entity page lists all of its
linked records) and every gate abstention, each with its source record.

Resolution indexes. `NameIndex.ensure` rebuilds res_* from the bundle, then the corpus
statistics that the scores and the exact path depend on are taken from the FULL index:
`n_keys` (how many parties carry a normalised name: NAME_NORMALISED_EXACT needs exactly one),
token document frequency / IDF, block sizes and the person-name vocabulary. Without that a
name that is shared in the full store would look unique in the bundle and link. Blocking still
only retrieves parties that are in the bundle: a query for a party outside K returns fewer
candidates than the full store would (stated in the app header).

Full-store totals (links and abstentions by source and reason) are copied to `demo_full_counts`
so the app can say how much of each it holds.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    BUNDLE_DIR,
    SNAPSHOT_DB,
    TIER23_SOURCES,
    compute_licence_events,
    connect_ro,
    ENTITY_EXAMPLES,
    make_matcher,
    matcher_version,
    stored_policy,
)

EXAMPLE_QUERIES = (
    "Commonwealth Bank of Australia",
    "Commonwealth Superannuation Corporation",
    "Commonwealth Bank of Aust ABN 48 123 123 124",
    "AMP Capital",
    "Bluegum Trust",
    "Vacaciones eDreams",
    "Macquarie Group",
    "Macquarie Bank",
    "Westpac Banking Corporation",
    "National Australia Bank",
    "Citigroup Pty Limited",
    "Goldman Sachs Australia",
    "Merrill Lynch Equities (Australia)",
    "John Smith",
)

GATE_REASONS = "'JURISDICTION_MISMATCH', 'AMBIGUOUS', 'IDENTIFIER_CONFLICT', 'PARTY_TYPE_CONFLICT', 'QUARANTINED_TARGET'"
COPY_ALL = ("matcher_version", "source_snapshot", "quarantine")


def example_candidate_keys(src_db: Path, version: str) -> set[str]:
    store = connect_ro(src_db)
    policy, _ = stored_policy(store.con, version)
    m, _ = make_matcher(store, policy)
    keys: set[str] = set()
    for text in EXAMPLE_QUERIES:
        d = m.resolve(text)
        keys |= {r.canonical_key for r in d.ranked}
    store.close()
    return keys


def build(src_db: Path, out_dir: Path, sample: int, seed: int) -> dict:
    import duckdb

    t_start = time.perf_counter()
    info: dict = {"src": str(src_db), "sample": sample, "seed": seed, "timings_s": {}}
    out_dir.mkdir(parents=True, exist_ok=True)
    db = out_dir / "demo.duckdb"
    tmp = out_dir / "demo.duckdb.building"
    for p in (tmp, Path(str(tmp) + ".wal")):
        if p.exists():
            p.unlink()

    probe = connect_ro(src_db)
    version = matcher_version(probe.con)
    probe.close()
    info["matcher_version"] = version

    t = time.perf_counter()
    ex_keys = example_candidate_keys(src_db, version)
    info["timings_s"]["example_candidates"] = round(time.perf_counter() - t, 1)
    info["example_candidate_keys"] = len(ex_keys)

    con = duckdb.connect(str(tmp))
    con.execute(f"SET memory_limit='{os.environ.get('BIZGRAPH_MEMORY_LIMIT', '2GB')}'")
    con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"ATTACH '{src_db.as_posix()}' AS src (READ_ONLY)")
    tiers = ", ".join(f"'{s}'" for s in TIER23_SOURCES)
    con.execute("CREATE TEMP TABLE v AS SELECT ? AS mv", [version])

    # licence events: the store's own table when it has one (v3 does), else derived from the
    # archived register files with the pipeline's code
    from bizgraph.pipeline import licence_history as lh

    t = time.perf_counter()
    if con.execute("SELECT count(*) FROM duckdb_tables() WHERE database_name = 'src' AND table_name = 'licence_event'"
                   ).fetchall()[0][0]:
        con.execute("CREATE TABLE licence_event AS SELECT * FROM src.licence_event")
        info["licence_event_origin"] = "copied from the store"
    else:
        events = compute_licence_events()
        con.execute(lh.LICENCE_EVENT_DDL)
        ph = ", ".join("?" for _ in lh._COLUMNS)
        con.executemany(f"INSERT INTO licence_event ({', '.join(lh._COLUMNS)}) VALUES ({ph})", [e.row() for e in events])
        info["licence_event_origin"] = "derived from data/raw history files"
    info["licence_events"] = con.execute("SELECT count(*) FROM licence_event").fetchall()[0][0]
    info["timings_s"]["licence_events"] = round(time.perf_counter() - t, 1)

    t = time.perf_counter()
    # GLEIF slice: every L1 record on an L2 edge
    con.execute("""CREATE TEMP TABLE l1 AS
        SELECT DISTINCT lei AS record_id FROM (
            SELECT json_extract_string(payload, '$.child_lei') AS lei FROM src.source_record WHERE source = 'gleif_l2'
            UNION ALL SELECT json_extract_string(payload, '$.parent_lei') FROM src.source_record WHERE source = 'gleif_l2')
        WHERE lei IS NOT NULL""")
    con.execute("CREATE TEMP TABLE k (canonical_key VARCHAR, why VARCHAR)")
    con.execute(f"""INSERT INTO k SELECT canonical_key, 'tier23_link' FROM src.link
                    WHERE matcher_version = (SELECT mv FROM v) AND source IN ({tiers})""")
    con.execute(f"""INSERT INTO k SELECT best_candidate, 'tier23_abstention_best' FROM src.abstention
                    WHERE matcher_version = (SELECT mv FROM v) AND source IN ({tiers}) AND best_candidate IS NOT NULL""")
    con.execute("""INSERT INTO k SELECT l.canonical_key, 'gleif_slice_link' FROM src.link l JOIN l1 USING (record_id)
                   WHERE l.matcher_version = (SELECT mv FROM v) AND l.source = 'gleif_l1'""")
    con.execute("""INSERT INTO k SELECT a.best_candidate, 'gleif_slice_abstention_best' FROM src.abstention a
                   JOIN l1 USING (record_id)
                   WHERE a.matcher_version = (SELECT mv FROM v) AND a.source = 'gleif_l1' AND a.best_candidate IS NOT NULL""")
    con.execute("""INSERT INTO k SELECT p.canonical_key, 'gleif_slice_identifier' FROM src.party_canonical p
                   JOIN (SELECT r.lei, r.abn, r.acn FROM src.source_record r JOIN l1 USING (record_id)
                         WHERE r.source = 'gleif_l1') g
                     ON p.lei = g.lei OR p.abn = g.abn OR p.acn = g.acn""")
    con.execute("""INSERT INTO k SELECT p.canonical_key, 'licence_event_holder' FROM src.party_canonical p
                   JOIN licence_event e ON p.abn IN (e.holder_abn_before, e.holder_abn_after)
                                        OR p.acn IN (e.holder_acn_before, e.holder_acn_after)""")
    con.execute("INSERT INTO k SELECT canonical_key, 'quarantine' FROM src.quarantine WHERE canonical_key IS NOT NULL")
    con.executemany("INSERT INTO k VALUES (?, 'example_query_candidate')", [[x] for x in sorted(ex_keys)])
    con.executemany("INSERT INTO k VALUES (?, 'example_entity')", [[x] for x in ENTITY_EXAMPLES])
    # GLEIF abstentions refused by a gate (not just a low score) are all kept, with their best candidate
    con.execute(f"""INSERT INTO k SELECT best_candidate, 'gleif_gate_abstention_best' FROM src.abstention
                    WHERE matcher_version = (SELECT mv FROM v) AND source = 'gleif_l1'
                      AND reason IN ({GATE_REASONS}) AND best_candidate IS NOT NULL""")
    con.execute(f"""INSERT INTO k SELECT canonical_key, 'random_sample' FROM
                    (SELECT canonical_key FROM src.party_canonical WHERE party_type = 'organisation'
                     ORDER BY hash(canonical_key || '{seed}') LIMIT {int(sample)})""")
    info["k_by_reason"] = dict(con.execute("SELECT why, count(DISTINCT canonical_key) FROM k GROUP BY 1 ORDER BY 1").fetchall())
    con.execute("CREATE TEMP TABLE keys AS SELECT DISTINCT canonical_key FROM k WHERE canonical_key IS NOT NULL")
    info["parties"] = con.execute("SELECT count(*) FROM keys").fetchall()[0][0]
    # GLEIF L1 records kept: the ownership slice, every record linked to a kept party, and every
    # gate abstention, so an entity page lists all of its linked records
    con.execute(f"""CREATE TEMP TABLE g1 AS
        SELECT record_id FROM l1
        UNION SELECT l.record_id FROM src.link l JOIN keys USING (canonical_key)
              WHERE l.matcher_version = (SELECT mv FROM v) AND l.source = 'gleif_l1'
        UNION SELECT record_id FROM src.abstention
              WHERE matcher_version = (SELECT mv FROM v) AND source = 'gleif_l1' AND reason IN ({GATE_REASONS})""")
    info["gleif_l1_records"] = con.execute("SELECT count(*) FROM g1").fetchall()[0][0]
    info["timings_s"]["select_parties"] = round(time.perf_counter() - t, 1)

    t = time.perf_counter()
    con.execute("CREATE TABLE party_canonical AS SELECT p.* FROM src.party_canonical p JOIN keys USING (canonical_key)")
    con.execute("CREATE TABLE identifier AS SELECT i.* FROM src.identifier i JOIN keys USING (canonical_key)")
    con.execute("CREATE TABLE alias AS SELECT a.* FROM src.alias a JOIN keys USING (canonical_key)")
    for tname in COPY_ALL:
        con.execute(f"CREATE TABLE {tname} AS SELECT * FROM src.{tname}")
    con.execute("CREATE TABLE label AS SELECT * FROM src.label LIMIT 0")
    con.execute("CREATE TABLE candidate AS SELECT * FROM src.candidate LIMIT 0")
    if con.execute("SELECT count(*) FROM duckdb_tables() WHERE database_name = 'src' AND table_name = 'candidate_ref'"
                   ).fetchall()[0][0]:
        con.execute("CREATE TABLE candidate_ref AS SELECT * FROM src.candidate_ref LIMIT 0")
    # decisions of the demo version only: all Tier 2/3; GLEIF for the kept L1 records
    con.execute(f"""CREATE TABLE link AS SELECT l.* FROM src.link l
        WHERE l.matcher_version = (SELECT mv FROM v)
          AND (l.source IN ({tiers}) OR (l.source = 'gleif_l1' AND l.record_id IN (SELECT record_id FROM g1)))""")
    con.execute(f"""CREATE TABLE abstention AS SELECT a.* FROM src.abstention a
        WHERE a.matcher_version = (SELECT mv FROM v)
          AND (a.source IN ({tiers}) OR (a.source = 'gleif_l1' AND a.record_id IN (SELECT record_id FROM g1)))""")
    # source records: Tier 2/3 and GLEIF L2 in full, the GLEIF L1 slice, and the ABR / ASIC company
    # records the kept parties and their aliases were built from
    con.execute(f"""CREATE TEMP TABLE rec_keys AS
        SELECT DISTINCT source, record_id FROM (
            SELECT source, record_id FROM party_canonical
            UNION ALL SELECT 'asic_company', asic_record_id FROM party_canonical WHERE asic_record_id IS NOT NULL
            UNION ALL SELECT source, record_id FROM alias WHERE record_id IS NOT NULL)""")
    con.execute(f"""CREATE TABLE source_record AS
        SELECT r.* FROM src.source_record r WHERE r.source IN ({tiers}, 'gleif_l2')
        UNION ALL SELECT r.* FROM src.source_record r JOIN g1 USING (record_id) WHERE r.source = 'gleif_l1'
        UNION ALL SELECT r.* FROM src.source_record r JOIN rec_keys k USING (source, record_id)
                  WHERE r.source NOT IN ({tiers}, 'gleif_l2', 'gleif_l1')""")
    con.execute("""CREATE TABLE demo_full_counts AS
        SELECT 'link' AS kind, source, match_type AS label, count(*) AS n FROM src.link
          WHERE matcher_version = (SELECT mv FROM v) GROUP BY ALL
        UNION ALL SELECT 'abstention', source, reason, count(*) FROM src.abstention
          WHERE matcher_version = (SELECT mv FROM v) GROUP BY ALL
        UNION ALL SELECT 'party', source, party_type, count(*) FROM src.party_canonical GROUP BY ALL
        UNION ALL SELECT 'source_record', source, NULL, count(*) FROM src.source_record GROUP BY ALL""")
    con.execute("CREATE TABLE demo_bundle_reason AS SELECT canonical_key, string_agg(DISTINCT why, ',') AS why FROM k GROUP BY 1")
    info["timings_s"]["copy_tables"] = round(time.perf_counter() - t, 1)
    info["rows"] = {tn: con.execute(f"SELECT count(*) FROM {tn}").fetchall()[0][0]
                    for tn in ("party_canonical", "identifier", "alias", "link", "abstention", "source_record",
                               "licence_event", "quarantine")}

    # resolution indexes: rebuild, then take the corpus statistics from the full index
    t = time.perf_counter()
    from bizgraph.resolution.candidates import NameIndex

    info["name_index"] = NameIndex(con).ensure(force=True)
    con.execute("""UPDATE res_name_index b SET n_keys = f.n_keys
                   FROM (SELECT name_norm, max(n_keys) AS n_keys FROM src.res_name_index
                         WHERE name_norm IN (SELECT DISTINCT name_norm FROM res_name_index) GROUP BY 1) f
                   WHERE b.name_norm = f.name_norm""")
    con.execute("""CREATE OR REPLACE TABLE res_token_df AS SELECT f.* FROM src.res_token_df f
                   WHERE f.token IN (SELECT DISTINCT token FROM res_name_token)""")
    con.execute("""CREATE OR REPLACE TABLE res_block_size AS SELECT f.* FROM src.res_block_size f
                   WHERE f.block_token IN (SELECT DISTINCT block_token FROM res_name_index)""")
    con.execute("CREATE OR REPLACE TABLE res_person_vocab AS SELECT * FROM src.res_person_vocab")
    info["timings_s"]["name_index"] = round(time.perf_counter() - t, 1)

    con.execute("DETACH src")
    con.execute("CHECKPOINT")
    con.close()
    # rewrite compactly (drops the space freed by the index rebuild)
    t = time.perf_counter()
    if db.exists():
        db.unlink()
    c2 = duckdb.connect(str(db))
    c2.execute(f"ATTACH '{tmp.as_posix()}' AS b (READ_ONLY)")
    for (tn,) in c2.execute("SELECT table_name FROM duckdb_tables() WHERE database_name = 'b' ORDER BY 1").fetchall():
        c2.execute(f"CREATE TABLE main.{tn} AS SELECT * FROM b.{tn}")
    c2.execute("DETACH b")
    c2.execute("CHECKPOINT")
    c2.execute(f"COPY licence_event TO '{(out_dir / 'licence_event.parquet').as_posix()}' (FORMAT parquet)")
    c2.close()
    tmp.unlink()
    info["timings_s"]["compact"] = round(time.perf_counter() - t, 1)

    # graphs, exported from the bundle itself
    t = time.perf_counter()
    from export_graphs import export

    rdf = out_dir / "rdf"
    if rdf.exists():
        shutil.rmtree(rdf)
    manifest = export(db, rdf, nq=False, gz=True, version=version)
    info["graphs"] = {g["iri"]: g["triples"] for g in manifest["graphs"]}
    info["triples"] = sum(info["graphs"].values())
    info["timings_s"]["export_graphs"] = round(time.perf_counter() - t, 1)

    info["bytes"] = {p.relative_to(out_dir).as_posix(): p.stat().st_size for p in sorted(out_dir.rglob("*")) if p.is_file()
                     and p.name != "build_info.json"}
    info["total_mb"] = round(sum(info["bytes"].values()) / 1e6, 1)
    info["timings_s"]["total"] = round(time.perf_counter() - t_start, 1)
    (out_dir / "build_info.json").write_text(json.dumps(info, indent=2, default=str), encoding="utf-8")
    return info


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=SNAPSHOT_DB)
    ap.add_argument("--out", type=Path, default=BUNDLE_DIR)
    ap.add_argument("--sample", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    info = build(a.src, a.out, a.sample, a.seed)
    print(json.dumps({k: info[k] for k in ("matcher_version", "parties", "rows", "triples", "total_mb", "timings_s")},
                     indent=2, default=str))


if __name__ == "__main__":
    main()
