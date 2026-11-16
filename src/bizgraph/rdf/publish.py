"""Graph publishing: GraphLoader, ShaclValidator, PublishPipeline (ARCHITECTURE.md 2.3, 3.3).

Data flows one way, DuckDB -> files -> Fuseki. Every incremental write is a
whole-graph HTTP PUT of a file exported from one DuckDB snapshot, so a reader
never sees a half-written graph and a rerun is idempotent. The first build can
instead go through the offline TDB2 bulk loader (scripts/bulk_load.sh, Fuseki
stopped), which is several times faster for tens of millions of triples.

SHACL validation runs over the union of the source graphs, the canonical
graph, ONE links graph and the ontology (shapes.ttl explains why), either with
Jena's ``shacl`` (full data, run in the portable JDK) or pyshacl (in-process,
optionally on a deterministic sample of subjects).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import zlib
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from bizgraph.config import REPO_ROOT
from bizgraph.rdf.exporter import ExportResult, NamedGraph, RdfExporter
from bizgraph.rdf.vocab import GRAPH_ONTOLOGY, RDF_TYPE, SH

# --------------------------------------------------------------------------- tools


def find_java(repo_root: Path = REPO_ROOT) -> Path:
    """The portable JDK under tools/ (scripts/_java.sh uses the same one), else JAVA_HOME / PATH."""
    for jdk in sorted((repo_root / "tools").glob("jdk-21*")):
        for name in ("java.exe", "java"):
            if (jdk / "bin" / name).exists():
                return jdk / "bin" / name
    home = os.environ.get("JAVA_HOME")
    if home:
        for name in ("java.exe", "java"):
            if (Path(home) / "bin" / name).exists():
                return Path(home) / "bin" / name
    found = shutil.which("java")
    if not found:
        raise FileNotFoundError("no Java runtime: expected tools/jdk-21* or java on PATH")
    return Path(found)


def find_bash() -> str:
    """Git Bash on Windows (never the WSL launcher in System32), plain bash elsewhere."""
    env = os.environ.get("BIZGRAPH_BASH")
    if env:
        return env
    if os.name == "nt":
        for cand in (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe",
            Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
        ):
            if cand.exists():
                return str(cand)
    found = shutil.which("bash")
    if not found or "system32" in found.lower():
        raise FileNotFoundError("bash not found (set BIZGRAPH_BASH to Git Bash)")
    return found


def _posix(p: Path) -> str:
    return str(Path(p).resolve()).replace("\\", "/")


# --------------------------------------------------------------------------- loader


class GraphLoader:
    """Puts exported files into Fuseki/TDB2."""

    def __init__(self, fuseki: Any | None = None, repo_root: Path = REPO_ROOT) -> None:
        self.fuseki = fuseki
        self.repo_root = Path(repo_root)

    def replace(self, graph_iri: str, file: Path, content_type: str | None = None) -> None:
        """Incremental, idempotent: HTTP PUT replaces the named graph with the file's contents."""
        if self.fuseki is None:
            raise RuntimeError("GraphLoader.replace needs a FusekiClient")
        self.fuseki.put_graph(graph_iri, Path(file), content_type)

    def drop(self, graph_iri: str) -> None:
        if self.fuseki is None:
            raise RuntimeError("GraphLoader.drop needs a FusekiClient")
        self.fuseki.delete_graph(graph_iri)

    def bulk_load(self, files: Sequence[Path], tdb2_loc: Path | None = None,
                  graph: str | None = None, xmx: str | None = None) -> subprocess.CompletedProcess:
        """Offline load with tdb2.tdbloader via scripts/bulk_load.sh. Fuseki must NOT be running on
        that TDB2 location. N-Quads carry their graphs; triple formats need `graph`. Loading into a
        location that already holds a graph ADDS to it (set semantics), it does not replace it:
        use this for a first build into an empty location, PUT for reloads."""
        if not files:
            raise ValueError("no files to load")
        env = dict(os.environ)
        if tdb2_loc is not None:
            env["TDB2_LOC"] = _posix(tdb2_loc)
        if xmx:
            env["LOADER_XMX"] = xmx
        cmd = [find_bash(), _posix(self.repo_root / "scripts" / "bulk_load.sh")]
        if graph:
            cmd += ["--graph", graph]
        cmd += [_posix(f) for f in files]
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=self.repo_root)
        if proc.returncode != 0:
            raise RuntimeError(f"bulk load failed ({proc.returncode}):\n{proc.stderr[-2000:]}")
        return proc


