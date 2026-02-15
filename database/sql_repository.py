"""SQLAlchemy repository (scaffold).

This file is a preparation layer for migrating from JSON to SQLite/PostgreSQL.

It intentionally provides only a minimal skeleton so that the project structure
is ready for extension.

To implement:
- SQLAlchemy models
- async session management
- migrations (alembic)
- full BaseRepository methods
"""

from __future__ import annotations

from typing import List, Optional

from database.repository import BaseRepository
from database.models import RealtorModel, ClientModel


class SQLRepository(BaseRepository):
    """Scaffold for SQL backend repository."""

    def __init__(self, database_url: str):
        self.database_url = database_url

    async def create_realtor(self, realtor: RealtorModel) -> RealtorModel:
        raise NotImplementedError

    async def get_realtor(self, realtor_id: int) -> Optional[RealtorModel]:
        raise NotImplementedError

    async def update_realtor(self, realtor: RealtorModel) -> RealtorModel:
        raise NotImplementedError

    async def get_all_realtors(self) -> List[RealtorModel]:
        raise NotImplementedError

    async def create_client(self, client: ClientModel) -> ClientModel:
        raise NotImplementedError

    async def get_client(self, client_id: int) -> Optional[ClientModel]:
        raise NotImplementedError

    async def update_client(self, client: ClientModel) -> ClientModel:
        raise NotImplementedError

    async def get_clients_by_realtor(
        self, realtor_id: int, status: Optional[str] = None
    ) -> List[ClientModel]:
        raise NotImplementedError

    async def get_client_by_telegram(
        self, telegram_id: int, realtor_id: int
    ) -> Optional[ClientModel]:
        raise NotImplementedError

    async def delete_client(self, client_id: int) -> bool:
        raise NotImplementedError


__all__ = ["SQLRepository"]
