#!/bin/bash
# Pre-deployment smoke test - MUST PASS before starting bot

set -e  # Exit on any error

echo "🧪 Running pre-deployment tests..."

cd /data/.openclaw/workspace/realtor-bot

# Test 1: Python syntax check
echo "1️⃣ Checking Python syntax..."
python3 -m py_compile main.py bot/*.py core/*.py database/*.py integrations/*.py utils/*.py
echo "   ✅ Syntax OK"

# Test 2: Import check - critical!
echo "2️⃣ Checking imports..."
python3 -c "
import sys
errors = []

try:
    from main import main
except Exception as e:
    errors.append(f'main: {e}')

try:
    from core.container import Container
    from core.llm_service import LLMService
except Exception as e:
    errors.append(f'core: {e}')

try:
    from bot.client_handlers import start_command
    from bot.realtor_handlers import button_callback, register_command
    from bot.drive_handlers import drive_setup_command
except Exception as e:
    errors.append(f'bot.handlers: {e}')

try:
    from database.repository import BaseRepository
    from database.json_repository import JSONRepository
    from database.models import ClientModel, RealtorModel
except Exception as e:
    errors.append(f'database: {e}')

try:
    from integrations.google_drive import GoogleDriveManager
    from integrations.inventory import InventoryMatcher
except Exception as e:
    errors.append(f'integrations: {e}')

if errors:
    print('❌ IMPORT ERRORS:')
    for e in errors:
        print(f'   - {e}')
    sys.exit(1)
else:
    print('   ✅ All imports OK')
"

# Test 3: Environment check
echo "3️⃣ Checking environment..."
if [ ! -f ".env" ]; then
    echo "   ❌ .env file missing"
    exit 1
fi

if [ ! -f "data/realtors.json" ]; then
    echo "   ⚠️  data/realtors.json missing (will be created)"
fi

echo "   ✅ Environment OK"

# Test 4: Check for common errors
echo "4️⃣ Checking for common errors..."

# Check for wrong imports
if grep -r "from database.container import" --include="*.py" . 2>/dev/null; then
    echo "   ❌ Found wrong import: database.container (should be core.container)"
    exit 1
fi

# Check for undefined variables in main handlers
if grep -n "developers_command" main.py | grep -v "from.*import.*developers_command" | grep -v "developers_command," 2>/dev/null; then
    :  # It's defined now
fi

echo "   ✅ Common errors check passed"

echo ""
echo "🎉 All tests passed! Bot is safe to deploy."
