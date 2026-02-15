"""Backward-compatible LLM handler.

The original project used synchronous helper functions. This refactor introduces
`core.llm_service.LLMService` with provider abstraction, streaming, retries, and
fallback chain.

This module keeps the old public function names but implements them using the
new async service.

New code should prefer using `Container.get_llm_service()` directly.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from core.container import Container


async def get_llm_response_async(messages: List[Dict], model: Optional[str] = None) -> Optional[str]:
    """Async LLM response."""
    service = Container.get_llm_service()
    # model param kept for compatibility; service is already configured
    return await service.generate_response(messages=messages)


def get_llm_response(messages: List[Dict], model: str = "gpt-4o-mini") -> Optional[str]:
    """Sync wrapper for compatibility (NOT recommended in async handlers)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # In async context user should call async variant.
        raise RuntimeError("Use get_llm_response_async inside async handlers")

    return asyncio.run(get_llm_response_async(messages=messages, model=model))


async def extract_client_info_async(conversation_history: List[Dict]) -> Dict:
    """Async extraction of client info."""
    service = Container.get_llm_service()
    return await service.extract_client_info(conversation_history=conversation_history)


def extract_client_info(conversation_history: List[Dict]) -> Dict:
    """Sync wrapper for compatibility."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        raise RuntimeError("Use extract_client_info_async inside async handlers")

    return asyncio.run(extract_client_info_async(conversation_history=conversation_history))


def should_end_conversation(conversation_history: List[Dict]) -> bool:
    """Compatibility helper."""
    info = extract_client_info(conversation_history)
    return bool(info.get("is_complete", False))


def build_summary(info: Dict) -> str:
    """Build a human-readable summary."""
    field_names = {
        "budget": "💰 Бюджет",
        "size": "📐 Площадь",
        "location": "📍 Район",
        "rooms": "🛏 Комнаты",
        "ready_status": "🏗 Стадия",
        "contact": "📞 Контакт",
        "notes": "📝 Пожелания",
    }

    lines = []
    for field, label in field_names.items():
        value = info.get(field)
        if value:
            lines.append(f"{label}: {value}")

    return "\n".join(lines) if lines else "Информация не указана"


async def transcribe_audio_async(audio_file_path: str) -> Optional[str]:
    """Async transcription."""
    service = Container.get_llm_service()
    return await service.transcribe_audio(audio_path=audio_file_path)


def transcribe_audio(audio_file_path: str) -> Optional[str]:
    """Sync wrapper for compatibility."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        raise RuntimeError("Use transcribe_audio_async inside async handlers")

    return asyncio.run(transcribe_audio_async(audio_file_path))


__all__ = [
    "get_llm_response",
    "get_llm_response_async",
    "extract_client_info",
    "extract_client_info_async",
    "should_end_conversation",
    "build_summary",
    "transcribe_audio",
    "transcribe_audio_async",
]
