#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$PROJECT_DIR/data/polysentiment-trader.pid"
TIMER_FILE="$PROJECT_DIR/data/polysentiment-trader-timer.pid"
LOGPATH_FILE="$PROJECT_DIR/data/polysentiment-trader.logpath"
LOG_FILE="$PROJECT_DIR/logs/polysentiment-trader-service.log"

mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/logs"

printf '%s\n' "$$" > "$PID_FILE"
printf '%s\n' "service" > "$TIMER_FILE"
printf '%s\n' "$LOG_FILE" > "$LOGPATH_FILE"

child_pid=""

cleanup() {
  if [[ -n "$child_pid" ]] && kill -0 "$child_pid" 2>/dev/null; then
    kill "$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  printf '%s\n' "stopped" > "$TIMER_FILE"
}

trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM HUP

cd "$PROJECT_DIR"
env PYTHONUNBUFFERED=1 "$PROJECT_DIR/venv/bin/python" -m polysentiment_trader.cli \
  --base-url https://api.adanos.org \
  --loop \
  --interval-minutes 2 \
  --scan-limit 25 \
  --max-positions 5 \
  --min-price 0.25 \
  --max-price 0.60 \
  --min-edge 0.05 \
  --min-confidence 0.45 \
  --min-evidence-quality-score 0.55 \
  --min-liquidity 10000 \
  --min-market-trade-count 10 \
  --min-stock-trade-count 20 \
  --stop-loss-pct -0.12 \
  --take-profit-pct 0.30 \
  --max-stop-losses-per-day 1 \
  --block-ticker-stop-losses 2 \
  --block-ticker-stop-loss-days 7 \
  --bankroll 1000 \
  --ledger "$PROJECT_DIR/data/paper-portfolio.json" \
  --actions-out "$PROJECT_DIR/data/latest-actions.json" \
  --markets-out "$PROJECT_DIR/data/considered-markets-latest.csv" &
child_pid=$!
wait "$child_pid"
