"""Query-side services over the published graph (ARCHITECTURE.md 3.7).

* `traversal`   TraversalService: ultimate parent, N-hop neighbourhoods, group exposure,
                entity views, all bounded by a TraversalBudget.
* `projection`  ProjectionService: CriteriaSpec -> QueryPlanner -> SPARQL + DuckDB SQL ->
                one pandas DataFrame with provenance columns.
* `endpoint`    the SPARQL endpoint protocol (FusekiClient satisfies it) and an in-process
                rdflib endpoint used by tests and offline runs.
"""
