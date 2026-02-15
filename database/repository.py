"""Repository pattern for database operations."""
from abc import ABC, abstractmethod
from typing import List, Optional

from database.models import RealtorModel, ClientModel


class BaseRepository(ABC):
    """Abstract base repository interface."""
    
    @abstractmethod
    async def create_realtor(self, realtor: RealtorModel) -> RealtorModel:
        """Create a new realtor."""
        pass
    
    @abstractmethod
    async def get_realtor(self, realtor_id: int) -> Optional[RealtorModel]:
        """Get realtor by ID."""
        pass
    
    @abstractmethod
    async def update_realtor(self, realtor: RealtorModel) -> RealtorModel:
        """Update realtor information."""
        pass
    
    @abstractmethod
    async def get_all_realtors(self) -> List[RealtorModel]:
        """Get all realtors."""
        pass
    
    @abstractmethod
    async def create_client(self, client: ClientModel) -> ClientModel:
        """Create a new client."""
        pass
    
    @abstractmethod
    async def get_client(self, client_id: int) -> Optional[ClientModel]:
        """Get client by ID."""
        pass
    
    @abstractmethod
    async def update_client(self, client: ClientModel) -> ClientModel:
        """Update client information."""
        pass
    
    @abstractmethod
    async def get_clients_by_realtor(
        self,
        realtor_id: int,
        status: Optional[str] = None
    ) -> List[ClientModel]:
        """Get all clients for a realtor, optionally filtered by status."""
        pass
    
    @abstractmethod
    async def get_client_by_telegram(
        self,
        telegram_id: int,
        realtor_id: int
    ) -> Optional[ClientModel]:
        """Get client by Telegram ID and realtor ID."""
        pass
    
    @abstractmethod
    async def delete_client(self, client_id: int) -> bool:
        """Delete a client."""
        pass


__all__ = ["BaseRepository"]
