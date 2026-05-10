#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOURS="${1:-12}"
NEAR_MISSES="${NEAR_MISSES:-15}"
LABEL="org.adanos.polysentiment-trader-report"
APP_SUPPORT="$HOME/Library/Application Support/PolySentimentTrader"
RUNTIME_DIR="$APP_SUPPORT/runtime"
LOG_DIR="$APP_SUPPORT/logs"
REPORT_DIR="$APP_SUPPORT/reports"
TIMER="$APP_SUPPORT/run-performance-report-timer.sh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
STATUS_FILE="$RUNTIME_DIR/performance-report-timer.pid"
LOG_FILE="$LOG_DIR/performance-report-timer.log"

mkdir -p "$RUNTIME_DIR" "$LOG_DIR" "$REPORT_DIR" "$HOME/Library/LaunchAgents"

DELAY_SECONDS="$(python3 - "$HOURS" <<'PY'
import sys

hours = float(sys.argv[1])
print(max(0, int(hours * 3600)))
PY
)"

cat > "$TIMER" <<EOF
#!/bin/bash
set -euo pipefail

sleep "$DELAY_SECONDS"
cd "$PROJECT_DIR"
timestamp="\$(date +%Y%m%d-%H%M%S)"
report="$REPORT_DIR/performance-report-\${timestamp}.txt"
"$PROJECT_DIR/venv/bin/python" -m polysentiment_trader.analysis --hours "$HOURS" --near-misses "$NEAR_MISSES" > "\$report"
ln -sf "\$report" "$REPORT_DIR/performance-report-latest.txt"
EOF

chmod 755 "$TIMER"

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
    <string>$TIMER</string>
  </array>

  <key>RunAtLoad</key>
  <true/>

  <key>ProcessType</key>
  <string>Background</string>

  <key>StandardOutPath</key>
  <string>$LOG_FILE</string>

  <key>StandardErrorPath</key>
  <string>$LOG_FILE</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST"
launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

printf '%s\n' "$LABEL" > "$STATUS_FILE"
echo "Scheduled ${HOURS}h performance report"
echo "Label: $LABEL"
echo "Report dir: $REPORT_DIR"
