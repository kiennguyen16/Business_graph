"""`bizgraph` command line entry point."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from bizgraph.config import get_settings


def _store(args: argparse.Namespace):
    from bizgraph.store.duckdb_store import DuckDBStore

    settings = get_settings()
    store = DuckDBStore(args.db or settings.db_path)
    store.init_schema()
    return store


def cmd_init_db(args: argparse.Namespace) -> int:
    get_settings().ensure_dirs()
    with _store(args) as store:
        print(f"schema ready at {store.path}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from bizgraph.sources.registry import registry

    try:
        import bizgraph.sources.adapters  # noqa: F401  (registers adapters)
    except ImportError:
        pass
    path = Path(args.path)
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 2
    try:
        adapter = registry.get(args.source_id)
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return 2
    snapshot = date.fromisoformat(args.snapshot_date) if args.snapshot_date else date.today()
    with _store(args) as store:
        if args.tier2_allowlist or args.acn_conflict_scan:
            import time

            from bizgraph.pipeline.canonical import tier2_reference_ids
            from bizgraph.sources.adapters.tier1 import AbrAdapter

            if not isinstance(adapter, AbrAdapter):
                print("--tier2-allowlist / --acn-conflict-scan only apply to the abr source", file=sys.stderr)
                return 2
            abns: set[str] = set()
            acns: set[str] = set()
            if args.tier2_allowlist:
                abns, acns = tier2_reference_ids(store.con)
                print(f"tier2 allowlist: {len(abns):,} ABNs, {len(acns):,} ACNs")
            if args.acn_conflict_scan:
                t0 = time.perf_counter()
                shared = AbrAdapter.shared_acn_abns(path, workers=args.workers)
                extra = {abn for group in shared.values() for abn in group}
                print(f"acn conflict scan: {len(shared):,} ACNs on 2+ ABNs, {len(extra):,} ABNs "
                      f"added ({time.perf_counter() - t0:.1f}s)")
                for acn, group in shared.items():
                    print(f"  {acn}: {', '.join(group)}")
                abns |= extra
            adapter = AbrAdapter(abn_allowlist=abns, acn_allowlist=acns)
        if args.workers and args.workers > 1 and hasattr(adapter, "run_parallel"):
            stats = adapter.run_parallel(path, snapshot, store, workers=args.workers, force=args.force)
        else:
            stats = adapter.run(path, snapshot, store, force=args.force)
    if stats.skipped_snapshot:
        print(f"{stats.source}: snapshot already ingested (same file hash), skipped")
        return 0
    print(
        f"{stats.source} {stats.snapshot_date}: in={stats.records_in} new={stats.records_new} "
        f"unchanged={stats.records_unchanged} rejected={stats.records_rejected} "
        f"top_reject={stats.top_rejection_reason or '-'} time={stats.wall_clock_s:.1f}s"
    )
    return 0


def cmd_build_canonical(args: argparse.Namespace) -> int:
    import json

    from bizgraph.pipeline.canonical import CanonicalBuilder

    with _store(args) as store:
        stats = CanonicalBuilder(store).build()
    print(json.dumps(stats.as_dict(), indent=2, default=str))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    with _store(args) as store:
        print("table counts:")
        for table, n in store.table_counts().items():
            print(f"  {table:<16} {n:>12,}")
        by_source = store.records.counts_by_source()
        if by_source:
            print("source_record by source:")
            for source, n in by_source.items():
                print(f"  {source:<16} {n:>12,}")
    return 0


def cmd_fuseki_ping(args: argparse.Namespace) -> int:
    from bizgraph.store.fuseki import FusekiClient

    client = FusekiClient(get_settings())
    if not client.ping():
        print(f"Fuseki not reachable at {client.settings.fuseki_url}", file=sys.stderr)
        return 1
    print(f"Fuseki up at {client.settings.fuseki_url}; dataset triples={client.count_triples():,}")
    return 0


# --------------------------------------------------------------------------- RDF export / publish


def _ro_store(args: argparse.Namespace):
    """Read-only DuckDB connection: export and publish never write the system of record."""
    from bizgraph.store.duckdb_store import DuckDBStore

    return DuckDBStore(args.db or get_settings().db_path, read_only=True)


def _select_graphs(exporter, args: argparse.Namespace):
    from bizgraph.rdf.exporter import NamedGraph

    kind = getattr(args, "kind", None) or "all"
    if getattr(args, "graph", None):
        wanted = set(args.graph)
        graphs = [g for g in exporter.graphs() if g.iri in wanted]
        for iri in sorted(wanted - {g.iri for g in graphs}):
            if iri.startswith("urn:graph:links:"):
                graphs.append(NamedGraph.links(iri[len("urn:graph:links:"):]))
            elif iri.startswith("urn:graph:source:"):
                src, _, d = iri[len("urn:graph:source:"):].rpartition(":")
                graphs.append(NamedGraph.source_snapshot(src, date.fromisoformat(d)))
            else:
                raise SystemExit(f"unknown graph {iri}")
        return graphs
    if kind == "source" and getattr(args, "snapshot_date", None):
        if not args.source:
            raise SystemExit("--snapshot-date needs --source")
        return [NamedGraph.source_snapshot(args.source, date.fromisoformat(args.snapshot_date))]
    if kind == "links" and getattr(args, "matcher_version", None):
        return [NamedGraph.links(args.matcher_version)]
    kinds = None if kind == "all" else [kind]
    return exporter.graphs(kinds, source=getattr(args, "source", None),
                           matcher_version=getattr(args, "matcher_version", None))


def cmd_export(args: argparse.Namespace) -> int:
    from bizgraph.rdf.exporter import RdfExporter

    settings = get_settings()
    out = Path(args.out) if args.out else settings.rdf_dir
    with _ro_store(args) as store:
        exporter = RdfExporter(store, settings.ontology_dir)
        graphs = _select_graphs(exporter, args)
        if not graphs:
            print("nothing to export", file=sys.stderr)
            return 1
        total = 0
        for g in graphs:
            r = exporter.export(g, out, "nq" if args.nquads else "nt")
            total += r.triples
            extra = " ".join(f"{k}={v:,}" for k, v in sorted(r.counts.items()))
            print(f"{g.iri:<55} {r.triples:>12,} triples {r.seconds:7.2f}s  {r.path}  {extra}")
    print(f"total {total:,} triples")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    from bizgraph.rdf.exporter import RdfExporter
    from bizgraph.rdf.publish import GraphLoader, PublishPipeline, load_report_rows, write_csv
    from bizgraph.store.fuseki import FusekiClient

    if not (args.all or args.graph):
        print("pass --all or --graph IRI", file=sys.stderr)
        return 2
    settings = get_settings()
    out = Path(args.out) if args.out else settings.rdf_dir
    client = None if args.bulk else FusekiClient(settings)
    if client is not None and not client.ping():
        print(f"Fuseki not reachable at {settings.fuseki_url}", file=sys.stderr)
        return 1
    with _ro_store(args) as store:
        exporter = RdfExporter(store, settings.ontology_dir)
        graphs = _select_graphs(exporter, args)
        pipeline = PublishPipeline(exporter, GraphLoader(client), out)
        if args.bulk:
            stats = pipeline.bulk(graphs, Path(args.tdb2_loc) if args.tdb2_loc else None)
        else:
            stats = pipeline.publish_many(graphs)
        for s in stats:
            stored = "-" if s.triples_in_store is None else f"{s.triples_in_store:,}"
            print(f"{s.graph_iri:<55} exported={s.triples_exported:>11,} stored={stored:>11} "
                  f"export={s.export_s:6.2f}s load={s.load_s:6.2f}s ({s.mode})")
        print(f"total exported={sum(s.triples_exported for s in stats):,} "
              f"wall={sum(s.export_s for s in stats) + (stats[0].load_s if args.bulk and stats else sum(s.load_s for s in stats)):.1f}s")
        if args.report and client is not None:
            rows = load_report_rows(store, client, [g for g in graphs if g.kind != "ontology"])
            path = write_csv(rows, Path(args.report))
            print(f"load report: {path}")
        if args.stats_csv:
            print(f"publish stats: {write_csv([s.as_row() for s in stats], Path(args.stats_csv))}")
    return 0


def cmd_validate_shacl(args: argparse.Namespace) -> int:
    import json

    from bizgraph.rdf.exporter import RdfExporter
    from bizgraph.rdf.publish import ShaclValidator

    settings = get_settings()
    validator = ShaclValidator(args.engine, settings.ontology_dir, java_xmx=args.xmx)
    if args.from_fuseki:
        from bizgraph.store.fuseki import FusekiClient

        client = FusekiClient(settings)
        if not args.graph:
            print("--from-fuseki needs --graph IRI (one links graph at most)", file=sys.stderr)
            return 2
        report = validator.validate_fuseki(client, args.graph, args.sample_every)
    else:
        out = Path(args.out) if args.out else settings.rdf_dir
        with _ro_store(args) as store:
            exporter = RdfExporter(store, settings.ontology_dir)
            if args.graph:
                graphs = _select_graphs(exporter, args)
            else:
                versions = exporter.matcher_versions()
                mv = args.matcher_version or (versions[-1] if versions else None)
                graphs = exporter.graphs(["source", "canonical", "derived"]) + (exporter.graphs(["links"], matcher_version=mv) if mv else [])
            files = []
            for g in graphs:
                if g.kind == "ontology":
                    continue
                path = out / f"{g.file_stem}.nt"
                if args.reexport or not path.exists():
                    path = exporter.export(g, out, "nt").path
                files.append(path)
        report = validator.validate_files(files, args.sample_every)
    summary = report.summary()
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"conforms={report.conforms} engine={report.engine} triples={report.triples_validated:,} "
          f"results={len(report.violations):,} time={report.seconds:.1f}s sampled={report.sampled}")
    for shape, n in sorted(report.by_shape().items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {n:>8,}  {shape}")
        for v in report.examples(2).get(shape, []):
            print(f"            {v.focus}  {v.message[:120]}")
    if args.quarantine:
        from bizgraph.store.duckdb_store import DuckDBStore

        with DuckDBStore(args.db or settings.db_path) as store:
            n = ShaclValidator.to_quarantine(store, report.violations)
        print(f"quarantined {n:,} rows")
    return 0 if report.conforms else 3


def _add_rdf_commands(sub) -> None:
    ex = sub.add_parser("export", help="export named graphs from DuckDB to N-Triples / N-Quads")
    ex.add_argument("kind", nargs="?", default="all", choices=["all", "source", "canonical", "links", "ontology"])
    ex.add_argument("--source", help="only this source (kind=source)")
    ex.add_argument("--snapshot-date", help="YYYY-MM-DD snapshot (default: latest per source)")
    ex.add_argument("--matcher-version", help="links graph version (default: every version)")
    ex.add_argument("--graph", action="append", help="graph IRI (repeatable), overrides kind")
    ex.add_argument("--out", help="output directory (default data/rdf)")
    ex.add_argument("--nquads", action="store_true", help="write .nq (graph on every line)")
    ex.set_defaults(func=cmd_export)

    pub = sub.add_parser("publish", help="export and load named graphs into Fuseki")
    pub.add_argument("--all", action="store_true", help="every graph: ontology, sources, canonical, links")
    pub.add_argument("--graph", action="append", help="graph IRI (repeatable)")
    pub.add_argument("--bulk", action="store_true",
                     help="offline tdb2.tdbloader via scripts/bulk_load.sh (Fuseki must be stopped)")
    pub.add_argument("--tdb2-loc", help="TDB2 directory for --bulk (default data/tdb2)")
    pub.add_argument("--out", help="export directory (default data/rdf)")
    pub.add_argument("--report", help="write outputs/load_report.csv style rows (needs Fuseki)")
    pub.add_argument("--stats-csv", help="write per-graph publish stats CSV")
    pub.set_defaults(func=cmd_publish, kind="all")

    sh = sub.add_parser("validate-shacl", help="validate exported graphs against ontology/shapes.ttl")
    sh.add_argument("--engine", choices=["jena", "pyshacl"], default="jena")
    sh.add_argument("--graph", action="append", help="graph IRI (repeatable); default sources + canonical + latest links")
    sh.add_argument("--matcher-version", help="links graph to validate with (default: latest)")
    sh.add_argument("--sample-every", type=int, help="keep 1 in N subjects (plus all rdf:type triples)")
    sh.add_argument("--from-fuseki", action="store_true", help="CONSTRUCT the graphs from Fuseki instead")
    sh.add_argument("--reexport", action="store_true", help="re-export even if the .nt file exists")
    sh.add_argument("--out", help="export directory (default data/rdf)")
    sh.add_argument("--json", help="write the summary (counts by shape, examples) as JSON")
    sh.add_argument("--quarantine", action="store_true", help="write violations into the quarantine table")
    sh.add_argument("--xmx", default="4g", help="Jena heap (default 4g)")
    sh.set_defaults(func=cmd_validate_shacl, kind="all")


# --------------------------------------------------------------------------- query services


def _service_store(args: argparse.Namespace):
    """Read-only DuckDB for the services, or None with --no-db (or when it cannot be opened)."""
    if getattr(args, "no_db", False):
        return None
    try:
        return _ro_store(args)
    except Exception as exc:  # noqa: BLE001 (a locked or missing DB downgrades, it does not fail)
        print(f"note: DuckDB not available ({exc}); tabular predicates are disabled", file=sys.stderr)
        return None


def _json_out(obj, path: str | None) -> None:
    import json

    text = json.dumps(obj, indent=2, default=str, ensure_ascii=False)
    if path:
        Path(path).write_text(text, encoding="utf-8")
        print(f"wrote {path}")
    else:
        print(text)


def cmd_ultimate_parent(args: argparse.Namespace) -> int:
    from bizgraph.services.traversal import TraversalService
    from bizgraph.store.fuseki import FusekiClient

    svc = TraversalService(FusekiClient(get_settings()), matcher_version=args.matcher_version)
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    chain = svc.ultimate_parent(args.key, as_of=as_of, max_depth=args.max_depth)
    print(chain.summary())
    for e in chain.edges:
        pct = f" {e.percentage}%" if e.percentage is not None else ""
        print(f"  {e.child} -[{e.kind}{pct} {e.valid_from or ''}..{e.valid_to or ''} rule={e.rule}]-> {e.parent}")
        print(f"      fact {e.fact} in {e.source_graph}")
    for e in chain.ambiguous_parents:
        print(f"  ambiguous parent: {e.parent} ({e.percentage}%) via {e.fact}")
    print(f"GLEIF ultimate: {[n.short() for n in chain.gleif_ultimate]} -> {chain.gleif_check}")
    print(f"links graph: {chain.links_graph}; {chain.queries} queries, {chain.elapsed_ms:.0f} ms")
    if args.json:
        _json_out(chain.as_dict(), args.json)
    return 0 if chain.status != "NOT_FOUND" else 1


def cmd_entity(args: argparse.Namespace) -> int:
    from bizgraph.services.traversal import TraversalBudget, TraversalService
    from bizgraph.store.fuseki import FusekiClient

    svc = TraversalService(FusekiClient(get_settings()), matcher_version=args.matcher_version)
    budget = TraversalBudget()
    for item in args.cap or []:
        name, _, n = item.partition("=")
        budget.per_fact_type[name] = int(n)
    view = svc.entity_view(args.key, budget, as_of=date.fromisoformat(args.as_of) if args.as_of else None)
    if view is None:
        print(f"not found: {args.key}", file=sys.stderr)
        return 1
    if args.json:
        _json_out(view.as_dict(), args.json if args.json != "-" else None)
        return 0
    p = view.party
    print(f"{p.name} [{p.key}] ({p.kind}, attribution={p.attribution}) links graph={view.links_graph}")
    print("identifiers: " + ", ".join(f"{i['scheme']}={i['value']}" for i in view.identifiers))
    print("source records:")
    for r in view.source_records:
        print(f"  {r['record']} ({r['source']}, {r['joined_by']}) {r.get('name') or ''}")
    for cat, items in view.facts_by_type.items():
        print(f"{cat} ({view.totals.get(cat, len(items))}):")
        for f in items:
            d = f.detail
            what = d.get("licence_kind") and f"{d['licence_kind']} {d.get('licence_number')}" or f.other_name or f.other or ""
            print(f"  {'active ' if f.active else 'history'} {f.valid_from or ''}..{f.valid_to or ''} {what} "
                  f"[{f.attribution}] {f.fact}")
    print(f"truncated: {view.truncation_note()} ({view.elapsed_ms:.0f} ms)")
    return 0


def cmd_project(args: argparse.Namespace) -> int:
    from bizgraph.services.projection import NAMED_SPECS, ProjectionService, load_spec, write_projection
    from bizgraph.store.fuseki import FusekiClient

    if args.list:
        for name, spec in NAMED_SPECS.items():
            print(f"{name}: {spec['description']}")
        return 0
    if not args.spec:
        print("give a spec file or a named spec (--list)", file=sys.stderr)
        return 2
    spec = load_spec(args.spec, date.fromisoformat(args.as_of) if args.as_of else None)
    store = _service_store(args)
    try:
        svc = ProjectionService(FusekiClient(get_settings()), store, matcher_version=args.matcher_version)
        if args.explain:
            print(svc.plan(spec).explain())
            return 0
        df = svc.project(spec)
    finally:
        if store is not None:
            store.con.close()
    print(f"{len(df)} rows ({svc.last_run.get('elapsed_ms', 0):.0f} ms, links graph {svc.links_graph})")
    if args.out:
        print(f"wrote {write_projection(df, args.out)}")
    else:
        print(df.head(args.head).to_string(index=False))
    return 0


def _add_service_commands(sub) -> None:
    up = sub.add_parser("ultimate-parent", help="bounded ultimate-parent walk (LEI, ABN, ACN or IRI)")
    up.add_argument("key")
    up.add_argument("--as-of", help="YYYY-MM-DD validity date (default: today, current relationships only)")
    up.add_argument("--max-depth", type=int, default=10)
    up.add_argument("--matcher-version", help="links graph to use (default: latest loaded)")
    up.add_argument("--json", help="also write the chain as JSON to this path")
    up.set_defaults(func=cmd_ultimate_parent)

    en = sub.add_parser("entity", help="entity view: identifiers, records, licences, bans, parents, subsidiaries")
    en.add_argument("key")
    en.add_argument("--as-of", help="YYYY-MM-DD (ranks active facts first)")
    en.add_argument("--cap", action="append", help="per fact-type cap, e.g. --cap subsidiaries=50 (repeatable)")
    en.add_argument("--matcher-version")
    en.add_argument("--json", help="write the view as JSON ('-' for stdout)")
    en.set_defaults(func=cmd_entity)

    pr = sub.add_parser("project", help="run a CriteriaSpec (JSON file or named spec) into a dataset")
    pr.add_argument("spec", nargs="?", help="spec.json or a named spec (see --list)")
    pr.add_argument("--list", action="store_true", help="list named specs")
    pr.add_argument("--as-of", help="override the spec's as_of date")
    pr.add_argument("--out", help="write CSV or Parquet (by extension)")
    pr.add_argument("--explain", action="store_true", help="print the plan (SPARQL and SQL) and exit")
    pr.add_argument("--matcher-version")
    pr.add_argument("--no-db", action="store_true", help="do not open DuckDB (graph predicates only)")
    pr.add_argument("--head", type=int, default=20)
    pr.set_defaults(func=cmd_project)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bizgraph", description="AU/NZ business graph tooling")
    p.add_argument("--db", help="DuckDB file (default: settings.db_path / BIZGRAPH_DB)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create the DuckDB schema").set_defaults(func=cmd_init_db)

    ing = sub.add_parser("ingest", help="ingest one source file")
    ing.add_argument("source_id")
    ing.add_argument("path")
    ing.add_argument("--snapshot-date", help="YYYY-MM-DD (default: today)")
    ing.add_argument("--workers", type=int, default=1,
                     help="parallel parse processes (sources with run_parallel, e.g. abr: one per XML member)")
    ing.add_argument("--acn-conflict-scan", action="store_true",
                     help="abr only: first scan the full extract for ACNs on 2+ ABNs and keep all of them")
    ing.add_argument("--tier2-allowlist", action="store_true",
                     help="abr only: also keep every ABN/ACN referenced by loaded Tier 2 sources")
    ing.add_argument("--force", action="store_true",
                     help="re-ingest even if this file hash was already loaded (refreshes derived fields)")
    ing.set_defaults(func=cmd_ingest)

    sub.add_parser(
        "build-canonical", help="rebuild party_canonical, identifier, alias and identity quarantine"
    ).set_defaults(func=cmd_build_canonical)

    sub.add_parser("stats", help="row counts per table and per source").set_defaults(func=cmd_stats)
    sub.add_parser("fuseki-ping", help="check Fuseki is reachable").set_defaults(func=cmd_fuseki_ping)
    _add_rdf_commands(sub)
    _add_service_commands(sub)
    from bizgraph.resolution.cli_commands import add_resolution_commands

    add_resolution_commands(sub)
    from bizgraph.evaluation.cli_commands import add_evaluation_commands

    add_evaluation_commands(sub)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
