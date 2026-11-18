"""Independent contract tests for FusekiClient, config.ttl semantics, and the shell scripts.

Runs against the Fuseki at FUSEKI_URL (set it to a throwaway server, e.g. http://localhost:3099,
started with a copy of fuseki/config.ttl pointing at a temp TDB2 location). Skipped if unreachable.
Graph IRIs are namespaced under urn:graph:indeptest: and removed afterwards.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import date
from pathlib import Path

import pytest

from bizgraph.config import Settings
from bizgraph.store.fuseki import FusekiClient, FusekiError, _convert

REPO = Path(__file__).resolve().parents[2]
client = FusekiClient(Settings())
live = pytest.mark.skipif(not client.ping(), reason=f"Fuseki not reachable at {client.settings.fuseki_url}")

G1 = "urn:graph:indeptest:one"
G2 = "urn:graph:indeptest:two"
XSD = "http://www.w3.org/2001/XMLSchema#"


def _nt(path: Path, lines: list[str]) -> Path:
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return path


@pytest.fixture()
def cleanup():
    yield
    for g in (G1, G2):
        client.delete_graph(g)


# ---------------------------------------------------------------- pure unit: _convert


def test_convert_types() -> None:
    assert _convert({"type": "literal", "value": "7", "datatype": f"{XSD}integer"}) == 7
    assert _convert({"type": "literal", "value": "2020-01-02", "datatype": f"{XSD}date"}) == date(2020, 1, 2)
    assert _convert({"type": "literal", "value": "2020-01-02Z", "datatype": f"{XSD}date"}) == date(2020, 1, 2)
    assert _convert({"type": "uri", "value": "urn:x"}) == "urn:x"
    assert _convert({"type": "literal", "value": "Café", "xml:lang": "fr"}) == "Café"
    assert _convert({"type": "literal", "value": "abc", "datatype": f"{XSD}integer"}) == "abc"


def test_convert_boolean_lexical_one() -> None:
    """xsd:boolean lexical space is {true, false, 1, 0}; '1' must be True."""
    assert _convert({"type": "literal", "value": "1", "datatype": f"{XSD}boolean"}) is True


def test_convert_other_integer_subtypes() -> None:
    """COUNT/SUM return xsd:integer, but exported data may use xsd:unsignedInt / xsd:byte / xsd:gYear."""
    assert _convert({"type": "literal", "value": "5", "datatype": f"{XSD}unsignedInt"}) == 5


# ---------------------------------------------------------------- live server


@live
def test_put_same_graph_twice_same_count(tmp_path: Path, cleanup) -> None:
    f = _nt(tmp_path / "a.nt", [f"<urn:s:{i}> <urn:p> \"v{i}\" ." for i in range(100)])
    client.put_graph(G1, f)
    client.put_graph(G1, f)
    assert client.count_triples(G1) == 100


@live
def test_put_different_file_fully_replaces(tmp_path: Path, cleanup) -> None:
    client.put_graph(G1, _nt(tmp_path / "a.nt", ["<urn:old> <urn:p> \"old\" ."]))
    client.put_graph(G1, _nt(tmp_path / "b.nt", ["<urn:new> <urn:p> \"new\" .", "<urn:new> <urn:q> \"1\" ."]))
    assert client.count_triples(G1) == 2
    assert not client.ask(f"ASK {{ GRAPH <{G1}> {{ <urn:old> ?p ?o }} }}")
    assert not client.ask("ASK { <urn:old> ?p ?o }")


@live
def test_put_turtle_by_suffix(tmp_path: Path, cleanup) -> None:
    f = tmp_path / "a.ttl"
    f.write_text("@prefix ex: <urn:ex:> .\nex:a ex:p \"Café\"@fr , 3 .\n", encoding="utf-8")
    client.put_graph(G1, f)
    assert client.count_triples(G1) == 2


@live
def test_put_empty_file_empties_graph(tmp_path: Path, cleanup) -> None:
    client.put_graph(G1, _nt(tmp_path / "a.nt", ["<urn:a> <urn:p> \"1\" ."]))
    client.put_graph(G1, _nt(tmp_path / "e.nt", []))
    assert client.count_triples(G1) == 0


@live
def test_put_malformed_raises_and_keeps_old(tmp_path: Path, cleanup) -> None:
    client.put_graph(G1, _nt(tmp_path / "a.nt", ["<urn:a> <urn:p> \"1\" ."]))
    with pytest.raises(FusekiError):
        client.put_graph(G1, _nt(tmp_path / "bad.nt", ["<urn:b> <urn:p> \"1\" .", "this is not ntriples"]))
    assert client.count_triples(G1) == 1, "a failed PUT left a partial graph"
    assert client.ask(f"ASK {{ GRAPH <{G1}> {{ <urn:a> ?p ?o }} }}")


@live
def test_union_default_graph_sees_named_graphs(tmp_path: Path, cleanup) -> None:
    client.put_graph(G1, _nt(tmp_path / "a.nt", ["<urn:u:a> <urn:p> <urn:u:b> ."]))
    client.put_graph(G2, _nt(tmp_path / "b.nt", ["<urn:u:b> <urn:p> <urn:u:c> ."]))
    rows = client.query("SELECT ?c WHERE { <urn:u:a> <urn:p> ?b . ?b <urn:p> ?c }")
    assert rows == [{"c": "urn:u:c"}]
    before = client.count_triples()
    client.delete_graph(G2)
    assert client.count_triples() == before - 1


@live
def test_union_default_graph_duplicates_across_graphs(tmp_path: Path, cleanup) -> None:
    """Same triple in two named graphs: union default graph should dedupe (set semantics)."""
    t = ["<urn:dup:a> <urn:p> \"x\" ."]
    client.put_graph(G1, _nt(tmp_path / "a.nt", t))
    client.put_graph(G2, _nt(tmp_path / "b.nt", t))
    rows = client.query("SELECT ?o WHERE { <urn:dup:a> <urn:p> ?o }")
    assert len(rows) == 1


@live
def test_delete_missing_graph_ok() -> None:
    client.delete_graph("urn:graph:indeptest:never-existed")
    client.delete_graph("urn:graph:indeptest:never-existed")


@live
def test_count_triples_missing_graph_zero() -> None:
    assert client.count_triples("urn:graph:indeptest:never-existed") == 0


@live
def test_query_result_typing(tmp_path: Path, cleanup) -> None:
    f = _nt(
        tmp_path / "t.nt",
        [
            f'<urn:t:a> <urn:n> "42"^^<{XSD}integer> .',
            f'<urn:t:a> <urn:d> "2024-02-29"^^<{XSD}date> .',
            '<urn:t:a> <urn:l> "Café Pty Ltd"@en .',
            "<urn:t:a> <urn:i> <urn:t:b> .",
            f'<urn:t:a> <urn:f> "1.5"^^<{XSD}double> .',
            f'<urn:t:a> <urn:b> "true"^^<{XSD}boolean> .',
            "<urn:t:a> <urn:bn> _:x .",
        ],
    )
    client.put_graph(G1, f)
    rows = client.query(
        """SELECT ?n ?d ?l ?i ?f ?b ?missing WHERE {
             <urn:t:a> <urn:n> ?n ; <urn:d> ?d ; <urn:l> ?l ; <urn:i> ?i ; <urn:f> ?f ; <urn:b> ?b .
             OPTIONAL { <urn:t:a> <urn:nope> ?missing } }"""
    )
    assert rows == [
        {"n": 42, "d": date(2024, 2, 29), "l": "Café Pty Ltd", "i": "urn:t:b", "f": 1.5, "b": True}
    ]
    assert "missing" not in rows[0]
    cnt = client.query(f"SELECT (COUNT(*) AS ?c) WHERE {{ GRAPH <{G1}> {{ ?s ?p ?o }} }}")
    assert cnt == [{"c": 7}] and isinstance(cnt[0]["c"], int)


@live
def test_query_error_raises() -> None:
    with pytest.raises(FusekiError):
        client.query("SELEC broken")


@live
def test_construct_unicode(tmp_path: Path, cleanup) -> None:
    client.put_graph(G1, _nt(tmp_path / "u.nt", ['<urn:c:a> <urn:p> "株式会社 Café" .']))
    out = client.construct(f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{G1}> {{ ?s ?p ?o }} }}")
    assert "株式会社 Café" in out


@live
def test_update_and_gsp_consistent(tmp_path: Path, cleanup) -> None:
    client.update(f'INSERT DATA {{ GRAPH <{G1}> {{ <urn:x> <urn:p> "1" }} }}')
    assert client.count_triples(G1) == 1
    client.update(f"DROP SILENT GRAPH <{G1}>")
    assert client.count_triples(G1) == 0


@live
def test_large_put_200k(tmp_path: Path, cleanup, capsys) -> None:
    f = tmp_path / "big.nt"
    with f.open("w", encoding="utf-8") as fh:
        for i in range(100_000):
            fh.write(f'<urn:big:{i}> <http://www.w3.org/2000/01/rdf-schema#label> "Company {i} Pty Ltd" .\n')
            fh.write(f'<urn:big:{i}> <urn:abn> "{i:011d}" .\n')
    t0 = time.perf_counter()
    client.put_graph(G1, f)
    t1 = time.perf_counter()
    client.put_graph(G1, f)
    t2 = time.perf_counter()
    n = client.count_triples(G1)
    with capsys.disabled():
        print(f"\n[fuseki] 200k PUT {t1 - t0:.1f}s, re-PUT {t2 - t1:.1f}s, count {time.perf_counter() - t2:.1f}s")
    assert n == 200_000


# ---------------------------------------------------------------- config / scripts (static and offline)


def test_config_tdb2_location_overridable() -> None:
    """Running a second Fuseki (test, CI) needs a different TDB2 location; config.ttl hard-codes data/tdb2."""
    cfg = (REPO / "fuseki" / "config.ttl").read_text(encoding="utf-8")
    script = (REPO / "scripts" / "fuseki.sh").read_text(encoding="utf-8")
    assert "data/tdb2" not in cfg or "TDB2_LOC" in script or "FUSEKI_CONFIG" in script


def _bash() -> str | None:
    candidates = [shutil.which("bash")]
    if os.name == "nt":
        # System32 bash is the WSL launcher and cannot run the Git Bash fixtures.
        candidates = [r"C:\Program Files\Git\bin\bash.exe", shutil.which("bash.exe")]
    for c in candidates:
        if c and Path(c).exists():
            if Path(c).parent.name.lower() != "system32":
                return c
    return None


_loader_available = pytest.mark.skipif(
    _bash() is None
    or not any(
        (jdk / "bin" / name).is_file()
        for jdk in (REPO / "tools").glob("jdk-21*")
        for name in ("java", "java.exe")
    )
    or not (REPO / "tools" / "apache-jena-5.5.0" / "lib").is_dir(),
    reason="bulk loader requires Bash, the portable JDK and Apache Jena under tools/",
)


def _shell_path(path: Path) -> str:
    if os.name != "nt":
        return path.as_posix()
    return subprocess.check_output(
        [_bash(), "-c", 'cygpath -u "$1"', "_", path.as_posix()], text=True
    ).strip()


@_loader_available
@pytest.mark.parametrize("loc_style", ["relative_to_cwd", "absolute_posix"])
def test_bulk_load_into_temp_location(tmp_path: Path, loc_style: str) -> None:
    nq = tmp_path / "x.nq"
    nq.write_text(
        "<urn:a> <urn:p> \"1\" <urn:graph:bl:one> .\n<urn:b> <urn:p> \"2\" <urn:graph:bl:two> .\n", encoding="utf-8"
    )
    work = tmp_path / "work"
    work.mkdir()
    posix_tmp = _shell_path(tmp_path)
    if loc_style == "relative_to_cwd":
        loc_env, expected = "tdb2rel", tmp_path / "tdb2rel"  # relative to the caller cwd (tmp_path)
    else:
        loc_env, expected = f"{posix_tmp}/tdb2abs", tmp_path / "tdb2abs"
    env = {**os.environ, "TDB2_LOC": loc_env, "LOADER_XMX": "512m"}
    r = subprocess.run(
        [_bash(), (REPO / "scripts" / "bulk_load.sh").as_posix(), "x.nq"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300,
    )
    stray = REPO / loc_env if loc_style == "relative_to_cwd" else None
    try:
        assert r.returncode == 0, r.stderr[-2000:]
        assert expected.exists() and any(expected.iterdir()), (
            f"TDB2 not created at {expected}; stray at repo: {stray and stray.exists()}"
        )
    finally:
        if stray and stray.exists():
            shutil.rmtree(stray, ignore_errors=True)
        weird = Path("C:/c") if loc_style == "absolute_posix" else None
        if weird and weird.exists() and (weird / "Users").exists():
            pass  # reported, not removed (outside test scope)


@_loader_available
def test_bulk_load_triples_without_graph_is_refused(tmp_path: Path) -> None:
    """config.ttl sets tdb2:unionDefaultGraph true, so triples in the stored default graph would be
    invisible to plain queries. Contract: bulk_load.sh refuses triple formats without --graph."""
    nt = tmp_path / "x.nt"
    nt.write_text('<urn:a> <urn:p> "1" .\n', encoding="utf-8")
    loc = tmp_path / "tdb2none"
    env = {**os.environ, "TDB2_LOC": "tdb2none", "LOADER_XMX": "512m"}
    r = subprocess.run(
        [_bash(), (REPO / "scripts" / "bulk_load.sh").as_posix(), "x.nt"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300,
    )
    assert r.returncode != 0
    assert "--graph" in r.stderr
    assert not loc.exists()


@_loader_available
def test_bulk_load_with_graph_flag(tmp_path: Path) -> None:
    nt = tmp_path / "x.nt"
    nt.write_text('<urn:a> <urn:p> "1" .\n', encoding="utf-8")
    loc = tmp_path / "tdb2g"
    posix = _shell_path(loc)
    env = {**os.environ, "TDB2_LOC": posix, "LOADER_XMX": "512m"}
    r = subprocess.run(
        [_bash(), (REPO / "scripts" / "bulk_load.sh").as_posix(), "--graph", "urn:graph:bl:g", "x.nt"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    assert loc.exists() and any(loc.iterdir())
