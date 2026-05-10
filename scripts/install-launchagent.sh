#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="org.adanos.polysentiment-trader"
APP_SUPPORT="$HOME/Library/Application Support/PolySentimentTrader"
RUNTIME_DIR="$APP_SUPPORT/runtime"
LOG_DIR="$APP_SUPPORT/logs"
WRAPPER="$APP_SUPPORT/run-launchagent.sh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$APP_SUPPORT" "$RUNTIME_DIR" "$LOG_DIR" "$HOME/Library/LaunchAgents"

cat > "$WRAPPER" <<EOF
#!/bin/bash
set -euo pipefail

PROJECT_DIR="$PROJECT_DIR"
RUNTIME_DIR="$RUNTIME_DIR"
LOG_DIR="$LOG_DIR"
PID_FILE="\$RUNTIME_DIR/polysentiment-trader.pid"
TIMER_FILE="\$RUNTIME_DIR/polysentiment-trader-timer.pid"
LOGPATH_FILE="\$RUNTIME_DIR/polysentiment-trader.logpath"
LOG_FILE="\$LOG_DIR/polysentiment-trader-launchd.log"
LEDGER_FILE="\$RUNTIME_DIR/paper-portfolio.json"
ACTIONS_FILE="\$RUNTIME_DIR/latest-actions.json"
MARKETS_FILE="\$RUNTIME_DIR/considered-markets-latest.csv"
HISTORY_DIR="\$RUNTIME_DIR/history"

mkdir -p "\$RUNTIME_DIR" "\$LOG_DIR" "\$HISTORY_DIR"

printf '%s\n' "\$\$" > "\$PID_FILE"
printf '%s\n' "launchagent" > "\$TIMER_FILE"
printf '%s\n' "\$LOG_FILE" > "\$LOGPATH_FILE"

cleanup() {
  rm -f "\$PID_FILE"
  printf '%s\n' "stopped" > "\$TIMER_FILE"
}

trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM HUP

cd "\$PROJECT_DIR"
exec env PYTHONUNBUFFERED=1 "\$PROJECT_DIR/venv/bin/python" -m polysentiment_trader.cli \\
  --base-url https://api.adanos.org \\
  --loop \\
  --interval-minutes 2 \\
  --scan-limit 25 \\
  --max-positions 5 \\
  --min-price 0.25 \\
  --max-price 0.60 \\
  --min-edge 0.05 \\
  --min-confidence 0.45 \\
  --min-evidence-quality-score 0.55 \\
  --min-liquidity 10000 \\
  --min-market-trade-count 10 \\
  --min-stock-trade-count 20 \\
  --stop-loss-pct -0.12 \\
  --take-profit-pct 0.30 \\
  --max-stop-losses-per-day 1 \\
  --block-ticker-stop-losses 2 \\
  --block-ticker-stop-loss-days 7 \\
  --bankroll 1000 \\
  --ledger "\$LEDGER_FILE" \\
  --actions-out "\$ACTIONS_FILE" \\
  --markets-out "\$MARKETS_FILE" \\
  --history-dir "\$HISTORY_DIR"
EOF

chmod 755 "$WRAPPER"

mkdir -p "$PROJECT_DIR/data"
mkdir -p "$RUNTIME_DIR/history"
for name in \
  paper-portfolio.json \
  latest-actions.json \
  considered-markets-latest.csv \
  polysentiment-trader.pid \
  polysentiment-trader-timer.pid \
  polysentiment-trader.logpath
do
  src="$PROJECT_DIR/data/$name"
  dst="$RUNTIME_DIR/$name"
  if [ -L "$src" ]; then
    rm "$src"
  elif [ -f "$src" ] && [ ! -f "$dst" ]; then
    cp "$src" "$dst"
    rm "$src"
  elif [ -f "$src" ]; then
    mv "$src" "$PROJECT_DIR/data/$name.pre-launchagent-$(date +%Y%m%d-%H%M%S)"
  fi
  ln -s "$dst" "$src"
done

history_src="$PROJECT_DIR/data/history"
history_dst="$RUNTIME_DIR/history"
if [ -L "$history_src" ]; then
  rm "$history_src"
elif [ -d "$history_src" ] && [ ! -L "$history_src" ]; then
  mv "$history_src" "$PROJECT_DIR/data/history.pre-launchagent-$(date +%Y%m%d-%H%M%S)"
fi
ln -s "$history_dst" "$history_src"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "https://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$WRAPPER</string>
  </array>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>ProcessType</key>
  <string>Background</string>

  <key>StandardOutPath</key>
  <string>$LOG_DIR/polysentiment-trader-launchd.log</string>

  <key>StandardErrorPath</key>
  <string>$LOG_DIR/polysentiment-trader-launchd.log</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "Installed and started $LABEL"
echo "Runtime: $RUNTIME_DIR"
echo "Logs: $LOG_DIR"