# --------------------------------------------------------------------------- SHACL


@dataclass
class Violation:
    focus: str
    shape: str  # node shape local name, plus '/<path>' for property shapes
    component: str
    severity: str
    message: str
    path: str | None = None
    value: str | None = None


@dataclass
class ShaclReport:
    conforms: bool
    violations: list[Violation]
    engine: str
    triples_validated: int
    seconds: float
    sampled: bool = False

    def by_shape(self) -> Counter:
        return Counter(v.shape for v in self.violations)

    def by_severity(self) -> Counter:
        return Counter(v.severity for v in self.violations)

    def examples(self, per_shape: int = 3) -> dict[str, list[Violation]]:
        out: dict[str, list[Violation]] = {}
        for v in sorted(self.violations, key=lambda v: (v.shape, v.focus, v.value or "")):
            lst = out.setdefault(v.shape, [])
            if len(lst) < per_shape:
                lst.append(v)
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "conforms": self.conforms,
            "engine": self.engine,
            "triples_validated": self.triples_validated,
            "seconds": round(self.seconds, 2),
            "sampled": self.sampled,
            "results": len(self.violations),
            "by_severity": dict(self.by_severity()),
            "by_shape": dict(sorted(self.by_shape().items())),
            "examples": {k: [asdict(v) for v in vs] for k, vs in self.examples().items()},
        }


def _local(term: Any) -> str:
    s = str(term)
    for sep in ("#", "/"):
        if sep in s:
            s = s.rsplit(sep, 1)[1]
    return s


