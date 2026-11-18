# Streamlit Community Cloud

Create app with repository `kiennguyen16/Business_graph`, branch `main`, main file `demo/app.py`, and Python `3.12`. Add secret `BIZGRAPH_BUNDLE_URL` set to the direct GitHub release asset URL placeholder: `<GitHub release asset URL>`.

The first build is typically 5 to 10 minutes because CPU PyTorch and `all-MiniLM-L6-v2` are installed. Cold start downloads and extracts the roughly 25 MB bundle, opens DuckDB read-only, builds the resolution index in memory when needed, and loads RDF only when a live graph view is explicitly requested. Example traversals and entity pages use `precomputed.pkl`; expected peak memory is under 1.5 GB.

Troubleshooting: use the direct asset URL, not a release page; keep `BIZGRAPH_MEMORY_LIMIT=1GB` and `BIZGRAPH_THREADS=2`; confirm Python 3.12; and remove `FUSEKI_URL` for Cloud mode. If the bundle is missing, verify it contains `bundle/demo.duckdb` after extraction.
