#!/bin/bash
# Start Realtor Bot with lock file protection and pre-flight tests

set -e  # Exit on error

LOCK_FILE="/tmp/realtor-bot.lock"
BOT_DIR="/data/.openclaw/workspace/realtor-bot"
LOG_FILE="$BOT_DIR/bot.log"

echo "🚀 Starting bot deployment..."

# Step 1: Run smoke tests
echo ""
if ! ./test-before-deploy.sh; then
    echo ""
    echo "❌ DEPLOYMENT BLOCKED: Tests failed!"
    echo "   Fix errors above before deploying."
    exit 1
fi

echo ""
echo "📋 Pre-deployment checks passed!"
echo ""

# Step 2: Check if already running
if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "❌ Bot already running (PID: $PID)"
        echo "   Use: pkill -f 'python.*main.py' && rm -f $LOCK_FILE"
        exit 1
    else
        echo "⚠️ Stale lock file found, removing..."
        rm -f "$LOCK_FILE"
    fi
fi

# Step 3: Kill any existing Python processes (clean slate)
echo "🧹 Cleaning up existing processes..."
pkill -9 -f "python.*main.py" 2>/dev/null || true
sleep 2

# Step 4: Start bot
echo "🚀 Starting bot..."
cd "$BOT_DIR" || exit 1
nohup python3 main.py >> "$LOG_FILE" 2>&1 &
NEW_PID=$!

# Step 5: Verify it started
echo "⏳ Verifying startup..."
sleep 3

if ps -p "$NEW_PID" > /dev/null 2>&1; then
    echo $NEW_PID > "$LOCK_FILE"
    echo ""
    echo "✅ Bot started successfully (PID: $NEW_PID)"
    echo "📊 Log: tail -f $LOG_FILE"
    echo ""
    echo "🔍 Last 3 log lines:"
    tail -3 "$LOG_FILE"
else
    echo ""
    echo "❌ Bot failed to start! Check logs:"
    tail -20 "$LOG_FILE"
    exit 1
fi