class ShaclValidator:
    """Validate exported N-Triples files (data + schema merged) against ontology/shapes.ttl.

    engine='jena': `java -cp tools/apache-jena-5.5.0/lib/* shacl.shacl validate` on one merged
    N-Triples file (the .bat / bash wrappers are bypassed: they fail under Git Bash).
    engine='pyshacl': in-process; with `sample_every=k` keeps every subject whose crc32 % k == 0
    plus every rdf:type triple, so sh:class targets on unsampled nodes still resolve. Cross-node
    uniqueness constraints only see the sample, so a sample is a smoke test, not a proof.
    """

    def __init__(self, engine: str = "jena", ontology_dir: Path | None = None,
                 repo_root: Path = REPO_ROOT, java_xmx: str = "4g") -> None:
        if engine not in ("jena", "pyshacl"):
            raise ValueError("engine must be 'jena' or 'pyshacl'")
        self.engine = engine
        self.repo_root = Path(repo_root)
        self.ontology_dir = Path(ontology_dir or self.repo_root / "ontology")
        self.shapes_path = self.ontology_dir / "shapes.ttl"
        self.java_xmx = java_xmx

    # -- data assembly ---------------------------------------------------------

    def _schema_lines(self) -> list[str]:
        exp = RdfExporter.__new__(RdfExporter)
        exp.ontology_dir = self.ontology_dir
        return [ln + " .\n" for ln in exp._ontology_triples({})]

    def merge(self, files: Iterable[Path], out: Path, sample_every: int | None = None,
              include_schema: bool = True) -> int:
        """Concatenate N-Triples files (plus the schema) into `out`; returns the triple count."""
        n = 0
        with Path(out).open("w", encoding="utf-8", newline="\n") as dst:
            if include_schema:
                lines = self._schema_lines()
                dst.writelines(lines)
                n += len(lines)
            for f in files:
                f = Path(f)
                if f.suffix.lower() != ".nt":
                    raise ValueError(f"{f}: only N-Triples (.nt) exports can be merged for validation")
                with f.open("r", encoding="utf-8") as src:
                    for line in src:
                        if not line.strip() or line.startswith("#"):
                            continue
                        if sample_every and sample_every > 1:
                            subj, _, rest = line.partition(" ")
                            if (zlib.crc32(subj.encode("utf-8")) % sample_every) != 0 and not rest.startswith(
                                RDF_TYPE
                            ):
                                continue
                        dst.write(line)
                        n += 1
        return n

    # -- validation ------------------------------------------------------------

    def validate_files(self, files: Sequence[Path], sample_every: int | None = None,
                       workdir: Path | None = None) -> ShaclReport:
        started = time.perf_counter()
        tmpdir = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="bizgraph-shacl-"))
        tmpdir.mkdir(parents=True, exist_ok=True)
        merged = tmpdir / "shacl_data.nt"
        try:
            n = self.merge(files, merged, sample_every)
            if self.engine == "jena":
                report_graph = self._run_jena(merged, tmpdir)
            else:
                report_graph = self._run_pyshacl(merged)
            violations, conforms = self._parse_report(report_graph)
        finally:
            if workdir is None:
                shutil.rmtree(tmpdir, ignore_errors=True)
        return ShaclReport(conforms, violations, self.engine, n, time.perf_counter() - started,
                           bool(sample_every and sample_every > 1))

    def validate_fuseki(self, fuseki: Any, graph_iris: Sequence[str], sample_every: int | None = None,
                        workdir: Path | None = None) -> ShaclReport:
        """Pull graphs back out of Fuseki (CONSTRUCT per graph) and validate them."""
        tmpdir = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="bizgraph-shacl-"))
        tmpdir.mkdir(parents=True, exist_ok=True)
        files = []
        for i, g in enumerate(graph_iris):
            if g == GRAPH_ONTOLOGY:
                continue  # merged from schema.ttl
            text = fuseki.construct(
                f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{g}> {{ ?s ?p ?o }} }}", accept="application/n-triples"
            )
            path = tmpdir / f"g{i}.nt"
            path.write_text(text, encoding="utf-8", newline="\n")
            files.append(path)
        try:
            return self.validate_files(files, sample_every, tmpdir / "work")
        finally:
            if workdir is None:
                shutil.rmtree(tmpdir, ignore_errors=True)

    def _run_jena(self, data: Path, tmpdir: Path):
        from rdflib import Graph

        java = find_java(self.repo_root)
        jena_lib = self.repo_root / "tools" / "apache-jena-5.5.0" / "lib"
        log4j = self.repo_root / "tools" / "apache-jena-5.5.0" / "log4j2.properties"
        cmd = [str(java), f"-Xmx{self.java_xmx}"]
        if log4j.exists():
            cmd.append(f"-Dlog4j.configurationFile={log4j.resolve().as_uri()}")
        cmd += ["-cp", f"{jena_lib}{os.sep}*", "shacl.shacl", "validate",
                "--shapes", _posix(self.shapes_path), "--data", _posix(data)]
        out = tmpdir / "report.ttl"
        with out.open("wb") as fh:
            proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE)
        if proc.returncode not in (0, 1):  # Jena returns 1 when the data does not conform
            raise RuntimeError(f"jena shacl failed ({proc.returncode}): {proc.stderr.decode('utf-8', 'replace')[-2000:]}")
        g = Graph()
        g.parse(out, format="turtle")
        return g

    def _run_pyshacl(self, data: Path):
        from pyshacl import validate
        from rdflib import Graph

        data_graph = Graph().parse(data, format="nt")
        shapes = Graph().parse(self.shapes_path, format="turtle")
        _, report, _ = validate(data_graph, shacl_graph=shapes, inference="none", advanced=True,
                                allow_warnings=True)
        return report

    def _parse_report(self, report) -> tuple[list[Violation], bool]:
        from rdflib import RDF, BNode, Graph, Namespace

        shg = Namespace(SH)
        shapes = Graph().parse(self.shapes_path, format="turtle")
        # Property shapes are blank nodes and their ids differ between the shapes file and the
        # report, so a property-shape result is mapped back by (path, constraint parameter),
        # disambiguated by sh:message when several node shapes constrain the same path.
        prop_index: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for ns, ps in shapes.subject_objects(shg.property):
            path = shapes.value(ps, shg.path)
            msg = str(shapes.value(ps, shg.message) or "")
            for pred in set(shapes.predicates(ps)):
                prop_index.setdefault((str(path), _local(pred)), []).append((_local(ns), msg))

        out = []
        for r in report.subjects(RDF.type, shg.ValidationResult):
            src = report.value(r, shg.sourceShape)
            path = report.value(r, shg.resultPath)
            component = _local(report.value(r, shg.sourceConstraintComponent))
            message = str(report.value(r, shg.resultMessage) or "")
            if src is not None and not isinstance(src, BNode):
                name = _local(src)
            else:
                param = component.removesuffix("ConstraintComponent")
                param = param[:1].lower() + param[1:]
                cands = prop_index.get((str(path), param), [])
                if len(cands) > 1:
                    cands = [c for c in cands if c[1] and c[1] == message] or cands
                names = sorted({c[0] for c in cands}) or ["anonymous"]
                name = "|".join(names)
                if path is not None:
                    name = f"{name}/{_local(path)}"
            value = report.value(r, shg.value)
            out.append(
                Violation(
                    focus=str(report.value(r, shg.focusNode)),
                    shape=name,
                    component=component,
                    severity=_local(report.value(r, shg.resultSeverity)),
                    message=message,
                    path=str(path) if path is not None else None,
                    value=str(value) if value is not None else None,
                )
            )
        conforms_vals = list(report.objects(None, shg.conforms))
        conforms = bool(conforms_vals[0].toPython()) if conforms_vals else not out
        out.sort(key=lambda v: (v.shape, v.focus, v.value or "", v.message))
        return out, conforms

    # -- quarantine --------------------------------------------------------------

    @staticmethod
    def to_quarantine(con: Any, violations: Iterable[Violation], severities: tuple[str, ...] = ("Violation",)) -> int:
        """Write violations into the DuckDB quarantine table (source, record_id, invariant, detail).
        Source records map to their (source, record_id); parties and other nodes use source
        'graph' and the node IRI as record_id. Returns rows written."""
        from urllib.parse import unquote

        con = getattr(con, "con", con)
        rows = []
        for v in violations:
            if v.severity not in severities:
                continue
            if v.focus.startswith("urn:src:"):
                source, _, rid = v.focus[len("urn:src:"):].partition(":")
                source, rid = unquote(source), unquote(rid)
            else:
                source, rid = "graph", v.focus
            detail = json.dumps({"message": v.message, "value": v.value, "path": v.path,
                                 "component": v.component}, sort_keys=True)
            rows.append([source, rid, f"shacl:{v.shape}", detail])
        if rows:
            con.executemany("INSERT INTO quarantine (source, record_id, invariant, detail) VALUES (?, ?, ?, ?)", rows)
        return len(rows)


