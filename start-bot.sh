#!/bin/bash
# Start Realtor Bot with lock file protection

LOCK_FILE="/tmp/realtor-bot.lock"
BOT_DIR="/data/.openclaw/workspace/realtor-bot"
LOG_FILE="$BOT_DIR/bot.log"

# Check if already running
if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "❌ Bot already running (PID: $PID)"
        exit 1
    else
        echo "⚠️ Stale lock file found, removing..."
        rm -f "$LOCK_FILE"
    fi
fi

# Start bot
cd "$BOT_DIR" || exit 1
nohup python3 main.py >> "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo $NEW_PID > "$LOCK_FILE"

echo "✅ Bot started (PID: $NEW_PID)"
echo "📊 Log: tail -f $LOG_FILE"
