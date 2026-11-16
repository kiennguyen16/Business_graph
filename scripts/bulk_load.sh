#!/usr/bin/env bash
# Offline bulk load RDF files into a TDB2 database with tdb2.tdbloader.
# Fuseki MUST be stopped (TDB2 allows one JVM per database).
# Usage: scripts/bulk_load.sh [--graph IRI] <files...>
#   N-Quads / TriG (.nq, .trig, optionally .gz) carry their own graphs.
#   Triple formats (.nt, .ttl, .rdf, .owl, .jsonld, ...) REQUIRE --graph IRI: the
#   dataset uses unionDefaultGraph, so the stored default graph is not queryable.
# Env:
#   TDB2_LOC    target directory (default data/tdb2 under the repo). Relative paths are
#               resolved against the caller's cwd, like the input files.
#   LOADER_XMX  default 4g
#   LOADER      tdbloader strategy (default parallel)
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_java.sh"

usage() { echo "usage: $0 [--graph IRI] <files...>" >&2; exit 2; }

GRAPH=""
files=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --graph) [ "$#" -ge 2 ] || usage; GRAPH="$2"; shift 2 ;;
    --graph=*) GRAPH="${1#--graph=}"; shift ;;
    -h|--help) usage ;;
    *) files+=("$1"); shift ;;
  esac
done
[ "${#files[@]}" -gt 0 ] || usage

args=()
for f in "${files[@]}"; do
  if [ ! -f "$f" ]; then echo "input file not found: $f" >&2; exit 2; fi
  base="${f%.gz}"
  case "${base,,}" in
    *.nq|*.trig) ;;
    *)
      if [ -z "$GRAPH" ]; then
        echo "$f is a triple format: pass --graph IRI (triples in the stored default graph are" >&2
        echo "invisible under unionDefaultGraph). N-Quads/TriG carry their own graphs." >&2
        exit 2
      fi ;;
  esac
  args+=("$(to_native "$(abs_path "$f")")")
done

if [ -n "${TDB2_LOC:-}" ]; then LOC="$(abs_path "$TDB2_LOC")"; else LOC="$REPO_ROOT/data/tdb2"; fi
mkdir -p "$LOC"

graph_arg=()
[ -n "$GRAPH" ] && graph_arg=("--graph=$GRAPH")

exec "$JAVA" "-Xmx${LOADER_XMX:-4g}" \
  "-Dlog4j.configurationFile=$(file_url "$JENA_HOME/log4j2.properties")" \
  -cp "$(to_native "$JENA_HOME/lib")/*" tdb2.tdbloader --loader="${LOADER:-parallel}" \
  --loc "$(to_native "$LOC")" "${graph_arg[@]}" "${args[@]}"
