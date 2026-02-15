"""
Dependency Injection container for centralized dependency management.

Provides factory methods for creating and accessing service instances.
"""
from functools import lru_cache
from typing import Optional

from bot.config import settings, DatabaseBackend
from database.repository import BaseRepository
from database.json_repository import JSONRepository


class Container:
    """
    Dependency injection container.
    
    Provides centralized access to application dependencies with lazy initialization.
    Implements singleton pattern for shared resources.
    """
    
    _repository: Optional[BaseRepository] = None
    _llm_service: Optional[object] = None
    _drive_manager: Optional[object] = None
    _inventory_matcher: Optional[object] = None
    
    @classmethod
    def get_repository(cls) -> BaseRepository:
        """
        Get database repository instance.
        
        Returns repository based on configured backend (JSON/SQLite/PostgreSQL).
        Lazy initialization with singleton pattern.
        
        Returns:
            Repository instance
        """
        if cls._repository is None:
            if settings.database_backend == DatabaseBackend.JSON:
                cls._repository = JSONRepository(settings.database_path)
            elif settings.database_backend == DatabaseBackend.SQLITE:
                # Future implementation
                from database.sql_repository import SQLRepository
                cls._repository = SQLRepository(settings.database_url)
            elif settings.database_backend == DatabaseBackend.POSTGRESQL:
                # Future implementation
                from database.sql_repository import SQLRepository
                cls._repository = SQLRepository(settings.database_url)
            else:
                raise ValueError(f"Unsupported database backend: {settings.database_backend}")
        
        return cls._repository
    
    @classmethod
    def get_llm_service(cls) -> object:
        """
        Get LLM service instance.
        
        Returns LLM service with configured provider and fallback chain.
        Lazy initialization with singleton pattern.
        
        Returns:
            LLM service instance
        """
        if cls._llm_service is None:
            from core.llm_service import LLMService
            cls._llm_service = LLMService(
                primary_provider=settings.llm_provider,
                fallback_providers=settings.llm_fallback_providers,
                model=settings.llm_model,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
                stream=settings.llm_stream_responses
            )
        
        return cls._llm_service
    
    @classmethod
    def get_drive_manager(cls) -> object:
        """
        Get Google Drive manager instance.
        
        Returns:
            Drive manager instance
        """
        if cls._drive_manager is None:
            from integrations.google_drive import GoogleDriveManager
            cls._drive_manager = GoogleDriveManager(
                credentials_path=settings.google_credentials_path,
                token_path=settings.google_token_path,
                cache_ttl=settings.google_drive_cache_ttl
            )
        
        return cls._drive_manager
    
    @classmethod
    def get_inventory_matcher(cls) -> object:
        """
        Get inventory matcher instance.
        
        Returns:
            Inventory matcher instance
        """
        if cls._inventory_matcher is None:
            from integrations.inventory import InventoryMatcher
            cls._inventory_matcher = InventoryMatcher(
                drive_manager=cls.get_drive_manager()
            )
        
        return cls._inventory_matcher
    
    @classmethod
    def reset(cls) -> None:
        """
        Reset all cached instances.
        
        Useful for testing and re-initialization.
        """
        cls._repository = None
        cls._llm_service = None
        cls._drive_manager = None
        cls._inventory_matcher = None


# Convenience functions for easy access
def get_repository() -> BaseRepository:
    """Get repository instance."""
    return Container.get_repository()


def get_llm_service():
    """Get LLM service instance."""
    return Container.get_llm_service()


def get_drive_manager():
    """Get Drive manager instance."""
    return Container.get_drive_manager()


def get_inventory_matcher():
    """Get inventory matcher instance."""
    return Container.get_inventory_matcher()


__all__ = [
    "Container",
    "get_repository",
    "get_llm_service",
    "get_drive_manager",
    "get_inventory_matcher",
]
