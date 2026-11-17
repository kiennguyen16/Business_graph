# Business graph demo: Streamlit app + Apache Jena Fuseki, running from the trimmed demo bundle
# (demo/bundle, built by demo/build_demo_snapshot.py). Build context is the repo root; the
# repository .dockerignore keeps data/, tools/ and .venv/ out of it.
#
#   docker build -t bizgraph-demo .
#   docker run -p 7860:7860 -e EMBEDDED_FUSEKI=1 bizgraph-demo      # one container, Fuseki inside
#   docker compose up                                                # app + separate Fuseki service
FROM python:3.12-slim-bookworm

ARG JENA_VERSION=5.5.0
RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-17-jre-headless curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL "https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-${JENA_VERSION}.tar.gz" \
    | tar -xz -C /opt \
 && ln -s "/opt/apache-jena-fuseki-${JENA_VERSION}" /opt/fuseki

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY ontology ./ontology
COPY demo ./demo

ENV PYTHONUNBUFFERED=1 \
    FUSEKI_HOME=/opt/fuseki \
    BIZGRAPH_DB=/app/demo/bundle/demo.duckdb \
    BIZGRAPH_MEMORY_LIMIT=1GB \
    PORT=7860
# Non-root user (Hugging Face Spaces runs containers as uid 1000)
RUN useradd -m -u 1000 app && mkdir -p /data && chown -R app /data /app
USER app
VOLUME ["/data"]
EXPOSE 7860 3030
ENTRYPOINT ["bash", "/app/demo/docker/entrypoint.sh"]
CMD ["app"]
