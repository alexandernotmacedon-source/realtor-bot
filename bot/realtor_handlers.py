"""Realtor-facing handlers.

Contains:
- Realtor registration (/register)
- Clients management (/clients, /client, /stats)
- Export placeholder (/export)
- Inline buttons callbacks (client card, status updates)
- Developer names management (/developers)

All handlers are async.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.config import ClientStatus
from core.container import Container
from core.middleware import with_middleware
from database.models import RealtorModel
from utils.helpers import sanitize_user_text


logger = logging.getLogger(__name__)


async def _is_realtor(user_id: int) -> bool:
    repo = Container.get_repository()
    return (await repo.get_realtor(user_id)) is not None


@with_middleware
async def register_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start realtor registration."""

    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return ConversationHandler.END

    if await _is_realtor(user.id):
        await msg.reply_text("✅ Вы уже зарегистрированы как риелтор!")
        return ConversationHandler.END

    context.user_data["registering_realtor"] = True
    context.user_data["new_realtor"] = {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
    }

    await msg.reply_text(
        "📝 Регистрация риелтора\n\n"
        "Шаг 1/3: Введите ваш номер телефона для связи с клиентами."
    )

    return 11  # ConversationState.REALTOR_PHONE.value


@with_middleware
async def handle_realtor_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle realtor phone input."""

    msg = update.effective_message
    if not msg or not msg.text:
        return 11

    phone = sanitize_user_text(msg.text, max_len=64)
    context.user_data.setdefault("new_realtor", {})["phone"] = phone

    await msg.reply_text(
        f"✓ Телефон: {phone}\n\n"
        "Шаг 2/3: Введите название вашей компании (или напишите 'нет')."
    )

    return 12  # ConversationState.REALTOR_COMPANY.value


@with_middleware
async def handle_realtor_company(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle realtor company input and finalize registration."""

    user = update.effective_user
    msg = update.effective_message
    if not user or not msg or not msg.text:
        return ConversationHandler.END

    company = sanitize_user_text(msg.text, max_len=128)
    if company.lower() in {"нет", "no", "-"}:
        company = ""

    realtor_data = context.user_data.get("new_realtor", {})
    realtor_data["company_name"] = company or None

    # Validate and persist
    repo = Container.get_repository()

    try:
        realtor = RealtorModel(
            id=int(realtor_data["id"]),
            username=realtor_data.get("username"),
            full_name=realtor_data.get("full_name") or user.full_name,
            phone=realtor_data.get("phone"),
            company_name=realtor_data.get("company_name"),
        )
    except Exception as e:
        await msg.reply_text(f"❌ Ошибка в данных регистрации: {e}")
        return ConversationHandler.END

    await repo.create_realtor(realtor)

    context.user_data.pop("registering_realtor", None)
    context.user_data.pop("new_realtor", None)

    welcome_msg = (
        "✅ Регистрация завершена!\n\n"
        f"👤 {realtor.full_name}\n"
        f"📞 {realtor.phone or '—'}\n"
        f"🏢 {realtor.company_name or 'ИП'}\n\n"
        "Следующие шаги:\n"
        "1. Подключите Google Drive (/drive_setup)\n"
        "2. Дайте клиентам ссылку на бота\n\n"
        "Новые клиенты будут появляться автоматически!"
    )

    await msg.reply_text(welcome_msg)
    return ConversationHandler.END


