"""Thin Fuseki client: SPARQL query/update and Graph Store Protocol over HTTP."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import requests

from bizgraph.config import Settings, get_settings

XSD = "http://www.w3.org/2001/XMLSchema#"
_INT_TYPES = {
    f"{XSD}{t}"
    for t in (
        "integer", "int", "long", "short", "byte",
        "nonNegativeInteger", "positiveInteger", "nonPositiveInteger", "negativeInteger",
        "unsignedLong", "unsignedInt", "unsignedShort", "unsignedByte",
    )
}
_FLOAT_TYPES = {f"{XSD}{t}" for t in ("double", "float")}

CONTENT_TYPES = {
    ".nt": "application/n-triples",
    ".nq": "application/n-quads",
    ".ttl": "text/turtle",
    ".trig": "application/trig",
    ".rdf": "application/rdf+xml",
    ".jsonld": "application/ld+json",
}


class FusekiError(RuntimeError):
    pass


def _convert(term: dict[str, Any]) -> Any:
    """Turn one SPARQL JSON result term into a python value."""
    value = term.get("value")
    if term.get("type") in ("uri", "bnode"):
        return value
    dt = term.get("datatype")
    if not dt:
        return value
    try:
        if dt in _INT_TYPES:
            return int(value)
        if dt == f"{XSD}decimal":
            return Decimal(value)
        if dt in _FLOAT_TYPES:
            return float(value)
        if dt == f"{XSD}boolean":
            return value.strip() in ("true", "1")
        if dt == f"{XSD}date":
            return date.fromisoformat(value[:10])
        if dt == f"{XSD}dateTime":
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return value


class FusekiClient:
    def __init__(self, settings: Settings | None = None, timeout_s: float = 300.0) -> None:
        self.settings = settings or get_settings()
        self.timeout_s = timeout_s
        self.session = requests.Session()

    # ---- health ---------------------------------------------------------------
    def ping(self) -> bool:
        try:
            r = self.session.get(f"{self.settings.fuseki_url}/$/ping", timeout=5)
            return r.ok
        except requests.RequestException:
            return False

    # ---- SPARQL ---------------------------------------------------------------
    def _post_query(self, sparql: str, accept: str) -> requests.Response:
        r = self.session.post(
            self.settings.sparql_query_url,
            data={"query": sparql},
            headers={"Accept": accept},
            timeout=self.timeout_s,
        )
        if not r.ok:
            raise FusekiError(f"query failed ({r.status_code}): {r.text[:500]}")
        return r

    def query(self, sparql: str) -> list[dict[str, Any]]:
        """SELECT: rows as {var: python value}; unbound variables are omitted."""
        data = self._post_query(sparql, "application/sparql-results+json").json()
        return [{k: _convert(v) for k, v in b.items()} for b in data["results"]["bindings"]]

    def ask(self, sparql: str) -> bool:
        return bool(self._post_query(sparql, "application/sparql-results+json").json()["boolean"])

    def construct(self, sparql: str, accept: str = "text/turtle") -> str:
        r = self._post_query(sparql, accept)
        r.encoding = "utf-8"
        return r.text

    def update(self, sparql: str) -> None:
        r = self.session.post(
            self.settings.sparql_update_url,
            data={"update": sparql},
            timeout=self.timeout_s,
        )
        if not r.ok:
            raise FusekiError(f"update failed ({r.status_code}): {r.text[:500]}")

    # ---- Graph Store Protocol --------------------------------------------------
    def put_graph(self, graph_iri: str, file: Path, content_type: str | None = None) -> None:
        """Replace a named graph with the file's contents (streamed)."""
        file = Path(file)
        ctype = content_type or CONTENT_TYPES.get(file.suffix.lower(), "application/n-triples")
        with file.open("rb") as fh:
            r = self.session.put(
                self.settings.graph_store_url,
                params={"graph": graph_iri},
                data=fh,
                headers={"Content-Type": f"{ctype}; charset=utf-8"},
                timeout=self.timeout_s,
            )
        if not r.ok:
            raise FusekiError(f"PUT {graph_iri} failed ({r.status_code}): {r.text[:500]}")

    def delete_graph(self, graph_iri: str) -> None:
        """Drop a named graph; a missing graph is not an error."""
        r = self.session.delete(
            self.settings.graph_store_url, params={"graph": graph_iri}, timeout=self.timeout_s
        )
        if not r.ok and r.status_code != 404:
            raise FusekiError(f"DELETE {graph_iri} failed ({r.status_code}): {r.text[:500]}")

    def count_triples(self, graph_iri: str | None = None) -> int:
        """Triples in one named graph, or in the default (union) graph when graph_iri is None."""
        if graph_iri:
            q = f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{graph_iri}> {{ ?s ?p ?o }} }}"
        else:
            q = "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"
        rows = self.query(q)
        return int(rows[0]["n"]) if rows else 0
