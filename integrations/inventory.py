"""Inventory matching and search logic.

Provides `InventoryMatcher`:
- Lazy loading of inventory from Google Drive
- TTL caching to avoid frequent downloads
- Robust normalization and matching

Note:
Pandas operations may be CPU-heavy; call from async handlers via `asyncio.to_thread`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd

from integrations.google_drive import GoogleDriveManager


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InventoryMatch:
    """Single inventory match result."""

    developer: str
    score: int
    data: Dict[str, Any]


class InventoryMatcher:
    """Matches client requests with available inventory."""

    def __init__(
        self,
        drive_manager: GoogleDriveManager,
        ttl_seconds: int = 900,
    ):
        """Initialize matcher.

        Args:
            drive_manager: Google Drive manager.
            ttl_seconds: Inventory cache TTL.
        """
        self.drive_manager = drive_manager
        self.ttl_seconds = ttl_seconds

        self.inventory_cache: Dict[str, pd.DataFrame] = {}
        self.last_update: Optional[datetime] = None

    def _is_cache_valid(self) -> bool:
        if not self.last_update:
            return False
        return (datetime.now() - self.last_update) < timedelta(seconds=self.ttl_seconds)

    def refresh_inventory(self, force: bool = False) -> bool:
        """Refresh inventory data from Google Drive.

        Args:
            force: Force refresh even if cache is valid.

        Returns:
            True if refreshed successfully, False otherwise.
        """
        try:
            if not force and self._is_cache_valid() and self.inventory_cache:
                return True

            if not self.drive_manager.is_authorized():
                logger.warning("Google Drive not authorized")
                return False

            self.inventory_cache = self.drive_manager.get_inventory_data(use_cache=True)
            self.last_update = datetime.now()
            return True

        except Exception as e:
            logger.error("Failed to refresh inventory: %s", e, exc_info=True)
            return False

    @staticmethod
    def _normalize_number(text: str) -> Optional[float]:
        if not text:
            return None
        cleaned = str(text).lower()
        cleaned = re.sub(r"[^\d.,]", "", cleaned).replace(",", ".")
        cleaned = cleaned.replace(" ", "")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    def normalize_budget(self, budget_text: str) -> Optional[float]:
        """Extract numeric budget from text."""
        return self._normalize_number(budget_text)

    def normalize_size(self, size_text: str) -> Optional[float]:
        """Extract numeric size from text."""
        match = re.search(r"(\d+(?:[.,]\d+)?)", str(size_text or ""))
        if not match:
            return None
        try:
            return float(match.group(1).replace(",", "."))
        except ValueError:
            return None

    def normalize_rooms(self, rooms_text: str) -> Optional[int]:
        """Extract room count from text."""
        if not rooms_text:
            return None

        text = str(rooms_text).lower()

        if "студ" in text or "studio" in text:
            return 0

        match = re.search(r"(\d+)", text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
        return None

    def match_apartments(
        self,
        budget: Optional[str] = None,
        size: Optional[str] = None,
        location: Optional[str] = None,
        rooms: Optional[str] = None,
        ready_status: Optional[str] = None,
        max_results: int = 5,
    ) -> List[InventoryMatch]:
        """Find matching apartments in inventory."""

        if not self.inventory_cache or not self._is_cache_valid():
            self.refresh_inventory(force=False)

        if not self.inventory_cache:
            return []

        budget_min, budget_max = self._parse_budget_range(budget)
        size_min, size_max = self._parse_size_range(size)
        rooms_count = self.normalize_rooms(rooms)

        results: List[InventoryMatch] = []

        for developer_name, df in self.inventory_cache.items():
            if df is None or df.empty:
                continue

            budget_col = self._find_column(df, ["цена", "price", "стоимость", "budget", "gel"])  # noqa
            size_col = self._find_column(df, ["площадь", "size", "area", "м²", "кв.м", "sqm"])  # noqa
            rooms_col = self._find_column(df, ["комнаты", "rooms", "тип", "type", "спальн"])  # noqa
            location_col = self._find_column(df, ["проект", "project", "жк", "локац", "location"])  # noqa
            status_col = self._find_column(df, ["статус", "status", "готов", "ready"])  # noqa

            for _, row in df.iterrows():
                score = 0
                row_dict = row.to_dict()

                # Budget
                if budget_col and budget_max is not None:
                    apt_budget = self.normalize_budget(str(row_dict.get(budget_col, "")))
                    if apt_budget is not None:
                        if budget_min is not None and budget_min <= apt_budget <= budget_max:
                            score += 30
                        elif apt_budget <= budget_max:
                            score += 20
                        elif apt_budget <= budget_max * 1.1:
                            score += 10

                # Size
                if size_col and size_min is not None and size_max is not None:
                    apt_size = self.normalize_size(str(row_dict.get(size_col, "")))
                    if apt_size is not None:
                        if size_min <= apt_size <= size_max:
                            score += 25
                        elif size_min * 0.9 <= apt_size <= size_max * 1.1:
                            score += 15

                # Rooms
                if rooms_col and rooms_count is not None:
                    apt_rooms = self.normalize_rooms(str(row_dict.get(rooms_col, "")))
                    if apt_rooms is not None:
                        if apt_rooms == rooms_count:
                            score += 25
                        elif abs(apt_rooms - rooms_count) == 1:
                            score += 10

                # Location
                if location_col and location:
                    apt_location = str(row_dict.get(location_col, "")).lower()
                    query = location.lower().strip()
                    if query and (query in apt_location or any(w in apt_location for w in query.split())):
                        score += 15

                # Ready status
                if status_col and ready_status:
                    apt_status = str(row_dict.get(status_col, "")).lower()
                    rs = ready_status.lower().strip()
                    if rs and rs in apt_status:
                        score += 10

                if score > 0:
                    results.append(
                        InventoryMatch(
                            developer=developer_name,
                            score=score,
                            data=row_dict,
                        )
                    )

        results.sort(key=lambda m: m.score, reverse=True)
        return results[:max_results]

    def _parse_budget_range(self, budget_text: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
        if not budget_text:
            return None, None

        text = str(budget_text).lower()

        # Range: 100000-150000
        m = re.search(r"(\d[\d\s]*)\s*-\s*(\d[\d\s]*)", text)
        if m:
            return self.normalize_budget(m.group(1)), self.normalize_budget(m.group(2))

        # До X
        m = re.search(r"до\s+(\d[\d\s]*)", text)
        if m:
            return 0.0, self.normalize_budget(m.group(1))

        # От X
        m = re.search(r"от\s+(\d[\d\s]*)", text)
        if m:
            return self.normalize_budget(m.group(1)), float("inf")

        single = self.normalize_budget(text)
        if single is not None:
            return 0.0, single * 1.1

        return None, None

    def _parse_size_range(self, size_text: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
        if not size_text:
            return None, None

        text = str(size_text).lower()

        m = re.search(r"(\d+(?:[.,]\d+)?)\s*-\s*(\d+(?:[.,]\d+)?)", text)
        if m:
            return self.normalize_size(m.group(1)), self.normalize_size(m.group(2))

        single = self.normalize_size(text)
        if single is not None:
            return single * 0.8, single * 1.2

        return None, None

    @staticmethod
    def _find_column(df: pd.DataFrame, possible_names: List[str]) -> Optional[str]:
        columns = [str(c).lower().strip() for c in df.columns]

        for needle in possible_names:
            n = needle.lower()
            for i, col in enumerate(columns):
                if n in col or col in n:
                    return df.columns[i]

        return None

    @staticmethod
    def format_match(match: InventoryMatch) -> str:
        """Format a match for display."""
        lines = [f"🏢 {match.developer}"]

        for key, value in match.data.items():
            if pd.notna(value) and str(value).strip():
                lines.append(f"  {key}: {value}")

        lines.append(f"  📊 Совпадение: {match.score}%")
        lines.append("")
        return "\n".join(lines)


# Backward-compatible singleton
from integrations.google_drive import drive_manager  # noqa: E402

inventory_matcher = InventoryMatcher(drive_manager=drive_manager)


__all__ = ["InventoryMatcher", "InventoryMatch", "inventory_matcher"]