@with_middleware
async def clients_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List clients for realtor."""

    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return

    if not await _is_realtor(user.id):
        await msg.reply_text("⚠️ Только для риелторов.")
        return

    repo = Container.get_repository()
    clients = await repo.get_clients_by_realtor(user.id)

    if not clients:
        await msg.reply_text("📭 Пока нет клиентов.")
        return

    status_emoji = {
        ClientStatus.NEW.value: "🆕",
        ClientStatus.CONTACTED.value: "📞",
        ClientStatus.VIEWING.value: "👁",
        ClientStatus.CLOSED.value: "✅",
        ClientStatus.REJECTED.value: "❌",
    }

    lines = [f"📋 Ваши клиенты ({len(clients)}):\n"]
    for i, client in enumerate(clients[:10], 1):
        status = client.status.value if hasattr(client.status, "value") else str(client.status)
        emoji = status_emoji.get(status, "❓")
        lines.append(f"{i}. {emoji} {client.name or '—'} - {client.budget or '—'}")

    if len(clients) > 10:
        lines.append(f"\n... и ещё {len(clients) - 10} клиентов")

    await msg.reply_text("\n".join(lines))


@with_middleware
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show stats for realtor."""

    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return

    if not await _is_realtor(user.id):
        await msg.reply_text("⚠️ Только для риелторов.")
        return

    repo = Container.get_repository()
    clients = await repo.get_clients_by_realtor(user.id)

    by_status: dict[str, int] = {}
    for c in clients:
        key = c.status.value if hasattr(c.status, "value") else str(c.status)
        by_status[key] = by_status.get(key, 0) + 1

    total = len(clients)

    msg_text = (
        "📊 Статистика:\n\n"
        f"Всего клиентов: {total}\n\n"
        f"🆕 Новые: {by_status.get(ClientStatus.NEW.value, 0)}\n"
        f"📞 Связались: {by_status.get(ClientStatus.CONTACTED.value, 0)}\n"
        f"👁 На просмотре: {by_status.get(ClientStatus.VIEWING.value, 0)}\n"
        f"✅ Закрыто: {by_status.get(ClientStatus.CLOSED.value, 0)}\n"
        f"❌ Отказ: {by_status.get(ClientStatus.REJECTED.value, 0)}\n"
    )

    if clients:
        msg_text += "\n💡 Для просмотра деталей: /client <id>\n"
        msg_text += f"Например: /client {clients[0].id}"

    await msg.reply_text(msg_text)