# --------------------------------------------------------------------------- pipeline


@dataclass
class PublishStats:
    graph_iri: str
    kind: str
    file: str
    triples_exported: int
    export_s: float
    load_s: float
    triples_in_store: int | None = None
    mode: str = "put"
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total_s(self) -> float:
        return self.export_s + self.load_s

    def as_row(self) -> dict[str, Any]:
        d = asdict(self)
        d["total_s"] = round(self.total_s, 3)
        d["export_s"] = round(self.export_s, 3)
        d["load_s"] = round(self.load_s, 3)
        return d


class PublishPipeline:
    """export (DuckDB -> file) then load (PUT, or bulk N-Quads), per named graph."""

    def __init__(self, exporter: RdfExporter, loader: GraphLoader, out_dir: Path,
                 validator: ShaclValidator | None = None, count_after_load: bool = True) -> None:
        self.exporter = exporter
        self.loader = loader
        self.out_dir = Path(out_dir)
        self.validator = validator
        self.count_after_load = count_after_load

    def publish(self, graph: NamedGraph) -> PublishStats:
        """Export one graph and replace it in Fuseki with HTTP PUT."""
        if graph.kind == "ontology":
            return self.load_ontology()
        res = self.exporter.export(graph, self.out_dir, "nt")
        t = time.perf_counter()
        self.loader.replace(graph.iri, res.path)
        load_s = time.perf_counter() - t
        stored = self.loader.fuseki.count_triples(graph.iri) if self.count_after_load else None
        return PublishStats(graph.iri, graph.kind, str(res.path), res.triples, res.seconds, load_s,
                            stored, "put", res.counts)

    def load_ontology(self) -> PublishStats:
        """PUT ontology/schema.ttl as-is into urn:graph:ontology."""
        schema = self.exporter.ontology_dir / "schema.ttl"
        t = time.perf_counter()
        self.loader.replace(GRAPH_ONTOLOGY, schema, "text/turtle")
        load_s = time.perf_counter() - t
        stored = self.loader.fuseki.count_triples(GRAPH_ONTOLOGY) if self.count_after_load else None
        return PublishStats(GRAPH_ONTOLOGY, "ontology", str(schema), stored or 0, 0.0, load_s, stored, "put")

    def publish_many(self, graphs: Iterable[NamedGraph]) -> list[PublishStats]:
        return [self.publish(g) for g in graphs]

    def bulk(self, graphs: Sequence[NamedGraph], tdb2_loc: Path | None = None) -> list[PublishStats]:
        """First build: export every graph as N-Quads, then one offline tdb2.tdbloader run.
        The load time is shared, so each row carries the whole load wall-clock."""
        results: list[ExportResult] = [self.exporter.export(g, self.out_dir, "nq") for g in graphs]
        t = time.perf_counter()
        self.loader.bulk_load([r.path for r in results], tdb2_loc)
        load_s = time.perf_counter() - t
        return [
            PublishStats(r.graph.iri, r.graph.kind, str(r.path), r.triples, r.seconds, load_s, None, "bulk", r.counts)
            for r in results
        ]


