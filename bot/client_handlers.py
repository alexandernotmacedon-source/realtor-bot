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
        "Когда вам удобно, чтобы я позвонила? 📞\n\nНапишите:\n• Сейчас можно\n• Через час\n• После 18:00\n• Лучше пишите в Telegram",
    ),
    (
        "notes",
        "Дополнительные пожелания? 📝\n\nНапример: этаж, вид, паркинг, расстояние до моря.\nИли напишите «нет».",
    ),
]


async def _is_realtor(user_id: int) -> bool:
    repo = Container.get_repository()
    return (await repo.get_realtor(user_id)) is not None


async def _get_realtor_by_id(realtor_id: int) -> Optional[Any]:
    """Get realtor by specific ID."""
    repo = Container.get_repository()
    return await repo.get_realtor(realtor_id)


async def _get_default_realtor() -> Optional[Any]:
    """Get assigned realtor for client using round-robin distribution.

    Cycles through active realtors to distribute clients evenly.
    """
    repo = Container.get_repository()
    realtors = await repo.get_all_realtors()
    active_realtors = [r for r in realtors if r.is_active]

    if not active_realtors:
        return None

    if len(active_realtors) == 1:
        return active_realtors[0]

    # Load last assigned index from a simple file-based tracker
    import json
    import os
    tracker_path = Path("./data/last_assigned_realtor.json")

    last_index = 0
    if tracker_path.exists():
        try:
            with open(tracker_path, 'r') as f:
                data = json.load(f)
                last_index = data.get('index', 0)
        except (json.JSONDecodeError, IOError):
            last_index = 0

    # Calculate next index (round-robin)
    next_index = (last_index + 1) % len(active_realtors)

    # Save the new index
    try:
        with open(tracker_path, 'w') as f:
            json.dump({'index': next_index}, f)
    except IOError:
        pass  # Non-critical, continue anyway

    return active_realtors[next_index]


