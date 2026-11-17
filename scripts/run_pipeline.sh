#!/usr/bin/env bash
# Full pipeline from a clean checkout plus the raw files under data/raw/:
#   ingest every source, build the canonical tables, licence history, match-all, publish.
# Every step is idempotent (file hashes short-circuit identical re-ingests; derived tables are
# rebuilt; a matcher version replaces its own rows). Per-step wall-clock goes to
# data/logs/pipeline_<timestamp>.tsv and each step's output to data/logs/pipeline_<timestamp>.log.
#
# Usage: scripts/run_pipeline.sh [--skip-publish] [--skip-abr]
# Env:   BIZGRAPH (default: .venv python -m bizgraph.cli), BIZGRAPH_DB, ABR_WORKERS (default 4),
#        BIZGRAPH_DUCKDB_MEMORY (default 5GB), BIZGRAPH_DUCKDB_THREADS (default 4)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

SKIP_PUBLISH=0
SKIP_ABR=0
for a in "$@"; do
  case "$a" in
    --skip-publish) SKIP_PUBLISH=1 ;;
    --skip-abr) SKIP_ABR=1 ;;
    *) echo "unknown option $a" >&2; exit 2 ;;
  esac
done

if [ -z "${BIZGRAPH:-}" ]; then
  if [ -x .venv/Scripts/python ]; then PY=.venv/Scripts/python; else PY=.venv/bin/python; fi
  BIZGRAPH="$PY -m bizgraph.cli"
fi
RAW=data/raw
mkdir -p data/logs
TS=$(date +%Y%m%d_%H%M%S)
LOG=data/logs/pipeline_${TS}.log
TSV=data/logs/pipeline_${TS}.tsv
printf 'step\tseconds\tstatus\n' > "$TSV"

step() {  # step <name> <command...>
  local name="$1"; shift
  local t0 t1 status=ok
  t0=$(date +%s.%N)
  echo "=== $name: $*" | tee -a "$LOG"
  if ! "$@" >>"$LOG" 2>&1; then status=FAILED; fi
  t1=$(date +%s.%N)
  printf '%s\t%s\t%s\n' "$name" "$(awk -v a="$t0" -v b="$t1" 'BEGIN { printf "%.1f", b - a }')" "$status" | tee -a "$TSV"
  [ "$status" = ok ] || { echo "step $name failed, see $LOG" >&2; exit 1; }
}

wb_date() {  # afs_lic_202511__wb20251129.csv -> 2025-11-29
  local d; d=$(basename "$1" | sed -E 's/.*__(wb|asof)([0-9]{8}).*/\2/')
  echo "${d:0:4}-${d:4:2}-${d:6:2}"
}

step init-db $BIZGRAPH init-db

# Tier 1 company register first (canonical build reads it), then Tier 2 (the ABR slice keeps every
# ABN / ACN a Tier 2 source references), then ABR.
step ingest-asic_company $BIZGRAPH ingest asic_company "$RAW/asic_company/company_202611.zip" --snapshot-date 2026-11-09

# AFSL / credit: archived captures in date order, then the current files at their CKAN
# last_modified dates (outputs/sources.md), so the current file never collides with a capture.
for f in "$RAW"/asic_afsl/history/*.csv; do
  step "ingest-asic_afsl-$(basename "$f" .csv)" $BIZGRAPH ingest asic_afsl "$f" --snapshot-date "$(wb_date "$f")"
done
step ingest-asic_afsl-current $BIZGRAPH ingest asic_afsl "$RAW/asic_afsl/afs_lic_202611.csv" --snapshot-date 2026-11-11
for f in "$RAW"/asic_credit/history/*.csv; do
  step "ingest-asic_credit-$(basename "$f" .csv)" $BIZGRAPH ingest asic_credit "$f" --snapshot-date "$(wb_date "$f")"
done
step ingest-asic_credit-current $BIZGRAPH ingest asic_credit "$RAW/asic_credit/credit_lic_202611.csv" --snapshot-date 2026-11-15

step ingest-asic_banned_org $BIZGRAPH ingest asic_banned_org "$RAW/asic_banned_org/bd_org_202611.csv" --snapshot-date 2026-11-09
step ingest-asic_liquidator $BIZGRAPH ingest asic_liquidator "$RAW/asic_liquidator/liquidator_202611.csv" --snapshot-date 2026-11-09
step ingest-gleif_l1 $BIZGRAPH ingest gleif_l1 "$RAW/gleif_l1/20261116-gleif-lei2-au-nz.csv" --snapshot-date 2026-11-16
step ingest-gleif_l2 $BIZGRAPH ingest gleif_l2 "$RAW/gleif_l2/20261116-gleif-rr-au-nz.csv" --snapshot-date 2026-11-16
step ingest-accc_notice $BIZGRAPH ingest accc_notice "$RAW/accc_notice/extract_20261117.txt" --snapshot-date 2026-11-17

if [ "$SKIP_ABR" = 0 ]; then
  step ingest-abr $BIZGRAPH ingest abr "$RAW/abr" --snapshot-date 2026-11-11 \
    --workers "${ABR_WORKERS:-4}" --tier2-allowlist --acn-conflict-scan
fi

step build-canonical $BIZGRAPH build-canonical
step licence-events $BIZGRAPH licence-events
step match-all $BIZGRAPH match-all

if [ "$SKIP_PUBLISH" = 0 ]; then
  step fuseki-ping $BIZGRAPH fuseki-ping
  step publish $BIZGRAPH publish --all
fi
echo "done: $TSV"