@with_middleware
async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate referral link for realtor."""

    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return

    if not await _is_realtor(user.id):
        await msg.reply_text("⚠️ Только для риелторов.")
        return

    repo = Container.get_repository()
    realtor = await repo.get_realtor(user.id)
    
    if not realtor:
        await msg.reply_text("❌ Ошибка: риелтор не найден.")
        return

    # Get bot info for username
    try:
        bot_info = await context.bot.get_me()
        bot_username = bot_info.username
    except Exception:
        bot_username = "Property_Batumi_bot"  # Fallback

    # Generate referral link
    referral_link = f"https://t.me/{bot_username}?start=ref_{user.id}"

    msg_text = (
        "🔗 <b>Ваша реферальная ссылка</b>\n\n"
        f"{referral_link}\n\n"
        "📲 <b>Как использовать:</b>\n"
        "1. Отправьте эту ссылку клиенту\n"
        "2. Клиент нажимает и открывает бота\n"
        "3. Клиент автоматически закрепляется за вами!\n\n"
        f"💡 <b>Совет:</b> Добавьте ссылку в Instagram, визитку или отправьте в личных сообщениях."
    )

    await msg.reply_text(msg_text, parse_mode="HTML")


@with_middleware
async def client_detail_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show client details: /client <id>."""

    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return

    if not await _is_realtor(user.id):
        await msg.reply_text("⚠️ Только для риелторов.")
        return

    if not context.args:
        await msg.reply_text(
            "❌ Укажите ID клиента.\n\n"
            "Пример: /client 123\n\n"
            "Список клиентов: /clients"
        )
        return

    try:
        client_id = int(context.args[0])
    except ValueError:
        await msg.reply_text("❌ ID клиента должен быть числом.")
        return

    repo = Container.get_repository()
    client = await repo.get_client(client_id)

    if not client:
        await msg.reply_text(f"❌ Клиент с ID {client_id} не найден.")
        return

    if client.realtor_id != user.id:
        await msg.reply_text("❌ У вас нет доступа к этому клиенту.")
        return

    status_emoji = {
        ClientStatus.NEW.value: "🆕",
        ClientStatus.CONTACTED.value: "📞",
        ClientStatus.VIEWING.value: "👁",
        ClientStatus.CLOSED.value: "✅",
        ClientStatus.REJECTED.value: "❌",
    }
    status = client.status.value if hasattr(client.status, "value") else str(client.status)
    emoji = status_emoji.get(status, "❓")

    created_str = client.created_at.strftime("%d.%m.%Y %H:%M")

    text = (
        f"{emoji} <b>Клиент #{client.id}</b>\n\n"
        "📋 <b>Контакты:</b>\n"
        f"👤 Имя: {client.name or '—'}\n"
        + (f"🔗 Telegram: @{client.telegram_username}\n" if client.telegram_username else "")
        + f"📞 Телефон: {client.contact or '—'}\n"
        + f"🆔 Telegram ID: <code>{client.telegram_id}</code>\n\n"
        "🎯 <b>Требования:</b>\n"
        f"💰 Бюджет: {client.budget or '—'}\n"
        f"🛏 Комнаты: {client.rooms or '—'}\n"
        f"📐 Площадь: {client.size or '—'}\n"
        f"📍 Локация: {client.location or '—'}\n"
        f"🏗 Стадия: {client.ready_status or '—'}\n\n"
    )

    if client.notes:
        text += f"📝 <b>Дополнительно:</b>\n{client.notes}\n\n"

    text += f"📊 <b>Статус:</b> {emoji} {client.status}\n"
    text += f"📅 Добавлен: {created_str}\n"

    keyboard = [
        [InlineKeyboardButton("📞 Позвонить", url=f"tel:{client.contact}")],
        [
            InlineKeyboardButton("✅ Закрыть", callback_data=f"status:{client.id}:{ClientStatus.CLOSED.value}"),
            InlineKeyboardButton("❌ Отказ", callback_data=f"status:{client.id}:{ClientStatus.REJECTED.value}"),
        ],
    ]

    if client.telegram_username:
        keyboard[0].append(InlineKeyboardButton("💬 Написать", url=f"tg://user?id={client.telegram_id}"))

    await msg.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


