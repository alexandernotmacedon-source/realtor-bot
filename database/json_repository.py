"""JSON-based repository implementation for backward compatibility."""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional
import asyncio
from datetime import datetime

import aiofiles

from database.models import RealtorModel, ClientModel
from database.repository import BaseRepository
from bot.config import ClientStatus


class JSONRepository(BaseRepository):
    """
    JSON file-based repository with async operations.
    
    Maintains backward compatibility with existing JSON database structure.
    Thread-safe using asyncio locks.
    """
    
    def __init__(self, db_path: Path):
        """
        Initialize JSON repository.
        
        Args:
            db_path: Path to JSON database file
        """
        self.db_path = Path(db_path)
        self._lock = asyncio.Lock()
        self._ensure_db_exists()
    
    def _ensure_db_exists(self) -> None:
        """Create database directory and file if not exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        if not self.db_path.exists():
            initial_data = {
                "realtors": {},
                "clients": {},
                "client_counter": 0
            }
            self.db_path.write_text(
                json.dumps(initial_data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
    
    async def _load_data(self) -> Dict:
        """Load data from JSON file asynchronously."""
        async with aiofiles.open(self.db_path, "r", encoding="utf-8") as f:
            content = await f.read()
            return json.loads(content)
    
    async def _save_data(self, data: Dict) -> None:
        """Save data to JSON file asynchronously."""
        async with aiofiles.open(self.db_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=2))
    
    # Realtor operations
    
    async def create_realtor(self, realtor: RealtorModel) -> RealtorModel:
        """
        Create a new realtor.
        
        Args:
            realtor: Realtor model instance
            
        Returns:
            Created realtor model
        """
        async with self._lock:
            data = await self._load_data()
            
            # Convert to dict with proper serialization
            realtor_dict = realtor.model_dump(mode="json")
            realtor_dict["created_at"] = realtor.created_at.isoformat()
            
            data["realtors"][str(realtor.id)] = realtor_dict
            await self._save_data(data)
            
            return realtor
    
    async def get_realtor(self, realtor_id: int) -> Optional[RealtorModel]:
        """
        Get realtor by ID.
        
        Args:
            realtor_id: Realtor Telegram ID
            
        Returns:
            Realtor model or None if not found
        """
        data = await self._load_data()
        realtor_data = data["realtors"].get(str(realtor_id))
        
        if not realtor_data:
            return None
        
        # Parse datetime
        if isinstance(realtor_data.get("created_at"), str):
            realtor_data["created_at"] = datetime.fromisoformat(
                realtor_data["created_at"]
            )
        
        return RealtorModel(**realtor_data)
    
    async def update_realtor(self, realtor: RealtorModel) -> RealtorModel:
        """
        Update realtor information.
        
        Args:
            realtor: Updated realtor model
            
        Returns:
            Updated realtor model
        """
        async with self._lock:
            data = await self._load_data()
            
            realtor_dict = realtor.model_dump(mode="json")
            realtor_dict["created_at"] = realtor.created_at.isoformat()
            
            data["realtors"][str(realtor.id)] = realtor_dict
            await self._save_data(data)
            
            return realtor
    
    async def get_all_realtors(self) -> List[RealtorModel]:
        """
        Get all realtors.
        
        Returns:
            List of realtor models
        """
        data = await self._load_data()
        realtors = []
        
        for realtor_data in data["realtors"].values():
            if isinstance(realtor_data.get("created_at"), str):
                realtor_data["created_at"] = datetime.fromisoformat(
                    realtor_data["created_at"]
                )
            realtors.append(RealtorModel(**realtor_data))
        
        return realtors
    
    # Client operations
    
    async def _get_next_client_id(self) -> int:
        """Get next client ID (internal)."""
        async with self._lock:
            data = await self._load_data()
            data["client_counter"] = data.get("client_counter", 0) + 1
            await self._save_data(data)
            return data["client_counter"]
    
    async def create_client(self, client: ClientModel) -> ClientModel:
        """
        Create a new client.
        
        Args:
            client: Client model instance
            
        Returns:
            Created client model with assigned ID
        """
        if client.id is None:
            client.id = await self._get_next_client_id()
        
        async with self._lock:
            data = await self._load_data()
            
            # Convert to dict with proper serialization
            client_dict = client.model_dump(mode="json")
            client_dict["created_at"] = client.created_at.isoformat()
            
            if client.commission_paid_date:
                client_dict["commission_paid_date"] = (
                    client.commission_paid_date.isoformat()
                )
            
            data["clients"][str(client.id)] = client_dict
            await self._save_data(data)
            
            return client
    
    async def get_client(self, client_id: int) -> Optional[ClientModel]:
        """
        Get client by ID.
        
        Args:
            client_id: Client ID
            
        Returns:
            Client model or None if not found
        """
        data = await self._load_data()
        client_data = data["clients"].get(str(client_id))
        
        if not client_data:
            return None
        
        # Parse datetime fields
        if isinstance(client_data.get("created_at"), str):
            client_data["created_at"] = datetime.fromisoformat(
                client_data["created_at"]
            )
        
        if client_data.get("commission_paid_date"):
            if isinstance(client_data["commission_paid_date"], str):
                client_data["commission_paid_date"] = datetime.fromisoformat(
                    client_data["commission_paid_date"]
                )
        
        # Convert status string to enum if needed
        if isinstance(client_data.get("status"), str):
            try:
                client_data["status"] = ClientStatus(client_data["status"])
            except ValueError:
                client_data["status"] = ClientStatus.NEW
        
        return ClientModel(**client_data)
    
    async def update_client(self, client: ClientModel) -> ClientModel:
        """
        Update client information.
        
        Args:
            client: Updated client model
            
        Returns:
            Updated client model
        """
        async with self._lock:
            data = await self._load_data()
            
            client_dict = client.model_dump(mode="json")
            client_dict["created_at"] = client.created_at.isoformat()
            
            if client.commission_paid_date:
                client_dict["commission_paid_date"] = (
                    client.commission_paid_date.isoformat()
                )
            
            data["clients"][str(client.id)] = client_dict
            await self._save_data(data)
            
            return client
    
    async def get_clients_by_realtor(
        self,
        realtor_id: int,
        status: Optional[str] = None
    ) -> List[ClientModel]:
        """
        Get all clients for a realtor.
        
        Args:
            realtor_id: Realtor ID
            status: Optional status filter
            
        Returns:
            List of client models
        """
        data = await self._load_data()
        clients = []
        
        for client_data in data["clients"].values():
            if client_data.get("realtor_id") != realtor_id:
                continue
            
            # Apply status filter
            if status and client_data.get("status") != status:
                continue
            
            # Parse datetime fields
            if isinstance(client_data.get("created_at"), str):
                client_data["created_at"] = datetime.fromisoformat(
                    client_data["created_at"]
                )
            
            if client_data.get("commission_paid_date"):
                if isinstance(client_data["commission_paid_date"], str):
                    client_data["commission_paid_date"] = datetime.fromisoformat(
                        client_data["commission_paid_date"]
                    )
            
            # Convert status
            if isinstance(client_data.get("status"), str):
                try:
                    client_data["status"] = ClientStatus(client_data["status"])
                except ValueError:
                    client_data["status"] = ClientStatus.NEW
            
            clients.append(ClientModel(**client_data))
        
        return clients
    
    async def get_client_by_telegram(
        self,
        telegram_id: int,
        realtor_id: int
    ) -> Optional[ClientModel]:
        """
        Get client by Telegram ID and realtor ID.
        
        Args:
            telegram_id: Client's Telegram ID
            realtor_id: Realtor ID
            
        Returns:
            Client model or None if not found
        """
        clients = await self.get_clients_by_realtor(realtor_id)
        
        for client in clients:
            if client.telegram_id == telegram_id:
                return client
        
        return None
    
    async def delete_client(self, client_id: int) -> bool:
        """
        Delete a client.
        
        Args:
            client_id: Client ID
            
        Returns:
            True if deleted, False if not found
        """
        async with self._lock:
            data = await self._load_data()
            
            if str(client_id) not in data["clients"]:
                return False
            
            del data["clients"][str(client_id)]
            await self._save_data(data)
            
            return True


__all__ = ["JSONRepository"]