def _parse_referral_code(context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Parse referral code from /start command args.
    
    Format: /start ref_123 where 123 is realtor_id
    Returns: realtor_id or None
    """
    if not context.args:
        return None
    
    arg = context.args[0]
    if arg.startswith("ref_"):
        try:
            return int(arg.split("_")[1])
        except (IndexError, ValueError):
            return None
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


async def _autosave_client_draft(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Autosave client draft to database after each answer."""
    repo = Container.get_repository()
    info: Dict[str, Any] = context.user_data.get("client_info", {})
    
    if not info.get("telegram_id"):
        return
    
    # Check if draft already exists
    existing_id = context.user_data.get("draft_client_id")
    
    client = ClientModel(
        id=existing_id,
        telegram_id=int(info["telegram_id"]),
        realtor_id=int(info.get("realtor_id", 0)),
        telegram_username=info.get("telegram_username"),
        name=info.get("name", "— (в процессе)"),
        budget=info.get("budget", ""),
        size=info.get("size", ""),
        location=info.get("location", ""),
        rooms=info.get("rooms", ""),
        ready_status=info.get("ready_status", ""),
        contact=info.get("contact", ""),
        notes=info.get("notes", ""),
        status="draft",  # Temporary status
    )
    
    try:
        if existing_id:
            client = await repo.update_client(client)
        else:
            client = await repo.create_client(client)
            context.user_data["draft_client_id"] = client.id
            logger.info(f"Created client draft ID: {client.id}")
    except Exception as e:
        logger.error(f"Failed to autosave draft: {e}")


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
    
    # AUTOSAVE: Save draft after each answer
    await _autosave_client_draft(update, context)

    # Next question
    _set_question_step_index(context.user_data, _question_step_index(context.user_data) + 1)

    if _get_current_question(context.user_data) is None:
        return await _complete_client_conversation(update, context)

    await _ask_current_question(update, context)
    return 8


async def _notify_realtor_about_new_client(
    context: ContextTypes.DEFAULT_TYPE,
    client: ClientModel,
    selected_apartment: dict = None,
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

    # Add selected apartment info (highlighted!)
    if selected_apartment:
        notif_msg += (
            f"\n\n⭐ <b>ВЫБРАЛ ВАРИАНТ:</b>\n"
            f"{selected_apartment.get('developer')} — кв. {selected_apartment.get('apartment_id')}\n"
        )

    keyboard = [[InlineKeyboardButton("👤 Открыть карточку", callback_data=f"client:{client.id}")]]

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


async def _search_and_format_apartments(
    client_info: Dict[str, Any],
    max_results: int = 5
) -> tuple[Optional[str], list]:
    """Search inventory for matching apartments and format results.
    
    Returns tuple of (formatted_message, matches_list) or (None, []) if no matches.
    """
    try:
        from integrations.inventory import inventory_matcher
        from integrations.google_drive import drive_manager
        
        # Ensure drive is authorized
        if not drive_manager.is_authorized():
            logger.warning("Google Drive not authorized, cannot search inventory")
            return None, []
        
        # Refresh inventory if needed
        if not inventory_matcher.inventory_cache:
            success = await asyncio.to_thread(inventory_matcher.refresh_inventory)
            if not success:
                return None, []
        
        # Search for matches
        matches = await asyncio.to_thread(
            inventory_matcher.match_apartments,
            budget=client_info.get("budget"),
            size=client_info.get("size"),
            location=client_info.get("location"),
            rooms=client_info.get("rooms"),
            ready_status=client_info.get("ready_status"),
            max_results=max_results
        )
        
        if not matches:
            return None, []
        
        # Format results - simple and clean
        lines = ["\n🏠 <b>Варианты для вас:</b>\n"]
        for i, match in enumerate(matches, 1):
            lines.append(f"{i}. {inventory_matcher.format_match(match)}")
        
        lines.append("\n💬 Напишите номер варианта — пришлю фото и детали!")
        
        return "\n".join(lines), matches
        
    except Exception as e:
        logger.error(f"Failed to search apartments: {e}")
        return None, []


async def _complete_client_conversation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    repo = Container.get_repository()

    info: Dict[str, Any] = context.user_data.get("client_info", {})
    realtor_id = info.get("realtor_id")
    
    # Get draft ID if exists
    draft_id = context.user_data.get("draft_client_id")

    realtor = await repo.get_realtor(realtor_id) if realtor_id else None

    client = ClientModel(
        id=draft_id,  # Use existing draft ID if available
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
        status="new",  # Final status
    )

    if draft_id:
        client = await repo.update_client(client)
        logger.info(f"Finalized client from draft ID: {draft_id}")
    else:
        client = await repo.create_client(client)

    summary = client.to_summary()
    completion_msg = MessageTemplates.format_client_completion(summary=summary)

    # Search for matching apartments
    apartments_msg, matches = await _search_and_format_apartments(info)
    if apartments_msg:
        completion_msg += apartments_msg
        # Wait for client to select apartment - don't ask for contact yet
        completion_msg += "\n\n💬 Какой вариант вам понравился? Напишите номер, или скажите если ничего не подошло — подберу ещё!"
        # Save matches for later reference
        context.user_data["shown_apartments"] = matches
        context.user_data["awaiting_apartment_selection"] = True
    else:
        completion_msg += "\n\n🔍 Сейчас проверю наличие подходящих вариантов и пришлю результаты."

    if update.effective_message:
        await update.effective_message.reply_text(completion_msg, parse_mode="HTML")

    # Notify realtor
    try:
        await _notify_realtor_about_new_client(context, client, matches)
    except Exception as e:
        logger.error("Failed to notify realtor: %s", e, exc_info=True)

    # Keep conversation open for contact request, but mark client as created
    context.user_data["client_created"] = True
    context.user_data["client_id"] = client.id

    return 8  # Keep conversation open for follow-up contact


async def _handle_apartment_selection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> int:
    """Handle client's apartment selection response."""

    sanitized = sanitize_user_text(text, max_len=500).lower()

    # Check if client said nothing fits
    negative_responses = ['не', 'ничего', 'не подошло', 'не нравится', 'другое', 'другой', 'нет']
    if any(neg in sanitized for neg in negative_responses) or 'подошло' in sanitized:
        await update.effective_message.reply_text(
            "Поняла! Давайте уточним критерии — что именно не устроило? "
            "Или может посмотрим варианты в другом районе/бюджете? 🏠"
        )
        # Clear selection flag but keep conversation open
        context.user_data.pop("awaiting_apartment_selection", None)
        return 8

    # Try to extract apartment number (1, 2, 3, etc.)
    import re
    numbers = re.findall(r'\b(\d+)\b', sanitized)

    if numbers:
        apt_num = int(numbers[0])
        matches = context.user_data.get("shown_apartments", [])

        if 1 <= apt_num <= len(matches):
            match = matches[apt_num - 1]
            apt_id = match.data.get('ბინა/apartment', match.data.get('№', '—'))
            developer = match.developer

            await update.effective_message.reply_text(
                f"✅ Отличный выбор! Вариант #{apt_num} — {developer}, квартира {apt_id}.\n\n"
                f"📐 Хотите, чтобы я выслала планировку этой квартиры?"
            )

            # Mark as interested, now awaiting contact
            context.user_data.pop("awaiting_apartment_selection", None)
            context.user_data["awaiting_contact"] = True
            context.user_data["selected_apartment"] = {
                "number": apt_num,
                "developer": developer,
                "apartment_id": apt_id
            }
            return 8
        else:
            await update.effective_message.reply_text(
                f"Я вижу вы написали {apt_num}, но у меня показано {len(matches)} вариантов. "
                f"Напишите номер от 1 до {len(matches)}, или скажите если ничего не подошло 💬"
            )
            return 8

    # Couldn't parse selection - ask again
    await update.effective_message.reply_text(
        "Напишите, пожалуйста, номер варианта который понравился (например: 1, 2 или 3), "
        "или скажите если ничего не подошло 🏠"
    )
    return 8


async def _handle_contact_followup(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> int:
    """Handle contact information after client selected apartment."""

    client_id = context.user_data.get("client_id")
    if not client_id:
        return ConversationHandler.END

    sanitized = sanitize_user_text(text, max_len=200)

    # Update client with contact info
    repo = Container.get_repository()
    client = await repo.get_client(client_id)
    if client:
        client.contact = sanitized
        await repo.update_client(client)

        # Smooth transition to direct communication - no "I passed info" message
        selected = context.user_data.get("selected_apartment", {})
        if selected:
            await update.effective_message.reply_text(
                f"✅ Отлично! Передаю контакт Софе по выбранному варианту "
                f"({selected.get('developer')}, кв. {selected.get('apartment_id')}).\n\n"
                f"Она свяжется с вами {sanitized}! 📞"
            )
        else:
            await update.effective_message.reply_text(
                f"✅ Отлично! Передаю контакт Софе — она свяжется с вами {sanitized}! 📞"
            )

        # Notify realtor with selected apartment info
        try:
            await _notify_realtor_about_new_client(context, client, selected)
        except Exception as e:
            logger.error("Failed to notify realtor about contact update: %s", e)

    context.user_data.clear()
    return ConversationHandler.END


async def _process_client_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> int:
    """Single path for processing a client message."""

    # Handle apartment selection after showing options
    if context.user_data.get("awaiting_apartment_selection"):
        return await _handle_apartment_selection(update, context, text)

    # Handle contact info after client selected apartment
    if context.user_data.get("awaiting_contact"):
        return await _handle_contact_followup(update, context, text)

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
    
    # AUTOSAVE: Save draft after each LLM extraction
    await _autosave_client_draft(update, context)

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

    # Get target realtor from referral code or default
    referral_realtor_id = _parse_referral_code(context)
    if referral_realtor_id:
        target_realtor = await _get_realtor_by_id(referral_realtor_id)
        if not target_realtor:
            target_realtor = await _get_default_realtor()
    else:
        target_realtor = await _get_default_realtor()
    
    if not target_realtor:
        await update.effective_message.reply_text(
            "⚠️ Пока нет доступных риелторов.\n"
            "Если вы риелтор, отправьте /register"
        )
        return ConversationHandler.END

    # Check if client already exists with ANY realtor
    repo = Container.get_repository()
    existing_client = await repo.get_client_by_telegram_global(user.id)
    
    if existing_client:
        # Client exists with another realtor
        existing_realtor = await repo.get_realtor(existing_client.realtor_id)
        
        if existing_realtor and existing_realtor.id != target_realtor.id:
            # Different realtor - show warning with choice
            keyboard = [
                [
                    InlineKeyboardButton(
                        f"📞 Связаться с {existing_realtor.full_name}",
                        callback_data=f"choose_existing_realtor:{existing_realtor.id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"🆕 Начать с {target_realtor.full_name}",
                        callback_data=f"choose_new_realtor:{target_realtor.id}"
                    )
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            warning_text = (
                f"⚠️ <b>Внимание!</b>\n\n"
                f"Вы уже работаете с риелтором <b>{existing_realtor.full_name}</b>.\n\n"
                f"С кем хотите продолжить общение?"
            )
            
            # Store both realtors in context for later
            context.user_data["existing_realtor_id"] = existing_realtor.id
            context.user_data["new_realtor_id"] = target_realtor.id
            context.user_data["pending_realtor_choice"] = True
            
            await update.effective_message.reply_text(
                warning_text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
            return 8  # Wait for user choice
        
        elif existing_realtor and existing_realtor.id == target_realtor.id:
            # Same realtor - returning client
            is_returning = True
        else:
            is_returning = False
    else:
        is_returning = False

    # Setup client info with chosen realtor
    context.user_data["client_info"] = {
        "telegram_id": user.id,
        "telegram_username": user.username,
        "name": user.full_name,
        "realtor_id": target_realtor.id,
    }
    context.user_data["conversation"] = []

    # Send welcome message using template with realtor's name
    if is_returning:
        welcome_text = f"👋 С возвращением! Рада снова помочь с подбором недвижимости.\n\nДавайте уточним критерии — на какую сумму сейчас рассматриваете покупку? 💫"
    else:
        welcome_text = f"Здравствуйте! Меня зовут {target_realtor.full_name}, я риелтор по недвижимости в Батуми. Рада помочь с подбором квартиры! 💫\n\nДавайте начнём с бюджета — на какую сумму вы рассматриваете покупку?"
    await update.effective_message.reply_text(welcome_text)
    
    # Initialize conversation history for LLM
    context.user_data["conversation"] = [
        {"role": "system", "content": f"Риелтор: {target_realtor.full_name}"},
        {"role": "assistant", "content": welcome_text}
    ]

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
