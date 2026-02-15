"""Client-facing handlers.

This module contains handlers for clients:
- /start flow (routes realtor vs client)
- LLM-powered dialog (text + voice)
- Conversation completion and lead creation

All handlers are async and designed for python-telegram-bot v21.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from typing import Any, Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.config import MessageTemplates
from core.container import Container
from core.middleware import with_middleware
from database.models import ClientModel
from utils.helpers import sanitize_user_text


logger = logging.getLogger(__name__)


# Fallback structured questionnaire when LLM is unavailable.
_QUESTIONNAIRE: list[tuple[str, str]] = [
    (
        "budget",
        "Какой у вас бюджет? 💰\n\nНапишите сумму в лари (GEL):\n• до 150 000\n• 100-200 тысяч\n• от 200 000",
    ),
    (
        "size",
        "Какая минимальная площадь вас интересует? 📐\n\nУкажите в м²:\n• от 50\n• 60-80\n• минимум 70",
    ),
    (
        "location",
        "Какой район Батуми вы рассматриваете? 🗺\n\nПримеры: Старый Батуми, Новый бульвар, Махинджаури, Гонио, Кобулети.",
    ),
    (
        "rooms",
        "Сколько комнат нужно? 🛏\n\n• Студия\n• 1 спальня\n• 2 спальни\n• 3 спальни\n• 4+ спальни",
    ),
    (
        "ready_status",
        "Какая стадия строительства вас интересует? 🏗\n\n• Готовое\n• Строящееся (white/black frame)\n• Котлован\n• Рассмотрю всё",
    ),
    (
        "contact",
        "Как с вами связаться? 📞\n\nОтправьте телефон или ник в Telegram/WhatsApp:\n• +995 XXX XXX XXX\n• @username",
    ),
    (
        "notes",
        "Дополнительные пожелания? 📝\n\nНапример: этаж, вид, паркинг, расстояние до моря.\nИли напишите «нет».",
    ),
]


async def _is_realtor(user_id: int) -> bool:
    repo = Container.get_repository()
    return (await repo.get_realtor(user_id)) is not None


async def _get_default_realtor() -> Optional[Any]:
    """Get assigned realtor for client.

    текущая логика MVP: первый активный риелтор.
    """
    repo = Container.get_repository()
    realtors = await repo.get_all_realtors()
    for r in realtors:
        if r.is_active:
            return r
    return None


def _question_step_index(user_data: dict) -> int:
    """Get current questionnaire step index."""
    return int(user_data.get("question_step_index", 0))


def _set_question_step_index(user_data: dict, index: int) -> None:
    user_data["question_step_index"] = index
    user_data["questionnaire_mode"] = True


def _get_current_question(user_data: dict) -> Optional[tuple[str, str]]:
    idx = _question_step_index(user_data)
    if 0 <= idx < len(_QUESTIONNAIRE):
        return _QUESTIONNAIRE[idx]
    return None


async def _ask_current_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = _get_current_question(context.user_data)
    if not q:
        return
    _, text = q
    if update.effective_message:
        await update.effective_message.reply_text(text)


async def _handle_questionnaire_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, answer: str) -> int:
    """Handle structured questionnaire answer; complete when finished."""

    q = _get_current_question(context.user_data)
    if not q:
        return await _complete_client_conversation(update, context)

    field, _ = q

    value = sanitize_user_text(answer, max_len=500)
    if field == "notes" and value.lower() in {"нет", "no", "-"}:
        value = ""

    context.user_data.setdefault("client_info", {})[field] = value

    # Next question
    _set_question_step_index(context.user_data, _question_step_index(context.user_data) + 1)

    if _get_current_question(context.user_data) is None:
        return await _complete_client_conversation(update, context)

    await _ask_current_question(update, context)
    return 8


async def _notify_realtor_about_new_client(
    context: ContextTypes.DEFAULT_TYPE,
    client: ClientModel,
) -> None:
    repo = Container.get_repository()
    realtor = await repo.get_realtor(client.realtor_id)
    if not realtor:
        return

    notif_msg = (
        "🆕 <b>Новый клиент!</b>\n\n"
        f"👤 <b>{client.name or '—'}</b>\n"
        f"📞 {client.contact or 'Телефон не указан'}\n"
        f"💰 Бюджет: {client.budget or '—'}\n"
        f"🛏 {client.rooms or '—'} | 📐 {client.size or '—'}\n"
        f"📍 {client.location or '—'}\n"
        f"🏗 {client.ready_status or '—'}\n"
    )
    if client.notes:
        notes = client.notes
        notif_msg += f"\n📝 {notes[:200]}..." if len(notes) > 200 else f"\n📝 {notes}"

    keyboard = [[InlineKeyboardButton("👤 Открыть карточку", callback_data=f"client:{client.id}")]]
    if client.contact:
        keyboard[0].append(InlineKeyboardButton("📞 Позвонить", url=f"tel:{client.contact}"))

    if client.telegram_username:
        keyboard.append([
            InlineKeyboardButton(
                "💬 Написать в Telegram",
                url=f"https://t.me/{client.telegram_username}",
            )
        ])

    await context.bot.send_message(
        chat_id=realtor.id,
        text=notif_msg,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


async def _complete_client_conversation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    repo = Container.get_repository()

    info: Dict[str, Any] = context.user_data.get("client_info", {})
    realtor_id = info.get("realtor_id")

    realtor = await repo.get_realtor(realtor_id) if realtor_id else None

    client = ClientModel(
        telegram_id=int(info["telegram_id"]),
        realtor_id=int(realtor_id),
        telegram_username=info.get("telegram_username"),
        name=info.get("name", ""),
        budget=info.get("budget", ""),
        size=info.get("size", ""),
        location=info.get("location", ""),
        rooms=info.get("rooms", ""),
        ready_status=info.get("ready_status", ""),
        contact=info.get("contact", ""),
        notes=info.get("notes", ""),
    )

    client = await repo.create_client(client)

    summary = client.to_summary()
    completion_msg = MessageTemplates.format_client_completion(summary=summary)

    if update.effective_message:
        await update.effective_message.reply_text(completion_msg)

    # Notify realtor
    try:
        await _notify_realtor_about_new_client(context, client)
    except Exception as e:
        logger.error("Failed to notify realtor: %s", e, exc_info=True)

    # Clear user data
    context.user_data.clear()

    return ConversationHandler.END


async def _process_client_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> int:
    """Single path for processing a client message."""

    llm = Container.get_llm_service()

    sanitized = sanitize_user_text(text, max_len=2000)

    # If LLM is unavailable, run structured questionnaire.
    if context.user_data.get("questionnaire_mode") or not getattr(llm, "providers", {}):
        if not context.user_data.get("questionnaire_mode"):
            _set_question_step_index(context.user_data, 0)
            await _ask_current_question(update, context)
            return 8
        return await _handle_questionnaire_answer(update, context, sanitized)

    if "conversation" not in context.user_data:
        context.user_data["conversation"] = []

    context.user_data["conversation"].append({"role": "user", "content": sanitized})

    # Extract info once
    info = await llm.extract_client_info(context.user_data["conversation"])

    client_info: Dict[str, Any] = context.user_data.get("client_info", {})

    for field in [
        "budget",
        "size",
        "location",
        "rooms",
        "ready_status",
        "contact",
        "notes",
    ]:
        if info.get(field) and not client_info.get(field):
            client_info[field] = sanitize_user_text(str(info[field]), max_len=500)

    context.user_data["client_info"] = client_info

    # Complete
    if info.get("is_complete"):
        return await _complete_client_conversation(update, context)

    # Continue dialog
    response = await llm.generate_response(context.user_data["conversation"])
    if not response:
        response = "Понял! Расскажите ещё немного о ваших пожеланиях?"

    if update.effective_message:
        await update.effective_message.reply_text(response)

    context.user_data["conversation"].append({"role": "assistant", "content": response})

    return 8  # keep state value compatibility (ConversationState.CLIENT_COMPLETE.value)


@with_middleware
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start command and route based on user type."""

    user = update.effective_user
    if not user or not update.effective_message:
        return ConversationHandler.END

    if await _is_realtor(user.id):
        await update.effective_message.reply_text(
            "👋 С возвращением!\n\n"
            "Команды:\n"
            "/clients - список ваших клиентов\n"
            "/stats - статистика\n"
            "/help - помощь"
        )
        return ConversationHandler.END

    # Realtor registration in progress is handled by realtor conversation

    realtor = await _get_default_realtor()
    if not realtor:
        await update.effective_message.reply_text(
            "⚠️ Пока нет доступных риелторов.\n"
            "Если вы риелтор, отправьте /register"
        )
        return ConversationHandler.END

    # Existing client?
    repo = Container.get_repository()
    existing = await repo.get_client_by_telegram(user.id, realtor.id)
    if existing:
        await update.effective_message.reply_text(
            "👋 С возвращением!\n\n"
            "Мы уже получали вашу заявку. "
            f"{realtor.full_name} скоро с вами свяжется."
        )
        return ConversationHandler.END

    context.user_data["client_info"] = {
        "telegram_id": user.id,
        "telegram_username": user.username,
        "name": user.full_name,
        "realtor_id": realtor.id,
    }
    context.user_data["conversation"] = []

    await update.effective_message.reply_text(
        MessageTemplates.format_client_welcome(realtor_name=realtor.full_name)
    )

    # Seed first assistant message (LLM if available; otherwise questionnaire)
    llm = Container.get_llm_service()

    if not getattr(llm, "providers", {}):
        _set_question_step_index(context.user_data, 0)
        await _ask_current_question(update, context)
        return 8

    first_message = await llm.generate_response(
        [{"role": "user", "content": "Привет! Я хочу подобрать квартиру в Батуми."}]
    )

    if first_message:
        await update.effective_message.reply_text(first_message)
        context.user_data["conversation"].append({"role": "assistant", "content": first_message})
    else:
        # LLM temporarily failed → fallback to structured questionnaire
        _set_question_step_index(context.user_data, 0)
        await _ask_current_question(update, context)
        return 8

    return 8  # ConversationState.CLIENT_COMPLETE.value


