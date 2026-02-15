"""Database package.

Exports:
- Pydantic models
- Repository interfaces and JSON implementation

The legacy `Database` facade remains available for backward compatibility.
Import it directly: `from database.db import Database`
"""

from database.models import RealtorModel, ClientModel
from database.repository import BaseRepository
from database.json_repository import JSONRepository

__all__ = [
    "RealtorModel",
    "ClientModel",
    "BaseRepository",
    "JSONRepository",
]