# --------------------------------------------------------------------------- load report (T2.11)


def load_report_rows(con: Any, fuseki: Any, graphs: Sequence[NamedGraph]) -> list[dict[str, Any]]:
    """source, records_in, nodes_out, edges_out, records_rejected, top_rejection_reason.
    nodes_out = distinct IRI subjects in the named graph, edges_out = triples whose object is an
    IRI (both counted with SPARQL in Fuseki)."""
    con = getattr(con, "con", con)
    rows = []
    for g in graphs:
        records_in = rejected = None
        top = ""
        if g.kind == "source":
            snap = con.execute(
                """SELECT records_in, records_rejected, CAST(rejection_reasons AS VARCHAR) FROM source_snapshot
                   WHERE source = ? ORDER BY snapshot_date DESC, loaded_at DESC LIMIT 1""",
                [g.source],
            ).fetchall()
            if snap:
                records_in, rejected, reasons = snap[0]
                reasons = json.loads(reasons) if reasons else {}
                if reasons:
                    k, v = max(reasons.items(), key=lambda kv: (kv[1], kv[0]))
                    top = f"{k} ({v})"
        nodes = fuseki.query(
            f"SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ GRAPH <{g.iri}> {{ ?s ?p ?o FILTER(isIRI(?s)) }} }}"
        )
        edges = fuseki.query(
            f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{g.iri}> {{ ?s ?p ?o FILTER(isIRI(?o)) }} }}"
        )
        rows.append(
            {
                "source": g.source or g.kind,
                "graph": g.iri,
                "records_in": records_in,
                "nodes_out": int(nodes[0]["n"]) if nodes else 0,
                "edges_out": int(edges[0]["n"]) if edges else 0,
                "records_rejected": rejected,
                "top_rejection_reason": top,
            }
        )
    return rows


def write_csv(rows: Sequence[dict[str, Any]], path: Path) -> Path:
    import csv

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        if not rows:
            return path
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v) if isinstance(v, dict) else v) for k, v in r.items()})
    return path
