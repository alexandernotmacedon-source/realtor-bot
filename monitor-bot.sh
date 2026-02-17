#!/bin/bash
# Monitor Realtor Bot and restart if crashed (IMPROVED)

LOCK_FILE="/tmp/realtor-bot.lock"
BOT_DIR="/data/.openclaw/workspace/realtor-bot"
LOG_FILE="$BOT_DIR/bot.log"

# Check if bot is actually running by checking the process
check_bot_running() {
    if [ -f "$LOCK_FILE" ]; then
        PID=$(cat "$LOCK_FILE" 2>/dev/null)
        if [ -n "$PID" ] && ps -p "$PID" > /dev/null 2>&1; then
            # Double-check it's actually our bot
            if ps -p "$PID" -o cmd= | grep -q "python3 main.py"; then
                return 0  # Running
            fi
        fi
    fi
    return 1  # Not running
}

# Kill any duplicate processes
kill_duplicates() {
    local current_pid=$1
    for pid in $(pgrep -f "python.*main.py" | grep -v "^${current_pid}$"); do
        echo "$(date): Killing duplicate process $pid" >> "$LOG_FILE"
        kill -9 "$pid" 2>/dev/null
    done
}

# Main check
if check_bot_running; then
    PID=$(cat "$LOCK_FILE" 2>/dev/null)
    # Kill any duplicates just in case
    kill_duplicates "$PID"
    exit 0  # Already running, nothing to do
fi

# Not running, need to restart
echo "$(date): Bot not running, restarting..." >> "$LOG_FILE"

# Clean up any stale lock or processes
rm -f "$LOCK_FILE"
pkill -9 -f "python.*main.py" 2>/dev/null
sleep 1

# Start bot
cd "$BOT_DIR" || exit 1
nohup python3 main.py >> "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo $NEW_PID > "$LOCK_FILE"

# Wait a moment and verify
sleep 2
if ps -p "$NEW_PID" > /dev/null 2>&1; then
    echo "$(date): Bot restarted successfully (PID: $NEW_PID)" >> "$LOG_FILE"
else
    echo "$(date): FAILED to restart bot" >> "$LOG_FILE"
fi
