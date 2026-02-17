#!/bin/bash
# Monitor Realtor Bot and restart if crashed

LOCK_FILE="/tmp/realtor-bot.lock"
BOT_DIR="/data/.openclaw/workspace/realtor-bot"
LOG_FILE="$BOT_DIR/bot.log"

# Check if bot is running
check_bot() {
    if [ -f "$LOCK_FILE" ]; then
        PID=$(cat "$LOCK_FILE" 2>/dev/null)
        if [ -n "$PID" ] && ps -p "$PID" > /dev/null 2>&1; then
            return 0  # Running
        fi
    fi
    return 1  # Not running
}

# Restart bot
restart_bot() {
    echo "$(date): Bot not running, restarting..." >> "$LOG_FILE"
    cd "$BOT_DIR" || exit 1
    nohup python3 main.py >> "$LOG_FILE" 2>&1 &
    NEW_PID=$!
    echo $NEW_PID > "$LOCK_FILE"
    echo "$(date): Bot restarted (PID: $NEW_PID)" >> "$LOG_FILE"
}

# Main check
if ! check_bot; then
    restart_bot
    echo "✅ Bot was restarted"
else
    PID=$(cat "$LOCK_FILE" 2>/dev/null)
    echo "✅ Bot is running (PID: $PID)"
fi
