"""SPARQL endpoint protocol shared by the services.

The services only need ``query(sparql) -> list[dict]`` (rows as {var: python value},
unbound variables omitted), which is exactly what `FusekiClient.query` returns. The
`LocalEndpoint` runs the same SPARQL text in-process over an rdflib Dataset whose
default graph is the union of the named graphs (as `tdb2:unionDefaultGraph true` does
in Fuseki), so the same queries are exercised by the tests without a server.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any, Protocol

BG = "https://w3id.org/bizgraph/ont#"
PROV = "http://www.w3.org/ns/prov#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
XSD = "http://www.w3.org/2001/XMLSchema#"
GRAPH_CANONICAL = "urn:graph:canonical"
GRAPH_ONTOLOGY = "urn:graph:ontology"
LINKS_GRAPH_PREFIX = "urn:graph:links:"

PREFIXES = (
    f"PREFIX bg: <{BG}>\n"
    f"PREFIX prov: <{PROV}>\n"
    f"PREFIX rdf: <{RDF}>\n"
    f"PREFIX rdfs: <{RDFS}>\n"
    f"PREFIX xsd: <{XSD}>\n"
)


class SparqlEndpoint(Protocol):
    def query(self, sparql: str) -> list[dict[str, Any]]: ...


def iri_term(value: str) -> str:
    return f"<{value}>"


def values_clause(var: str, iris: Iterable[str]) -> str:
    return f"VALUES ?{var} {{ {' '.join(iri_term(i) for i in iris)} }}"


def date_lit(d: date) -> str:
    return f'"{d.isoformat()}"^^xsd:date'


def str_lit(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def local(iri: str | None) -> str | None:
    """Local name of a bg: IRI (bg:AFSL -> 'AFSL'); other values unchanged."""
    if iri is None:
        return None
    return iri[len(BG):] if isinstance(iri, str) and iri.startswith(BG) else iri


def links_graphs(endpoint: SparqlEndpoint) -> list[str]:
    rows = endpoint.query(
        PREFIXES + "SELECT DISTINCT ?g WHERE { GRAPH ?g { ?l a bg:Link } }"
    )
    return sorted(r["g"] for r in rows if str(r.get("g", "")).startswith(LINKS_GRAPH_PREFIX))


def pick_links_graph(endpoint: SparqlEndpoint, matcher_version: str | None = None,
                     store: Any = None) -> str | None:
    """The links graph to read party attributions from.

    Explicit version > the store's latest matcher version (if that graph is loaded) >
    the only links graph in the dataset > None (record-level mode). With several links
    graphs and no hint, the lexicographically last is used; the choice is reported on
    every result so it is never silent.
    """
    if matcher_version:
        return matcher_version if matcher_version.startswith("urn:") else LINKS_GRAPH_PREFIX + matcher_version
    loaded = links_graphs(endpoint)
    if not loaded:
        return None
    if store is not None:
        try:
            latest = store.matcher_versions.latest()
        except Exception:  # noqa: BLE001 (a store without the table is fine)
            latest = None
        if latest and LINKS_GRAPH_PREFIX + latest["version"] in loaded:
            return LINKS_GRAPH_PREFIX + latest["version"]
    return loaded[-1]


class LocalEndpoint:
    """rdflib Dataset with union default graph; same row format as FusekiClient.query."""

    def __init__(self) -> None:
        from rdflib import Dataset

        self.ds = Dataset(default_union=True)

    def add_ntriples(self, graph_iri: str, text: str) -> None:
        from rdflib import URIRef

        self.ds.graph(URIRef(graph_iri)).parse(data=text, format="nt")

    def add_file(self, graph_iri: str, path: Path) -> None:
        from rdflib import URIRef

        fmt = "turtle" if Path(path).suffix.lower() == ".ttl" else "nt"
        self.ds.graph(URIRef(graph_iri)).parse(str(path), format=fmt)

    def query(self, sparql: str) -> list[dict[str, Any]]:
        from rdflib import BNode, Literal, URIRef

        out: list[dict[str, Any]] = []
        res = self.ds.query(sparql)
        for row in res:
            d: dict[str, Any] = {}
            for var in res.vars:
                v = row[var]
                if v is None:
                    continue
                if isinstance(v, (URIRef, BNode)):
                    d[str(var)] = str(v)
                elif isinstance(v, Literal):
                    py = v.toPython()
                    d[str(var)] = py if not isinstance(py, Literal) else str(v)
                else:
                    d[str(var)] = v
            out.append(d)
        return out
