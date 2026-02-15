#!/bin/bash
# Setup script for Realtor Bot

echo "🚀 Настройка Realtor Bot..."

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не найден. Установите Python 3.9+"
    exit 1
fi

# Create virtual environment
echo "📦 Создаю виртуальное окружение..."
python3 -m venv venv

# Activate virtual environment
echo "🔄 Активирую окружение..."
source venv/bin/activate

# Install dependencies
echo "📥 Устанавливаю зависимости..."
pip install -r requirements.txt

# Create .env from example if not exists
if [ ! -f .env ]; then
    echo "📝 Создаю .env файл..."
    cp .env.example .env
    echo "⚠️  ВАЖНО: Отредактируйте .env и укажите TELEGRAM_BOT_TOKEN!"
fi

echo ""
echo "✅ Настройка завершена!"
echo ""
echo "Следующие шаги:"
echo "1. Отредактируйте файл .env"
echo "2. Получите токен у @BotFather"
echo "3. Запустите бота: python main.py"
echo ""
