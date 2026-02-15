"""Google Drive integration for reading developer inventory.

This module provides a `GoogleDriveManager` with:
- OAuth authorization (installed app / OOB)
- Drive API v3 client building
- Retrying with exponential backoff
- Caching scan results (TTL)
- Reading Excel (.xlsx/.xls) and CSV files

Note:
Google API calls are synchronous; when used from async handlers, run them via
`asyncio.to_thread(...)`.
"""

from __future__ import annotations

import logging
import os
import pickle
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd
from cachetools import TTLCache
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


logger = logging.getLogger(__name__)

# Google Drive API scopes
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Folder mappings (developer name -> folder ID)
DEFAULT_FOLDERS: Dict[str, str] = {
    "developer_1": "1zstD8eqbp6S_k-Dc-0ptlSF_etd_WNY8",
    "developer_2": "1uY91KJWgeAA-pu4weJddDwb54lgeKErJ",
}


@dataclass(frozen=True)
class DriveFile:
    """Drive file metadata."""

    id: str
    name: str
    mime_type: str
    modified_time: str
    web_view_link: Optional[str] = None


class GoogleDriveManager:
    """Manages Google Drive access for developer inventory."""

    def __init__(
        self,
        credentials_path: Path,
        token_path: Path,
        cache_ttl: int = 3600,
        folders: Optional[Dict[str, str]] = None,
    ):
        """Initialize manager.

        Args:
            credentials_path: Path to OAuth client secrets JSON.
            token_path: Path to token pickle file.
            cache_ttl: Cache TTL for scans in seconds.
            folders: Optional mapping (developer_name -> folder_id).
        """

        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self.service = None

        self.folders: Dict[str, str] = folders.copy() if folders else DEFAULT_FOLDERS.copy()

        # Caches
        # - scan_cache: developer_name -> list[DriveFile]
        self._scan_cache: TTLCache[str, List[DriveFile]] = TTLCache(maxsize=256, ttl=cache_ttl)

        logger.info(
            "GoogleDriveManager initialized (credentials=%s, token=%s, cache_ttl=%ss)",
            self.credentials_path,
            self.token_path,
            cache_ttl,
        )

    def add_folder(self, developer_name: str, folder_id: str) -> None:
        """Add or update a developer folder."""
        self.folders[developer_name] = folder_id
        # Invalidate cache for that developer
        self._scan_cache.pop(developer_name, None)
        logger.info("Added/updated folder for %s: %s", developer_name, folder_id)

    def is_authorized(self) -> bool:
        """Check whether an OAuth token exists."""
        return self.token_path.exists()

    def get_auth_url(self) -> str:
        """Generate OAuth authorization URL."""
        if not self.credentials_path.exists():
            raise FileNotFoundError(
                f"credentials.json not found at {self.credentials_path}. "
                "Download from Google Cloud Console."
            )

        flow = Flow.from_client_secrets_file(
            str(self.credentials_path),
            scopes=SCOPES,
            redirect_uri="urn:ietf:wg:oauth:2.0:oob",  # OOB for CLI bots
        )

        auth_url, _ = flow.authorization_url(prompt="consent")
        return auth_url

    def complete_auth(self, auth_code: str) -> bool:
        """Complete OAuth flow with authorization code."""
        try:
            flow = Flow.from_client_secrets_file(
                str(self.credentials_path),
                scopes=SCOPES,
                redirect_uri="urn:ietf:wg:oauth:2.0:oob",
            )

            flow.fetch_token(code=auth_code)
            credentials = flow.credentials

            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_path, "wb") as token:
                pickle.dump(credentials, token)

            self._build_service(credentials)
            logger.info("Google Drive authorization completed successfully")
            return True

        except Exception as e:
            logger.error("Failed to complete auth: %s", e, exc_info=True)
            return False

    def authenticate(self) -> bool:
        """Authenticate using stored token (refresh if needed)."""
        credentials: Optional[Credentials] = None

        if self.token_path.exists():
            with open(self.token_path, "rb") as token:
                credentials = pickle.load(token)

        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                with open(self.token_path, "wb") as token:
                    pickle.dump(credentials, token)
            except Exception as e:
                logger.error("Failed to refresh token: %s", e, exc_info=True)
                return False

        if not credentials or not credentials.valid:
            logger.warning("No valid credentials. Use get_auth_url() to start OAuth flow.")
            return False

        self._build_service(credentials)
        return True

    def _build_service(self, credentials: Credentials) -> None:
        """Build Drive service client."""
        self.service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    def _ensure_service(self) -> bool:
        if self.service is not None:
            return True
        return self.authenticate()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(HttpError),
        reraise=True,
    )
    def list_files_in_folder(
        self,
        folder_id: str,
        mime_types: Optional[Iterable[str]] = None,
        page_size: int = 200,
    ) -> List[DriveFile]:
        """List files in a folder.

        Args:
            folder_id: Drive folder ID.
            mime_types: Optional iterable of mime types to filter.
            page_size: Page size for listing.

        Returns:
            List of DriveFile.
        """

        if not self._ensure_service():
            return []

        query = f"'{folder_id}' in parents and trashed = false"
        if mime_types:
            types = " or ".join([f"mimeType='{t}'" for t in mime_types])
            query += f" and ({types})"

        results = (
            self.service.files()
            .list(
                q=query,
                pageSize=page_size,
                fields="files(id,name,mimeType,modifiedTime,webViewLink)",
            )
            .execute()
        )

        files: List[DriveFile] = []
        for f in results.get("files", []):
            files.append(
                DriveFile(
                    id=f["id"],
                    name=f.get("name", ""),
                    mime_type=f.get("mimeType", ""),
                    modified_time=f.get("modifiedTime", ""),
                    web_view_link=f.get("webViewLink"),
                )
            )

        return files

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(HttpError),
        reraise=True,
    )
    def download_file(self, file_id: str, local_path: Path) -> bool:
        """Download a file from Drive."""
        if not self._ensure_service():
            return False

        request = self.service.files().get_media(fileId=file_id)
        content = request.execute()
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(content)
        return True

    def read_tabular_file(self, file: DriveFile) -> Optional[pd.DataFrame]:
        """Read Excel/CSV file from Drive into a DataFrame.

        Supports:
        - .xlsx (openpyxl)
        - .xls (xlrd)
        - text/csv

        Args:
            file: DriveFile metadata.

        Returns:
            DataFrame or None.
        """

        suffix = ".xlsx"
        name_lower = file.name.lower()

        if name_lower.endswith(".csv") or file.mime_type == "text/csv":
            suffix = ".csv"
        elif name_lower.endswith(".xls"):
            suffix = ".xls"
        elif name_lower.endswith(".xlsx"):
            suffix = ".xlsx"

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            ok = self.download_file(file.id, tmp_path)
            if not ok:
                return None

            if suffix == ".csv":
                try:
                    return pd.read_csv(tmp_path)
                except Exception:
                    # Common alternative delimiter
                    return pd.read_csv(tmp_path, sep=";")

            # Excel
            engines = ["openpyxl", "xlrd"]
            for engine in engines:
                try:
                    return pd.read_excel(tmp_path, engine=engine)
                except Exception:
                    continue

            return None

        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    def scan_all_folders(self, use_cache: bool = True) -> Dict[str, List[DriveFile]]:
        """Scan all configured developer folders for inventory files.

        Args:
            use_cache: Use cached scan results if available.

        Returns:
            Mapping developer_name -> list of DriveFile.
        """

        inventory: Dict[str, List[DriveFile]] = {}

        # mime types: xlsx, xls, csv
        excel_mimes = [
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
            "text/csv",
        ]

        for developer_name, folder_id in self.folders.items():
            if use_cache and developer_name in self._scan_cache:
                inventory[developer_name] = self._scan_cache[developer_name]
                continue

            try:
                files = self.list_files_in_folder(folder_id, mime_types=excel_mimes)
            except HttpError as e:
                logger.error("Failed to scan folder for %s: %s", developer_name, e)
                files = []

            inventory[developer_name] = files
            self._scan_cache[developer_name] = files
            logger.info("Found %s files in %s", len(files), developer_name)

        return inventory

    def get_inventory_data(self, use_cache: bool = True) -> Dict[str, pd.DataFrame]:
        """Get inventory dataframes for each developer.

        Picks the most recently modified file in each folder.

        Args:
            use_cache: Whether to use scan cache.

        Returns:
            Mapping developer_name -> DataFrame.
        """

        data: Dict[str, pd.DataFrame] = {}
        inventory_files = self.scan_all_folders(use_cache=use_cache)

        for developer_name, files in inventory_files.items():
            if not files:
                continue

            most_recent = max(files, key=lambda x: x.modified_time or "")
            df = self.read_tabular_file(most_recent)

            if df is not None:
                data[developer_name] = df
                logger.info("Loaded %s rows for %s from %s", len(df), developer_name, most_recent.name)

        return data


# Backward-compatible singleton (old code expects drive_manager)
# New code should get instance via Container.get_drive_manager().
drive_manager = GoogleDriveManager(
    credentials_path=Path(os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")),
    token_path=Path(os.getenv("GOOGLE_TOKEN_PATH", "token.pickle")),
    cache_ttl=int(os.getenv("GOOGLE_DRIVE_CACHE_TTL", "3600")),
)


__all__ = ["GoogleDriveManager", "DriveFile", "drive_manager"]
