"""Google Drive / inventory handlers.

Contains commands:
- /drive_setup
- drive_auth_code_handler (plain text message when awaiting code)
- /inventory
- /search
- /folders

Uses DriveManager and InventoryMatcher via DI container.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict

from telegram import Update
from telegram.ext import ContextTypes

from core.container import Container
from core.middleware import with_middleware
from utils.helpers import sanitize_user_text


logger = logging.getLogger(__name__)


async def _is_realtor(user_id: int) -> bool:
    repo = Container.get_repository()
    return (await repo.get_realtor(user_id)) is not None


@with_middleware
async def drive_setup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Authorize Google Drive via OAuth code."""

    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return

    if not await _is_realtor(user.id):
        await msg.reply_text("⚠️ Только для риелторов.")
        return

    drive = Container.get_drive_manager()

    if drive.is_authorized():
        await msg.reply_text(
            "✅ Google Drive уже подключен!\n\n"
            "Используйте /inventory чтобы посмотреть остатки."
        )
        return

    try:
        auth_url = await asyncio.to_thread(drive.get_auth_url)
    except FileNotFoundError:
        await msg.reply_text(
            "❌ Ошибка: файл credentials.json не найден.\n\n"
            "Обратитесь к администратору бота."
        )
        return

    await msg.reply_text(
        "🔐 Настройка Google Drive\n\n"
        "1. Откройте эту ссылку:\n"
        f"{auth_url}\n\n"
        "2. Выберите Google аккаунт\n"
        "3. Разрешите доступ к Google Drive\n"
        "4. Скопируйте код авторизации и отправьте сюда\n\n"
        "Отправьте код: 👇"
    )

    context.user_data["awaiting_drive_code"] = True


@with_middleware
async def drive_auth_code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Google Drive authorization code."""

    if not context.user_data.get("awaiting_drive_code"):
        return

    msg = update.effective_message
    if not msg or not msg.text:
        return

    auth_code = sanitize_user_text(msg.text, max_len=512)

    await msg.reply_text("🔄 Подключаю Google Drive...")

    drive = Container.get_drive_manager()
    ok = await asyncio.to_thread(drive.complete_auth, auth_code)

    if ok:
        await msg.reply_text(
            "✅ Google Drive подключен успешно!\n\n"
            "Теперь бот может читать остатки из папок застройщиков.\n\n"
            "Используйте:\n"
            "/inventory — посмотреть остатки\n"
            "/folders — управление папками"
        )
    else:
        await msg.reply_text(
            "❌ Ошибка авторизации.\n\n"
            "Попробуйте снова: /drive_setup"
        )

    context.user_data["awaiting_drive_code"] = False


@with_middleware
async def inventory_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Load and show inventory summary."""

    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return

    if not await _is_realtor(user.id):
        await msg.reply_text("⚠️ Только для риелторов.")
        return

    drive = Container.get_drive_manager()
    if not drive.is_authorized():
        await msg.reply_text(
            "🔐 Google Drive не подключен.\n\n"
            "Отправьте /drive_setup чтобы настроить."
        )
        return

    await msg.reply_text("🔄 Загружаю остатки...")

    matcher = Container.get_inventory_matcher()
    ok = await asyncio.to_thread(matcher.refresh_inventory, False)

    if not ok:
        await msg.reply_text(
            "❌ Не удалось загрузить остатки.\n\n"
            "Попробуйте позже или проверьте доступ."
        )
        return

    inventory = matcher.inventory_cache
    if not inventory:
        await msg.reply_text(
            "📭 Остатки не найдены.\n\n"
            "Проверьте настройки папок: /folders"
        )
        return

    lines = ["📦 Остатки по застройщикам:\n"]
    for developer_name, df in inventory.items():
        if df is not None:
            lines.append(f"🏢 {developer_name}: {len(df)} квартир")

    lines.append("\nДля поиска используйте /search")
    await msg.reply_text("\n".join(lines))


@with_middleware
async def search_inventory_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search matching inventory by parameters."""

    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return

    if not await _is_realtor(user.id):
        await msg.reply_text("⚠️ Только для риелторов.")
        return

    args = context.args or []
    if not args:
        await msg.reply_text(
            "🔍 Поиск по остаткам\n\n"
            "Использование:\n"
            "/search бюджет=150000 комнаты=2\n"
            "/search площадь=50-70\n\n"
            "Параметры:\n"
            "• бюджет=XXX (в лари)\n"
            "• комнаты=X (0=студия, 1,2,3...)\n"
            "• площадь=XX-XX (в м²)\n"
            "• локация=название"
        )
        return

    params: Dict[str, str] = {}
    for arg in args:
        if "=" in arg:
            k, v = arg.split("=", 1)
            params[sanitize_user_text(k.lower(), 32)] = sanitize_user_text(v, 128)

    await msg.reply_text("🔍 Ищу подходящие варианты...")

    matcher = Container.get_inventory_matcher()

    # ensure inventory loaded (in thread)
    if not matcher.inventory_cache:
        await asyncio.to_thread(matcher.refresh_inventory, False)

    matches = await asyncio.to_thread(
        matcher.match_apartments,
        params.get("бюджет") or params.get("budget"),
        params.get("площадь") or params.get("size"),
        params.get("локация") or params.get("location"),
        params.get("комнаты") or params.get("rooms"),
        params.get("стадия") or params.get("ready_status"),
        5,
    )

    if not matches:
        await msg.reply_text(
            "😕 Подходящих вариантов не найдено.\n\n"
            "Попробуйте изменить параметры поиска."
        )
        return

    text = [f"✅ Найдено {len(matches)} вариантов:\n"]
    for m in matches:
        text.append(matcher.format_match(m))

    await msg.reply_text("\n".join(text))


@with_middleware
async def folders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show configured developer folders."""

    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return

    if not await _is_realtor(user.id):
        await msg.reply_text("⚠️ Только для риелторов.")
        return

    drive = Container.get_drive_manager()
    folders = drive.folders

    if not folders:
        await msg.reply_text(
            "📁 Папки не настроены.\n\n"
            "Обратитесь к администратору."
        )
        return

    lines = ["📁 Настроенные папки:\n"]
    for name, folder_id in folders.items():
        preview = folder_id[:20] + "..." if len(folder_id) > 20 else folder_id
        lines.append(f"• {name}: {preview}")

    lines.append("\nДля добавления новых папок обратитесь к администратору.")
    await msg.reply_text("\n".join(lines))
