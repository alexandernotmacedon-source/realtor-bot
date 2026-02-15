"""Google Sheets integration for CRM (optional).

This integration is not required for the core bot flow, but is kept for future
CRM automation.

It uses a Service Account JSON credentials file.

Environment variables:
- GOOGLE_SHEETS_ID
- GOOGLE_SHEETS_CREDENTIALS_PATH (defaults to `service_account.json`)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:  # pragma: no cover
    gspread = None
    Credentials = None

from database.models import ClientModel


logger = logging.getLogger(__name__)


class GoogleSheetsCRM:
    """Simple CRM using Google Sheets (Service Account)."""

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    def __init__(
        self,
        spreadsheet_id: Optional[str] = None,
        credentials_path: Optional[Path] = None,
        worksheet_title: str = "Clients",
    ):
        if gspread is None or Credentials is None:
            raise RuntimeError(
                "gspread/google-auth are not installed. Install optional dependencies."
            )

        self.spreadsheet_id = spreadsheet_id or os.getenv("GOOGLE_SHEETS_ID", "")
        self.credentials_path = credentials_path or Path(
            os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "service_account.json")
        )
        self.worksheet_title = worksheet_title

        self.client = None
        self.spreadsheet = None
        self.worksheet = None

        self._connect()

    def _connect(self) -> None:
        """Connect to Google Sheets."""
        if not self.spreadsheet_id:
            raise ValueError("GOOGLE_SHEETS_ID is not configured")

        if not self.credentials_path.exists():
            raise FileNotFoundError(f"Service account file not found: {self.credentials_path}")

        credentials = Credentials.from_service_account_file(
            str(self.credentials_path), scopes=self.SCOPES
        )
        self.client = gspread.authorize(credentials)
        self.spreadsheet = self.client.open_by_key(self.spreadsheet_id)

        try:
            self.worksheet = self.spreadsheet.worksheet(self.worksheet_title)
        except Exception:
            self.worksheet = self.spreadsheet.add_worksheet(
                title=self.worksheet_title, rows=1000, cols=20
            )
            headers = [
                "Дата",
                "Имя",
                "Telegram",
                "Бюджет",
                "Площадь",
                "Район",
                "Комнаты",
                "Стадия",
                "Телефон",
                "Пожелания",
                "Статус",
                "Комиссия",
            ]
            self.worksheet.append_row(headers)

        logger.info("Connected to Google Sheets successfully")

    def add_client(self, client: ClientModel) -> bool:
        """Add new client to CRM."""
        try:
            row_data = [
                client.created_at.isoformat(),
                client.name,
                client.telegram_username or "",
                client.budget,
                client.size,
                client.location,
                client.rooms,
                client.ready_status,
                client.contact,
                client.notes,
                str(client.status),
                client.commission_amount or "",
            ]
            self.worksheet.append_row(row_data)
            logger.info("Client %s added to CRM", client.name)
            return True
        except Exception as e:
            logger.error("Failed to add client: %s", e, exc_info=True)
            return False

    def get_all_clients(self) -> list[dict[str, Any]]:
        """Get all clients from CRM."""
        try:
            return self.worksheet.get_all_records()
        except Exception as e:
            logger.error("Failed to get clients: %s", e, exc_info=True)
            return []

    def update_client_status(self, row_index: int, status: str) -> bool:
        """Update client status."""
        try:
            # Status column index depends on headers; here it's 11
            self.worksheet.update_cell(row_index, 11, status)
            logger.info("Client status updated to %s", status)
            return True
        except Exception as e:
            logger.error("Failed to update status: %s", e, exc_info=True)
            return False


__all__ = ["GoogleSheetsCRM"]