@with_middleware
async def handle_client_llm_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle client text message."""

    if not update.effective_message or not update.effective_message.text:
        return 8

    if "client_info" not in context.user_data:
        await update.effective_message.reply_text(
            "Сначала отправьте /start чтобы начать диалог."
        )
        return ConversationHandler.END

    return await _process_client_text(update, context, update.effective_message.text)


@with_middleware
async def handle_client_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle client voice message."""

    if "client_info" not in context.user_data:
        if update.effective_message:
            await update.effective_message.reply_text(
                "🎙 Получил голосовое сообщение!\n\n"
                "Но сначала отправьте /start чтобы начать диалог."
            )
        return ConversationHandler.END

    if not update.message or not update.message.voice:
        return 8

    llm = Container.get_llm_service()

    # If transcription is unavailable, ask user to send text.
    if not getattr(llm, "providers", {}):
        if update.effective_message:
            await update.effective_message.reply_text(
                "🎙 Я получил голосовое, но сейчас не могу его расшифровать.\n"
                "Пожалуйста, отправьте сообщение текстом."
            )
        return 8

    # Download voice file
    voice_file = await update.message.voice.get_file()
    fd, voice_path = tempfile.mkstemp(suffix=".oga")
    os.close(fd)

    try:
        await voice_file.download_to_drive(voice_path)
        text = await llm.transcribe_audio(voice_path)
    finally:
        try:
            os.remove(voice_path)
        except Exception:
            pass

    if not text:
        if update.effective_message:
            await update.effective_message.reply_text(
                "❌ Не удалось распознать голосовое сообщение.\n"
                "Попробуйте записать ещё раз или напишите текстом."
            )
        return 8

    return await _process_client_text(update, context, text)


@with_middleware
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel command."""

    if update.effective_message:
        await update.effective_message.reply_text(
            "❌ Действие отменено.\n\n"
            "Чтобы начать заново, отправьте /start"
        )

    context.user_data.clear()
    return ConversationHandler.END