@with_middleware
async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Export clients placeholder."""

    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return

    if not await _is_realtor(user.id):
        await msg.reply_text("⚠️ Только для риелторов.")
        return

    repo = Container.get_repository()
    clients = await repo.get_clients_by_realtor(user.id)

    if not clients:
        await msg.reply_text("📭 Нет клиентов для экспорта.")
        return

    await msg.reply_text(
        f"📊 Экспорт {len(clients)} клиентов...\n\n"
        "(Функция в разработке — пока используйте /clients и /client <id>)"
    )


@with_middleware
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button callbacks."""

    query = update.callback_query
    if not query:
        return

    await query.answer()

    user = update.effective_user
    if not user:
        return

    data = query.data or ""

    repo = Container.get_repository()

    # Handle realtor choice for existing clients (available to all users)
    if data.startswith("choose_existing_realtor:"):
        realtor_id = int(data.split(":", 1)[1])
        realtor = await repo.get_realtor(realtor_id)
        
        if not realtor:
            await query.edit_message_text("❌ Риелтор не найден.")
            return
        
        # Continue with existing realtor
        context.user_data["client_info"] = {
            "telegram_id": user.id,
            "telegram_username": user.username,
            "name": user.full_name,
            "realtor_id": realtor.id,
        }
        context.user_data["conversation"] = []
        context.user_data["pending_realtor_choice"] = False
        
        welcome_text = f"👋 С возвращением! Рада снова помочь с подбором недвижимости.\n\nДавайте уточним критерии — на какую сумму сейчас рассматриваете покупку? 💫"
        
        await query.edit_message_text(welcome_text)
        
        context.user_data["conversation"] = [
            {"role": "system", "content": f"Риелтор: {realtor.full_name}"},
            {"role": "assistant", "content": welcome_text}
        ]
        return
    
    if data.startswith("choose_new_realtor:"):
        new_realtor_id = int(data.split(":", 1)[1])
        new_realtor = await repo.get_realtor(new_realtor_id)
        
        if not new_realtor:
            await query.edit_message_text("❌ Риелтор не найден.")
            return
        
        # Check if client exists with old realtor and delete old record
        existing_client = await repo.get_client_by_telegram_global(user.id)
        if existing_client:
            await repo.delete_client(existing_client.id)
        
        # Continue with new realtor
        context.user_data["client_info"] = {
            "telegram_id": user.id,
            "telegram_username": user.username,
            "name": user.full_name,
            "realtor_id": new_realtor.id,
        }
        context.user_data["conversation"] = []
        context.user_data["pending_realtor_choice"] = False
        
        welcome_text = f"Здравствуйте! Меня зовут {new_realtor.full_name}, я риелтор по недвижимости в Батуми. Рада помочь с подбором квартиры! 💫\n\nДавайте начнём с бюджета — на какую сумму вы рассматриваете покупку?"
        
        await query.edit_message_text(welcome_text)
        
        context.user_data["conversation"] = [
            {"role": "system", "content": f"Риелтор: {new_realtor.full_name}"},
            {"role": "assistant", "content": welcome_text}
        ]
        return

    # View client (realtor only)
    if data.startswith("client:"):
        client_id = int(data.split(":", 1)[1])
        client = await repo.get_client(client_id)

        if not client or client.realtor_id != user.id:
            await query.edit_message_text("❌ Клиент не найден или нет доступа.")
            return

        text = (
            f"<b>Клиент #{client.id}</b>\n\n"
            f"👤 Имя: {client.name or '—'}\n"
            f"📞 Телефон: {client.contact or '—'}\n"
            f"💰 Бюджет: {client.budget or '—'}\n"
            f"🛏 Комнаты: {client.rooms or '—'}\n"
            f"📐 Площадь: {client.size or '—'}\n"
            f"📍 Локация: {client.location or '—'}\n"
            f"🏗 Стадия: {client.ready_status or '—'}\n"
        )
        if client.notes:
            text += f"\n📝 {client.notes}"

        keyboard = []
        
        # Add Telegram message button if username exists
        if client.telegram_username:
            keyboard.append([InlineKeyboardButton("💬 Написать в Telegram", url=f"https://t.me/{client.telegram_username}")])
        
        # Only add call button if contact looks like a phone number
        if client.contact and client.contact.startswith("+"):
            keyboard.append([InlineKeyboardButton("📞 Позвонить", url=f"tel:{client.contact}")])
        
        keyboard.append([
            InlineKeyboardButton("✅ Закрыть", callback_data=f"status:{client.id}:{ClientStatus.CLOSED.value}"),
            InlineKeyboardButton("❌ Отказ", callback_data=f"status:{client.id}:{ClientStatus.REJECTED.value}"),
        ])

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )
        return

    # Status change
    if data.startswith("status:"):
        _, client_id_str, new_status = data.split(":", 2)
        client_id = int(client_id_str)

        client = await repo.get_client(client_id)
        if not client or client.realtor_id != user.id:
            await query.edit_message_text("❌ Клиент не найден или нет доступа.")
            return

        old_status = client.status.value if hasattr(client.status, "value") else str(client.status)
        try:
            client.status = ClientStatus(new_status)
        except ValueError:
            client.status = ClientStatus.NEW

        await repo.update_client(client)

        status_names = {
            ClientStatus.NEW.value: "Новый",
            ClientStatus.CONTACTED.value: "Связались",
            ClientStatus.VIEWING.value: "На просмотре",
            ClientStatus.CLOSED.value: "Закрыт",
            ClientStatus.REJECTED.value: "Отказ",
        }

        await query.edit_message_text(
            "✅ Статус клиента #{id} изменён:\n{old} → {new}".format(
                id=client.id,
                old=status_names.get(old_status, old_status),
                new=status_names.get(new_status, new_status),
            ),
            parse_mode="HTML",
        )
        return


