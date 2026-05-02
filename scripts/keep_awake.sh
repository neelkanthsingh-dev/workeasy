#!/bin/zsh
# keep_awake.sh — Prevents macOS from sleeping
# Usage: awake-start | awake-stop | awake-status

PID_FILE="/tmp/keep_awake.pid"
LOG_FILE="/tmp/keep_awake.log"

start() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
        echo "✅ Keep-awake is already running (PID: $(cat $PID_FILE))"
        return
    fi

    # -d: prevent display sleep, -i: prevent idle sleep, -m: prevent disk sleep
    caffeinate -d -i -m > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "☕ Keep-awake started (PID: $(cat $PID_FILE)) — Mac will stay awake"
    echo "[$(date)] Started caffeinate (PID: $(cat $PID_FILE))" >> "$LOG_FILE"
}

stop() {
    if [ ! -f "$PID_FILE" ]; then
        echo "⚠️  Keep-awake is not running"
        return
    fi

    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        rm -f "$PID_FILE"
        echo "🛑 Keep-awake stopped (PID: $PID)"
        echo "[$(date)] Stopped caffeinate (PID: $PID)" >> "$LOG_FILE"
    else
        rm -f "$PID_FILE"
        echo "⚠️  Process was not running, cleaned up PID file"
    fi
}

status() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
        echo "✅ Keep-awake is RUNNING (PID: $(cat $PID_FILE))"
        echo "📄 Log: $LOG_FILE"
    else
        echo "🔴 Keep-awake is STOPPED"
        [ -f "$PID_FILE" ] && rm -f "$PID_FILE"
    fi
}

case "$1" in
    start)  start ;;
    stop)   stop ;;
    status) status ;;
    *)
        echo "Usage: awake-start | awake-stop | awake-status"
        echo "  awake-start   — Start keeping Mac awake"
        echo "  awake-stop    — Allow Mac to sleep again"
        echo "  awake-status  — Check if running"
        ;;
esac
