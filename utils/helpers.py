"""Utility helpers.

This module contains small, side-effect-free helpers used across the bot.
"""

from __future__ import annotations

import re
from typing import Optional


_SANITIZE_ALLOWED = re.compile(r"[^\w\s\-+@().,/:#№%&*'\"!?$€₾₽]", re.UNICODE)


def sanitize_user_text(text: str, max_len: int = 1000) -> str:
    """Sanitize user input to a safe subset.

    Args:
        text: Raw user-provided text.
        max_len: Max length of the resulting string.

    Returns:
        Sanitized string.
    """
    if text is None:
        return ""

    cleaned = text.strip()
    cleaned = _SANITIZE_ALLOWED.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:max_len]


def parse_budget_amount(text: str) -> Optional[float]:
    """Parse first numeric value from budget text.

    Args:
        text: Budget text.

    Returns:
        Parsed numeric value or None.
    """
    if not text:
        return None

    numbers = re.findall(r"\d+[\d\s,.]*", text)
    if not numbers:
        return None

    num_str = numbers[0].replace(" ", "").replace(",", ".")
    try:
        return float(num_str)
    except ValueError:
        return None


def format_client_summary(client_info: dict) -> str:
    """Format client info for display."""
    return (
        f"👤 {client_info.get('name', 'Клиент')}\n"
        f"💰 {client_info.get('budget', 'Бюджет не указан')}\n"
        f"📐 {client_info.get('size', 'Площадь не указана')}\n"
        f"📍 {client_info.get('location', 'Район не указан')}\n"
        f"🛏 {client_info.get('rooms', 'Комнаты не указаны')}\n"
        f"🏗 {client_info.get('ready_status', 'Стадия не указана')}\n"
        f"📞 {client_info.get('contact', 'Контакт не указан')}\n"
    )


__all__ = ["sanitize_user_text", "parse_budget_amount", "format_client_summary"]
