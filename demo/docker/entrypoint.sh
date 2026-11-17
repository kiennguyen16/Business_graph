#!/usr/bin/env bash
# Container entrypoint.
#   entrypoint.sh fuseki   run Fuseki only (docker compose "fuseki" service)
#   entrypoint.sh app      run the Streamlit demo (default). With EMBEDDED_FUSEKI=1 a Fuseki is
#                          started inside this container first (single-container hosting, e.g.
#                          Hugging Face Spaces). With FUSEKI_URL set, the bundle's graphs are
#                          loaded into that Fuseki if it is empty. Without either, the app uses
#                          the in-process rdflib endpoint.
set -euo pipefail
cd /app
MODE="${1:-app}"
FUSEKI_JAR="${FUSEKI_HOME:-/opt/fuseki}/fuseki-server.jar"
mkdir -p /data/tdb2 /data/fuseki-run

start_fuseki() {
  export FUSEKI_BASE=/data/fuseki-run
  exec_or_bg="$1"
  cmd=(java "-Xmx${FUSEKI_XMX:-1g}" -jar "$FUSEKI_JAR" --port "${FUSEKI_PORT:-3030}"
       --config /app/demo/docker/fuseki-config.ttl)
  if [ "$exec_or_bg" = "exec" ]; then exec "${cmd[@]}"; else "${cmd[@]}" > /data/fuseki.log 2>&1 & fi
}

if [ "$MODE" = "fuseki" ]; then
  start_fuseki exec
fi

if [ "${EMBEDDED_FUSEKI:-0}" = "1" ]; then
  start_fuseki bg
  export FUSEKI_URL="http://localhost:${FUSEKI_PORT:-3030}"
fi
if [ -n "${FUSEKI_URL:-}" ]; then
  python demo/load_fuseki.py --url "$FUSEKI_URL"
fi
exec streamlit run demo/app.py --server.port "${PORT:-7860}" --server.address 0.0.0.0 \
  --server.headless true --browser.gatherUsageStats false
