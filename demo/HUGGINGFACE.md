# Hugging Face Spaces deployment

Docker Spaces are paid; use Streamlit Cloud or docker compose for deployment.

This demo runs on a free CPU Space with the Docker SDK. The image includes the CPU-only
`all-MiniLM-L6-v2` sentence-transformers model, downloaded at build time, so the semantic path is
ON without a runtime model download.

## Create the Space

1. Sign in to Hugging Face and choose **New Space**.
2. Choose a unique name, visibility, **Docker** as the Space SDK, and the free CPU hardware.
3. Copy `Dockerfile`, `.dockerignore`, `pyproject.toml`, `README.md`, `src/`, `ontology/`, and
   `demo/` into the Space repository.
4. Add the 72 MB `demo/bundle`. Use Git LFS (`git lfs install`, then
   `git lfs track "demo/bundle/**"`) or publish `bizgraph_demo_bundle.tar.gz` as a GitHub release
   asset and set `BIZGRAPH_BUNDLE_URL` to its direct download URL in Space Settings > Variables.
5. Put this exact block at the top of the Space `README.md`:

```yaml
---
title: AU/NZ business graph
sdk: docker
app_port: 7860
---
```

6. Set these variables in Space Settings:

```text
BIZGRAPH_EMBEDDER=auto
BIZGRAPH_EMBEDDINGS=1
EMBEDDED_FUSEKI=1
```

Use `BIZGRAPH_BUNDLE_URL` only when the bundle is not committed. The image starts embedded Fuseki,
loads the bundle graph on first start, and serves Streamlit on port 7860.

## Build and runtime expectations

The first build usually takes 5 to 10 minutes: CPU PyTorch, the model download, and Fuseki dominate.
A sleeping Space may take about 30 seconds to wake. Keep `BIZGRAPH_MEMORY_LIMIT=1GB` if memory
pressure occurs.

## Troubleshooting

- **Model downloads at startup:** confirm the two embedding variables and that the Dockerfile model
  layer completed. The model should be under `/opt/huggingface`.
- **Bundle missing:** use a direct GitHub release asset URL, not the release page URL, or commit it
  with Git LFS. The tarball must contain `bundle/demo.duckdb` after extraction.
- **Blank or slow first page:** wait through the roughly 30 second wake-up and initial Fuseki graph
  load, then refresh.
- **Out of memory:** use the trimmed bundle, set `BIZGRAPH_MEMORY_LIMIT=1GB` and
  `BIZGRAPH_THREADS=2`, and do not build the full snapshot in the Space.
- **Fuseki errors:** retain `EMBEDDED_FUSEKI=1` so the bundled Java/Fuseki entrypoint runs.

## Verified Docker run (2026-11-18)

`docker build -t bizgraph-demo .` succeeded in 515 seconds and produced a 3.69 GB image.
The Space-style run with `EMBEDDED_FUSEKI=1` and the bundle mount returned HTTP 200 after
about 35 seconds. Embedded Fuseki loaded the bundle graphs; `docker stats --no-stream`
reported 525 MiB used with a 7.46 GiB limit. The app was healthy through its own code path.
The standalone CLI resolve command attempts to create a transient resolution index and needs
a writable database, so use the app path for the read-only Space bundle.

After signing in, upload the prepared folder with:

```powershell
.venv/Scripts/hf upload <user>/<space> deploy/hf_space . --repo-type space
```
