"""Handlers facade (backward compatible).

The original code had a single large `handlers.py`. This refactor splits it into:
- `bot/client_handlers.py`
- `bot/realtor_handlers.py`
- `bot/drive_handlers.py`

This module re-exports the public handler functions and state constants so that
`main.py` can keep importing from `bot.handlers`.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.client_handlers import (
    start_command,
    handle_client_llm_message,
    handle_client_voice,
    cancel_command,
)
from bot.realtor_handlers import (
    register_command,
    clients_command,
    stats_command,
    client_detail_command,
    export_command,
    handle_realtor_phone,
    handle_realtor_company,
    button_callback,
)
from bot.drive_handlers import (
    drive_setup_command,
    drive_auth_code_handler,
    inventory_command,
    search_inventory_command,
    folders_command,
)

from bot.config import ConversationState
from core.container import Container
from core.middleware import with_middleware


# ===== Conversation state ints (python-telegram-bot requires ints) =====
STATE_REALTOR_PHONE = ConversationState.REALTOR_PHONE.value
STATE_REALTOR_COMPANY = ConversationState.REALTOR_COMPANY.value
STATE_CLIENT_COMPLETE = ConversationState.CLIENT_COMPLETE.value


@with_middleware
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command (role-aware)."""

    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return

    repo = Container.get_repository()
    is_realtor = (await repo.get_realtor(user.id)) is not None

    if is_realtor:
        text = (
            "📖 <b>Команды для риелторов:</b>\n\n"
            "/clients — Список клиентов\n"
            "/client &lt;id&gt; — Детали клиента (пример: /client 5)\n"
            "/stats — Статистика\n"
            "/export — Экспорт клиентов (скоро)\n\n"
            "🔗 <b>Интеграции:</b>\n"
            "/drive_setup — Подключить Google Drive\n"
            "/inventory — Просмотр остатков\n"
            "/search — Поиск по остаткам\n"
            "/folders — Управление папками\n\n"
            "⚙️ <b>Прочее:</b>\n"
            "/register — Регистрация (если ещё не зарегистрированы)\n"
            "/cancel — Отмена действия\n\n"
            "💡 <b>Совет:</b> Дайте клиентам ссылку на бота — они сами пройдут опрос!"
        )
    else:
        text = (
            "📖 Отправьте /start чтобы начать подбор недвижимости.\n\n"
            "Бот задаст несколько вопросов о ваших пожеланиях и передаст информацию риелтору."
        )

    await msg.reply_text(text, parse_mode="HTML")


__all__ = [
    # commands
    "start_command",
    "help_command",
    "cancel_command",
    "register_command",
    "clients_command",
    "stats_command",
    "client_detail_command",
    "export_command",
    # client conversation
    "handle_client_llm_message",
    "handle_client_voice",
    # realtor registration
    "handle_realtor_phone",
    "handle_realtor_company",
    # drive
    "drive_setup_command",
    "inventory_command",
    "search_inventory_command",
    "folders_command",
    "drive_auth_code_handler",
    # callbacks
    "button_callback",
    # states
    "STATE_REALTOR_PHONE",
    "STATE_REALTOR_COMPANY",
    "STATE_CLIENT_COMPLETE",
]
