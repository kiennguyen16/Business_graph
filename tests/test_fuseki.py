"""Integration test: needs a running Fuseki (scripts/fuseki.sh). Skipped otherwise."""

from __future__ import annotations

from pathlib import Path

import pytest

from bizgraph.config import get_settings
from bizgraph.store.fuseki import FusekiClient

client = FusekiClient(get_settings())
pytestmark = pytest.mark.skipif(not client.ping(), reason="Fuseki not reachable")

GRAPH = "urn:graph:test:pytest"
NT = (
    '<urn:test:a> <http://www.w3.org/2000/01/rdf-schema#label> "Alpha" .\n'
    '<urn:test:a> <urn:test:score> "42"^^<http://www.w3.org/2001/XMLSchema#integer> .\n'
    '<urn:test:b> <http://www.w3.org/2000/01/rdf-schema#label> "Beta" .\n'
)


def test_graph_lifecycle(tmp_path: Path) -> None:
    f = tmp_path / "t.nt"
    f.write_text(NT, encoding="utf-8")
    try:
        client.put_graph(GRAPH, f, "application/n-triples")
        client.put_graph(GRAPH, f, "application/n-triples")  # replace, not append
        assert client.count_triples(GRAPH) == 3

        # default graph is the union of named graphs
        rows = client.query("SELECT ?s ?n WHERE { ?s <urn:test:score> ?n }")
        assert rows == [{"s": "urn:test:a", "n": 42}]
        assert client.ask("ASK { <urn:test:b> ?p ?o }")
        assert "Alpha" in client.construct(
            f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{GRAPH}> {{ ?s ?p ?o }} }}"
        )

        client.update(f'INSERT DATA {{ GRAPH <{GRAPH}> {{ <urn:test:c> <urn:test:p> "x" }} }}')
        assert client.count_triples(GRAPH) == 4
    finally:
        client.delete_graph(GRAPH)
    assert client.count_triples(GRAPH) == 0
    client.delete_graph(GRAPH)  # deleting a missing graph is fine
