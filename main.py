"""Main entry point for the Realtor Bot (refactored).

Key features:
- Async python-telegram-bot v21 Application
- Dependency Injection via `core.container.Container`
- Middleware for logging, errors, rate limiting
- Split handlers by domain (client / realtor / drive)

The user-facing logic (commands and flows) is preserved.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.config import settings
from bot.handlers import (
    start_command,
    help_command,
    cancel_command,
    register_command,
    clients_command,
    stats_command,
    client_detail_command,
    export_command,
    handle_realtor_phone,
    handle_realtor_company,
    handle_client_llm_message,
    handle_client_voice,
    drive_setup_command,
    inventory_command,
    search_inventory_command,
    folders_command,
    drive_auth_code_handler,
    button_callback,
    STATE_REALTOR_PHONE,
    STATE_REALTOR_COMPANY,
    STATE_CLIENT_COMPLETE,
)


logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """Configure application logging."""

    level = getattr(logging, (settings.log_level or "INFO").upper(), logging.INFO)

    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=level,
    )

    if settings.debug:
        logger.setLevel(logging.DEBUG)


async def on_error(update: object, context) -> None:
    """Global error handler for PTB."""

    logger.error("Unhandled error: %s", context.error, exc_info=True)


def build_application() -> Application:
    """Build and configure the telegram Application."""

    application = Application.builder().token(settings.telegram_bot_token).build()

    application.add_error_handler(on_error)

    # Realtor registration conversation
    realtor_conv = ConversationHandler(
        entry_points=[CommandHandler("register", register_command)],
        states={
            STATE_REALTOR_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_realtor_phone)
            ],
            STATE_REALTOR_COMPANY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_realtor_company)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        name="realtor_registration",
        persistent=False,
    )

    # Client conversation (LLM-powered, single state)
    client_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            STATE_CLIENT_COMPLETE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_client_llm_message),
                MessageHandler(filters.VOICE, handle_client_voice),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        name="client_llm_dialog",
        persistent=False,
    )

    application.add_handler(realtor_conv)
    application.add_handler(client_conv)

    # Realtor commands
    application.add_handler(CommandHandler("clients", clients_command))
    application.add_handler(CommandHandler("client", client_detail_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("export", export_command))

    # Common commands
    application.add_handler(CommandHandler("help", help_command))

    # Drive / inventory commands
    application.add_handler(CommandHandler("drive_setup", drive_setup_command))
    application.add_handler(CommandHandler("inventory", inventory_command))
    application.add_handler(CommandHandler("search", search_inventory_command))
    application.add_handler(CommandHandler("folders", folders_command))

    # Callback queries
    application.add_handler(CallbackQueryHandler(button_callback))

    # Drive auth code handler (lower priority than conversations)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, drive_auth_code_handler),
        group=1,
    )

    return application


def ensure_directories() -> None:
    """Ensure required directories exist."""

    Path("./data").mkdir(parents=True, exist_ok=True)
    Path("./logs").mkdir(parents=True, exist_ok=True)


def main() -> None:
    """Start the bot."""

    setup_logging()
    ensure_directories()

    logger.info("Starting Realtor Bot...")

    application = build_application()

    logger.info("🚀 Realtor Bot запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
