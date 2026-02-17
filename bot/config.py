"""Configuration management with pydantic-settings."""
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConversationState(Enum):
    """Conversation states for type-safe state management."""
    # Client states
    CLIENT_START = 0
    CLIENT_BUDGET = 1
    CLIENT_SIZE = 2
    CLIENT_LOCATION = 3
    CLIENT_ROOMS = 4
    CLIENT_READY_STATUS = 5
    CLIENT_CONTACT = 6
    CLIENT_NOTES = 7
    CLIENT_COMPLETE = 8
    
    # Realtor states
    REALTOR_REGISTER = 10
    REALTOR_PHONE = 11
    REALTOR_COMPANY = 12
    REALTOR_DRIVE_SETUP = 13
    REALTOR_CRM_SETUP = 14
    REALTOR_COMPLETE = 15


class ClientStatus(Enum):
    """Client lead statuses."""
    DRAFT = "draft"  # Temporary, during conversation
    NEW = "new"
    CONTACTED = "contacted"
    VIEWING = "viewing"
    CLOSED = "closed"
    REJECTED = "rejected"


class LLMProvider(Enum):
    """Supported LLM providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class DatabaseBackend(Enum):
    """Supported database backends."""
    JSON = "json"
    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"


class Settings(BaseSettings):
    """Application settings with validation."""
    
    # Telegram
    telegram_bot_token: str = Field(..., description="Telegram bot token")
    bot_admin_id: int = Field(default=0, description="Admin user ID")
    
    # Database
    database_backend: DatabaseBackend = Field(
        default=DatabaseBackend.JSON,
        description="Database backend type"
    )
    database_path: Path = Field(
        default=Path("./data/realtor_bot.json"),
        description="Path to database file"
    )
    database_url: Optional[str] = Field(
        default=None,
        description="Database URL for SQL backends (e.g., postgresql://...)"
    )
    
    # LLM Configuration
    llm_provider: LLMProvider = Field(
        default=LLMProvider.OPENAI,
        description="Primary LLM provider"
    )
    llm_fallback_providers: list[LLMProvider] = Field(
        default_factory=lambda: [LLMProvider.ANTHROPIC],
        description="Fallback LLM providers"
    )
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API key")
    anthropic_api_key: Optional[str] = Field(
        default=None,
        description="Anthropic API key"
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        description="Default LLM model"
    )
    llm_temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="LLM temperature"
    )
    llm_max_tokens: int = Field(
        default=500,
        gt=0,
        description="Max tokens for LLM response"
    )
    llm_stream_responses: bool = Field(
        default=False,
        description="Enable streaming for LLM responses"
    )
    
    # Google Integration
    google_credentials_path: Path = Field(
        default=Path("credentials.json"),
        description="Path to Google OAuth credentials"
    )
    google_token_path: Path = Field(
        default=Path("token.pickle"),
        description="Path to Google OAuth token"
    )
    google_drive_cache_ttl: int = Field(
        default=3600,
        gt=0,
        description="Google Drive cache TTL in seconds"
    )
    
    # Rate Limiting
    rate_limit_enabled: bool = Field(
        default=True,
        description="Enable rate limiting"
    )
    rate_limit_requests: int = Field(
        default=10,
        gt=0,
        description="Max requests per window"
    )
    rate_limit_window: int = Field(
        default=60,
        gt=0,
        description="Rate limit window in seconds"
    )
    
    # Application
    debug: bool = Field(default=False, description="Debug mode")
    log_level: str = Field(default="INFO", description="Logging level")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    @field_validator("telegram_bot_token")
    @classmethod
    def validate_telegram_token(cls, v: str) -> str:
        """Validate Telegram bot token format."""
        if not v or v == "your_bot_token_here":
            raise ValueError("TELEGRAM_BOT_TOKEN must be set in .env file")

        parts = v.split(":")
        if len(parts) != 2 or not parts[0].isdigit():
            raise ValueError("Invalid Telegram bot token format")

        return v

    @field_validator("database_url", mode="after")
    @classmethod
    def validate_database_url(cls, v: Optional[str], info):
        """Validate database URL if SQL backend is used."""
        backend = info.data.get("database_backend")

        if backend in (DatabaseBackend.SQLITE, DatabaseBackend.POSTGRESQL):
            if not v:
                if backend == DatabaseBackend.SQLITE:
                    return "sqlite+aiosqlite:///./data/realtor_bot.db"
                raise ValueError(f"database_url is required for {backend.value} backend")

        return v

    # NOTE: We intentionally do not hard-require provider API keys at startup.
    # The bot can still run without LLM keys (it will fallback to simple prompts).
    
    @property
    def is_sql_backend(self) -> bool:
        """Check if using SQL backend."""
        return self.database_backend in (
            DatabaseBackend.SQLITE,
            DatabaseBackend.POSTGRESQL
        )


# Global settings instance
settings = Settings()


# Message templates
class MessageTemplates:
    """Message templates for the bot."""
    
    REALTOR_WELCOME = """
👋 Добро пожаловать, риелтор!

Я помогу автоматизировать работу с клиентами.

Что я умею:
• Собирать заявки от клиентов
• Сохранять в вашу CRM (Google Sheets)
• Уведомлять о новых лидах
• Управлять клиентской базой

Для начала работы нужно настроить подключение.
Отправьте /register чтобы зарегистрироваться.
"""
    
    CLIENT_WELCOME = """
👋 Здравствуйте! Меня зовут {realtor_name}.

Я помогу подобрать вам идеальную квартиру или апартаменты в Батуми и пригороде.

🇬🇪 Специализация: недвижимость в Грузии
💰 Бюджет: в лари (GEL)
📐 Площадь: в квадратных метрах (м²)

Чтобы найти лучший вариант, задам несколько вопросов. 
Это займёт 2-3 минуты.

Готовы начать? Просто отвечайте на вопросы сообщениями.
"""
    
    CLIENT_COMPLETION = """
✅ Спасибо! Я получил всю информацию.

📋 Ваш запрос:
{summary}

Я подберу для вас актуальные варианты и пришлю на рассмотрение. После этого можно обсудить детали и договориться о просмотре.
"""
    
    @staticmethod
    def format_client_welcome(realtor_name: str) -> str:
        """Format client welcome message."""
        return MessageTemplates.CLIENT_WELCOME.format(realtor_name=realtor_name)
    
    @staticmethod
    def format_client_completion(summary: str, realtor_phone: str | None = None) -> str:
        """Format client completion message.
        
        Args:
            summary: Client requirements summary
            realtor_phone: Kept for backward compatibility, not shown to client
        """
        return MessageTemplates.CLIENT_COMPLETION.format(
            summary=summary,
            realtor_phone=realtor_phone or ""
        )


# Export commonly used objects
__all__ = [
    "settings",
    "Settings",
    "ConversationState",
    "ClientStatus",
    "LLMProvider",
    "DatabaseBackend",
    "MessageTemplates",
]
