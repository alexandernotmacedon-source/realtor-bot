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
    ContextTypes,
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
    link_command,
    client_detail_command,
    export_command,
    developers_command,
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
from bot.drive_handlers import search_followup_handler


logger = logging.getLogger(__name__)


async def handle_client_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle client text message - wrapper that checks client_info."""
    # Skip if not a client message (will be handled by other handlers)
    if not update.effective_user:
        return
    
    # Check if this is a realtor
    from core.container import Container
    repo = Container.get_repository()
    if await repo.get_realtor(update.effective_user.id):
        return  # Let realtor handlers process
    
    # Check if client has active conversation in memory
    if "client_info" not in context.user_data:
        # Try to load from database (client might exist from previous session)
        existing_client = await repo.get_client_by_telegram_global(update.effective_user.id)
        if existing_client:
            # Restore client info from database
            context.user_data["client_info"] = {
                "telegram_id": existing_client.telegram_id,
                "telegram_username": existing_client.telegram_username,
                "name": existing_client.name,
                "realtor_id": existing_client.realtor_id,
                "budget": existing_client.budget,
                "size": existing_client.size,
                "location": existing_client.location,
                "rooms": existing_client.rooms,
                "ready_status": existing_client.ready_status,
                "notes": existing_client.notes,
                "contact": existing_client.contact,
            }
            context.user_data["conversation"] = [
                {"role": "system", "content": f"Риелтор ID: {existing_client.realtor_id}"}
            ]
            logger.info(f"Restored client {update.effective_user.id} from database after restart")
        else:
            # Not in conversation - prompt to start
            await update.effective_message.reply_text(
                "👋 Привет! Чтобы начать подбор недвижимости, отправьте /start"
            )
            return
    
    # Process as client message
    await handle_client_llm_message(update, context)


async def handle_client_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle client voice message - wrapper that checks client_info."""
    # Skip if not a client message
    if not update.effective_user:
        return
    
    # Check if this is a realtor
    from core.container import Container
    repo = Container.get_repository()
    if await repo.get_realtor(update.effective_user.id):
        return  # Let realtor handlers process
    
    # Check if client has active conversation in memory
    if "client_info" not in context.user_data:
        # Try to load from database (client might exist from previous session)
        existing_client = await repo.get_client_by_telegram_global(update.effective_user.id)
        if existing_client:
            # Restore client info from database
            context.user_data["client_info"] = {
                "telegram_id": existing_client.telegram_id,
                "telegram_username": existing_client.telegram_username,
                "name": existing_client.name,
                "realtor_id": existing_client.realtor_id,
                "budget": existing_client.budget,
                "size": existing_client.size,
                "location": existing_client.location,
                "rooms": existing_client.rooms,
                "ready_status": existing_client.ready_status,
                "notes": existing_client.notes,
                "contact": existing_client.contact,
            }
            context.user_data["conversation"] = [
                {"role": "system", "content": f"Риелтор ID: {existing_client.realtor_id}"}
            ]
            logger.info(f"Restored client {update.effective_user.id} from database after restart")
        else:
            if update.effective_message:
                await update.effective_message.reply_text(
                    "🎙 Получил голосовое сообщение!\n\n"
                    "Но сначала отправьте /start чтобы начать диалог."
                )
            return
    
    # Process as client voice
    await handle_client_voice(update, context)


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

    application.add_handler(realtor_conv)
    
    # Client /start handler (separate from conversation)
    application.add_handler(CommandHandler("start", start_command))
    
    # Client message handler (not using ConversationHandler for persistence)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_client_message),
        group=0,
    )
    application.add_handler(
        MessageHandler(filters.VOICE, handle_client_voice_message),
        group=0,
    )

    # Realtor commands
    application.add_handler(CommandHandler("clients", clients_command))
    application.add_handler(CommandHandler("client", client_detail_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("link", link_command))
    application.add_handler(CommandHandler("export", export_command))
    application.add_handler(CommandHandler("developers", developers_command))

    # Common commands
    application.add_handler(CommandHandler("help", help_command))

    # Drive / inventory commands
    application.add_handler(CommandHandler("drive_setup", drive_setup_command))
    application.add_handler(CommandHandler("inventory", inventory_command))
    application.add_handler(CommandHandler("search", search_inventory_command))
    application.add_handler(CommandHandler("folders", folders_command))

    # Callback queries
    application.add_handler(CallbackQueryHandler(button_callback))

    # Search follow-up handler (layout requests, "show more")
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, search_followup_handler),
        group=0,
    )

    # Drive auth code handler (lower priority than conversations)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, drive_auth_code_handler),
        group=1,
    )

    # Fallback handler for users not in conversation (prompt to /start)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _prompt_start_handler),
        group=2,
    )

    return application


async def _prompt_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt user to send /start if they're not in a conversation."""
    # Skip if user is in a conversation
    if context.user_data.get("client_info"):
        return
    
    # Skip if user is a realtor
    from core.container import Container
    repo = Container.get_repository()
    if update.effective_user and await repo.get_realtor(update.effective_user.id):
        return
    
    if update.effective_message:
        await update.effective_message.reply_text(
            "👋 Привет! Чтобы начать подбор недвижимости, отправьте /start"
        )


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
