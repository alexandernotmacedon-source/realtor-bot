"""Data models with Pydantic validation."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, validator, field_validator

from bot.config import ClientStatus


class RealtorModel(BaseModel):
    """Realtor account data with validation."""
    
    id: int = Field(..., description="Telegram ID of realtor")
    username: Optional[str] = Field(default=None, description="Telegram username")
    full_name: str = Field(..., min_length=1, description="Full name")
    phone: Optional[str] = Field(default=None, description="Contact phone")
    company_name: Optional[str] = Field(default=None, description="Company name")
    
    # Google integrations
    google_drive_folder_id: Optional[str] = Field(
        default=None,
        description="Root folder for developer data"
    )
    google_sheets_id: Optional[str] = Field(
        default=None,
        description="CRM spreadsheet ID"
    )
    google_credentials_path: Optional[str] = Field(
        default=None,
        description="Path to Google credentials"
    )
    
    # Telegram settings
    notification_chat_id: Optional[str] = Field(
        default=None,
        description="Chat for new leads"
    )
    public_chat_id: Optional[str] = Field(
        default=None,
        description="Chat for clients"
    )
    
    # Bot settings
    welcome_message: Optional[str] = Field(
        default=None,
        description="Custom welcome message"
    )
    questions_template: str = Field(
        default="default",
        description="Question template to use"
    )
    
    # Status
    is_active: bool = Field(default=True, description="Account is active")
    is_admin: bool = Field(default=False, description="Admin privileges")
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="Creation timestamp"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 123456789,
                "username": "john_realtor",
                "full_name": "John Doe",
                "phone": "+995555123456",
                "company_name": "Batumi Realty",
                "is_active": True,
                "is_admin": False
            }
        }
    }
    
    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        """Validate phone number format."""
        if v is None:
            return v
        
        # Remove spaces and common separators
        cleaned = "".join(c for c in v if c.isdigit() or c == "+")
        
        # Basic validation: should start with + and have 10-15 digits
        if cleaned and not (cleaned.startswith("+") and 10 <= len(cleaned) <= 16):
            raise ValueError(
                "Phone must start with + and contain 10-15 digits"
            )
        
        return cleaned or None


class ClientModel(BaseModel):
    """Client data model with validation."""
    
    id: Optional[int] = Field(default=None, description="Unique client ID")
    telegram_id: int = Field(..., description="Telegram user ID")
    realtor_id: int = Field(..., description="Assigned realtor ID")
    
    # Personal info
    telegram_username: Optional[str] = Field(
        default=None,
        description="Telegram username"
    )
    name: str = Field(default="", description="Client name")
    contact: str = Field(default="", description="Contact phone/telegram")
    
    # Requirements
    budget: str = Field(default="", description="Budget in GEL")
    size: str = Field(default="", description="Desired size in m²")
    location: str = Field(default="", description="Preferred location")
    rooms: str = Field(default="", description="Number of rooms")
    ready_status: str = Field(default="", description="Construction readiness")
    notes: str = Field(default="", description="Additional notes")
    
    # Metadata
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="Lead creation timestamp"
    )
    status: ClientStatus = Field(
        default=ClientStatus.NEW,
        description="Lead status"
    )
    commission_amount: Optional[float] = Field(
        default=None,
        ge=0,
        description="Commission amount if closed"
    )
    commission_paid_date: Optional[datetime] = Field(
        default=None,
        description="Commission payment date"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "telegram_id": 987654321,
                "realtor_id": 123456789,
                "name": "Jane Smith",
                "budget": "150000-200000",
                "size": "60-80",
                "location": "New Boulevard",
                "rooms": "2",
                "ready_status": "Ready or white frame",
                "contact": "+995555999888",
                "status": "new"
            }
        },
        "use_enum_values": True
    }
    
    @field_validator("budget")
    @classmethod
    def sanitize_budget(cls, v: str) -> str:
        """Sanitize budget input to prevent injection."""
        if not v:
            return v
        
        # Keep only alphanumeric, spaces, and common separators
        return "".join(
            c for c in v if c.isalnum() or c in " -+.,абвгдежзийклмнопрстуфхцчшщъыьэюя"
        )[:200]
    
    @field_validator("notes")
    @classmethod
    def sanitize_notes(cls, v: str) -> str:
        """Sanitize notes to prevent injection."""
        if not v:
            return v
        
        # Limit length and remove potentially dangerous characters
        return v[:1000]
    
    def to_summary(self) -> str:
        """Generate human-readable summary."""
        lines = []
        
        if self.name:
            lines.append(f"👤 Имя: {self.name}")
        if self.budget:
            lines.append(f"💰 Бюджет: {self.budget}")
        if self.size:
            lines.append(f"📐 Площадь: {self.size}")
        if self.location:
            lines.append(f"📍 Район: {self.location}")
        if self.rooms:
            lines.append(f"🛏 Комнаты: {self.rooms}")
        if self.ready_status:
            lines.append(f"🏗 Стадия: {self.ready_status}")
        if self.contact:
            lines.append(f"📞 Контакт: {self.contact}")
        if self.notes:
            lines.append(f"📝 Пожелания: {self.notes[:100]}...")
        
        return "\n".join(lines) if lines else "Информация не указана"


class ConversationContextModel(BaseModel):
    """Model for storing conversation context."""
    
    user_id: int = Field(..., description="User Telegram ID")
    realtor_id: int = Field(..., description="Assigned realtor ID")
    messages: list[dict] = Field(
        default_factory=list,
        description="Message history"
    )
    extracted_info: dict = Field(
        default_factory=dict,
        description="Extracted client information"
    )
    last_updated: datetime = Field(
        default_factory=datetime.now,
        description="Last update timestamp"
    )
    
    def add_message(self, role: str, content: str) -> None:
        """Add message to conversation history."""
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        self.last_updated = datetime.now()


# Export models
__all__ = [
    "RealtorModel",
    "ClientModel",
    "ConversationContextModel",
]
