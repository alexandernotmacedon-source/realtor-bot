"""Database facade for backward compatibility.

The refactor introduces an async Repository layer (see `database/repository.py`).
Old code used a synchronous `Database` class.

This module keeps a `Database` class with similar method names but implemented
using the configured repository.

New code should depend on `BaseRepository` via `Container.get_repository()`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Optional

from bot.config import settings
from core.container import Container
from database.models import RealtorModel, ClientModel


class Database:
    """Backward-compatible database facade."""

    def __init__(self, db_path: str | None = None):
        """Initialize database facade.

        Args:
            db_path: Optional override of JSON db path.
        """
        if db_path is not None:
            # keep backward compatibility: allow overriding path
            settings.database_path = Path(db_path)
            Container.reset()

        self._repo = Container.get_repository()

    # Realtor operations
    async def get_realtor(self, realtor_id: int) -> Optional[RealtorModel]:
        return await self._repo.get_realtor(realtor_id)

    async def create_realtor(self, realtor: RealtorModel) -> RealtorModel:
        return await self._repo.create_realtor(realtor)

    async def update_realtor(self, realtor: RealtorModel) -> RealtorModel:
        return await self._repo.update_realtor(realtor)

    async def get_all_realtors(self) -> List[RealtorModel]:
        return await self._repo.get_all_realtors()

    # Client operations
    async def create_client(self, client: ClientModel) -> ClientModel:
        return await self._repo.create_client(client)

    async def get_client(self, client_id: int) -> Optional[ClientModel]:
        return await self._repo.get_client(client_id)

    async def get_clients_by_realtor(self, realtor_id: int) -> List[ClientModel]:
        return await self._repo.get_clients_by_realtor(realtor_id)

    async def get_client_by_telegram(self, telegram_id: int, realtor_id: int) -> Optional[ClientModel]:
        return await self._repo.get_client_by_telegram(telegram_id, realtor_id)

    async def update_client(self, client: ClientModel) -> ClientModel:
        return await self._repo.update_client(client)


# --- Sync helpers for legacy code ---

def _run(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        raise RuntimeError("Synchronous DB access is not allowed in async context")

    return asyncio.run(coro)


class SyncDatabase(Database):
    """Synchronous adapter (use only outside async handlers)."""

    def get_realtor(self, realtor_id: int):  # type: ignore[override]
        return _run(super().get_realtor(realtor_id))

    def create_realtor(self, realtor: RealtorModel):  # type: ignore[override]
        return _run(super().create_realtor(realtor))

    def update_realtor(self, realtor: RealtorModel):  # type: ignore[override]
        return _run(super().update_realtor(realtor))

    def get_all_realtors(self):  # type: ignore[override]
        return _run(super().get_all_realtors())

    def create_client(self, client: ClientModel):  # type: ignore[override]
        return _run(super().create_client(client))

    def get_client(self, client_id: int):  # type: ignore[override]
        return _run(super().get_client(client_id))

    def get_clients_by_realtor(self, realtor_id: int):  # type: ignore[override]
        return _run(super().get_clients_by_realtor(realtor_id))

    def get_client_by_telegram(self, telegram_id: int, realtor_id: int):  # type: ignore[override]
        return _run(super().get_client_by_telegram(telegram_id, realtor_id))

    def update_client(self, client: ClientModel):  # type: ignore[override]
        return _run(super().update_client(client))


__all__ = ["Database", "SyncDatabase"]
