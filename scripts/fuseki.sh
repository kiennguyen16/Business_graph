#!/usr/bin/env bash
# Start Fuseki (foreground) from the repo root with the portable JDK.
# Usage: scripts/fuseki.sh [extra fuseki-server args]
# Env:
#   FUSEKI_PORT    default 3030
#   FUSEKI_XMX     default 4g
#   FUSEKI_CONFIG  config file to use instead of fuseki/config.ttl
#   TDB2_LOC       TDB2 directory to serve instead of data/tdb2 (relative paths are
#                  resolved against the caller's cwd). A config is generated from
#                  fuseki/config.ttl into the run directory. Ignored if FUSEKI_CONFIG is set.
#   FUSEKI_BASE    run/state directory (default fuseki/run, or fuseki/run-<port> when
#                  TDB2_LOC or FUSEKI_CONFIG is set so a second instance does not clash)
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_java.sh"

PORT="${FUSEKI_PORT:-3030}"
CONFIG=""
if [ -n "${FUSEKI_CONFIG:-}" ]; then
  CONFIG="$(abs_path "$FUSEKI_CONFIG")"
elif [ -n "${TDB2_LOC:-}" ]; then
  LOC="$(abs_path "$TDB2_LOC")"
fi
if [ -n "${FUSEKI_CONFIG:-}${TDB2_LOC:-}" ]; then
  BASE_DEFAULT="fuseki/run-$PORT"
else
  BASE_DEFAULT="fuseki/run"
fi

cd "$REPO_ROOT"
export FUSEKI_BASE="${FUSEKI_BASE:-$BASE_DEFAULT}"
mkdir -p "$FUSEKI_BASE"

if [ -z "$CONFIG" ] && [ -n "${LOC:-}" ]; then
  mkdir -p "$LOC"
  CONFIG="$FUSEKI_BASE/config.generated.ttl"
  sed "s#tdb2:location \"data/tdb2\"#tdb2:location \"$(to_native "$LOC")\"#" fuseki/config.ttl > "$CONFIG"
  grep -q "$(to_native "$LOC")" "$CONFIG" || { echo "failed to rewrite tdb2:location in $CONFIG" >&2; exit 1; }
fi
if [ -z "$CONFIG" ]; then
  mkdir -p data/tdb2
  CONFIG="fuseki/config.ttl"
fi

exec "$JAVA" "-Xmx${FUSEKI_XMX:-4g}" \
  -jar "$(to_native "$FUSEKI_HOME/fuseki-server.jar")" \
  --port "$PORT" \
  --config "$(to_native "$CONFIG")" "$@"