@with_middleware
async def developers_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show and manage developer names and addresses mapping."""
    if not update.effective_user or not update.effective_message:
        return

    user = update.effective_user
    if not await _is_realtor(user.id):
        await update.effective_message.reply_text(
            "❌ Эта команда только для риелторов."
        )
        return

    # Load current mappings
    names_path = Path("./data/developer_names.json")
    addresses_path = Path("./data/developer_addresses.json")

    if names_path.exists():
        with open(names_path, 'r', encoding='utf-8') as f:
            names_mapping = json.load(f)
    else:
        names_mapping = {}

    if addresses_path.exists():
        with open(addresses_path, 'r', encoding='utf-8') as f:
            addresses_mapping = json.load(f)
    else:
        addresses_mapping = {}

    # Check for subcommand: /developers address folder_3 "ул. Пушкина 10"
    if context.args and len(context.args) >= 1:
        if context.args[0].lower() == 'address' and len(context.args) >= 3:
            # Format: /developers address folder_3 "ул. Пушкина 10"
            folder_key = context.args[1]
            address = ' '.join(context.args[2:]).strip('"\'')

            if folder_key.startswith('folder_'):
                addresses_mapping[folder_key] = address
                with open(addresses_path, 'w', encoding='utf-8') as f:
                    json.dump(addresses_mapping, f, indent=2, ensure_ascii=False)
                await update.effective_message.reply_text(
                    f"✅ Адрес обновлён: <b>{folder_key}</b>\n"
                    f"📍 {address}\n\n"
                    f"Изменения применятся сразу!",
                    parse_mode="HTML"
                )
                return
            else:
                await update.effective_message.reply_text(
                    "❌ Неверный формат ключа. Используйте: folder_1, folder_2, etc."
                )
                return

        elif context.args[0].startswith('folder_') and len(context.args) >= 2:
            # Format: /developers folder_3 "Next Magnolia"
            folder_key = context.args[0]
            display_name = ' '.join(context.args[1:]).strip('"\'')

            names_mapping[folder_key] = display_name
            with open(names_path, 'w', encoding='utf-8') as f:
                json.dump(names_mapping, f, indent=2, ensure_ascii=False)
            await update.effective_message.reply_text(
                f"✅ Название обновлено: <b>{folder_key}</b> → <b>{display_name}</b>\n\n"
                f"Изменения применятся сразу!",
                parse_mode="HTML"
            )
            return

        else:
            await update.effective_message.reply_text(
                "❌ Неверный формат.\n\n"
                "<b>Название:</b> <code>/developers folder_3 Next Magnolia</code>\n"
                "<b>Адрес:</b> <code>/developers address folder_3 \"ул. Пушкина 10\"</code>"
            )
            return

    # Show current mapping
    lines = ["🏗 <b>Застройщики</b> (название + адрес)\n"]

    for key in sorted(names_mapping.keys()):
        if key.startswith('_'):
            continue
        name = names_mapping[key]
        address = addresses_mapping.get(key, '')
        if address:
            lines.append(f"<code>{key}</code> → <b>{name}</b>\n   📍 {address}")
        else:
            lines.append(f"<code>{key}</code> → <b>{name}</b>")

    lines.append("\n<b>Как обновить:</b>")
    lines.append("<code>/developers folder_3 Next Magnolia</code>")
    lines.append("<code>/developers address folder_3 \"ул. Пушкина 10\"</code>")
    lines.append("\nИзменения применяются сразу — без перезапуска бота!")

    await update.effective_message.reply_text(
        '\n'.join(lines),
        parse_mode="HTML"
    )
