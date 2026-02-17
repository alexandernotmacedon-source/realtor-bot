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


def load_developer_names() -> Dict[str, str]:
    """Load developer name mapping from JSON file."""
    import json
    import os
    
    json_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data",
        "developer_names.json"
    )
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Filter out comments
            return {k: v for k, v in data.items() if not k.startswith('_')}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Could not load developer_names.json: {e}")
        return {}


def load_developer_addresses() -> Dict[str, str]:
    """Load developer address mapping from JSON file."""
    import json
    import os
    
    json_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data",
        "developer_addresses.json"
    )
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Filter out comments and empty values
            return {k: v for k, v in data.items() if not k.startswith('_') and v}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Could not load developer_addresses.json: {e}")
        return {}


# Load developer names and addresses (will be refreshed on each format call)
DEVELOPER_NAMES = load_developer_names()
DEVELOPER_ADDRESSES = load_developer_addresses()


@dataclass(frozen=True)
class InventoryMatch:
    """Single inventory match result."""

    developer: str
    score: int
    data: Dict[str, Any]
    matched_criteria: List[str]


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
        self.developer_names_mapping: Dict[str, str] = {}  # folder_key -> actual name
        self.developer_addresses_mapping: Dict[str, str] = {}  # folder_key -> address
        self.last_update: Optional[datetime] = None

    def _is_cache_valid(self) -> bool:
        if not self.last_update:
            return False
        return (datetime.now() - self.last_update) < timedelta(seconds=self.ttl_seconds)

    # Keywords that indicate sold/booked/reserved
    SOLD_KEYWORDS = ['sold', 'продано', 'sold out',
                     'booked', 'забронировано', 'бронь', 'ჯავშანი',
                     'reserved', 'резерв', 'резервировано']
    
    # Patterns indicating realtor booking (names in status field)
    # If status contains uppercase name + optional numbers/slash, it's likely booked
    BOOKING_PATTERNS = [
        r'[A-Z]{3,}',           # MARIA, LASHA
        r'[A-Z]+\s*\d+',        # MARIA 022
        r'[A-Z]+/[A-Z]+',        # LASHA/VLAD
        r'[a-z]+/[a-z]+',        # lasha/ekaterina
        r'დაინტერესებული',      # "interested" in Georgian
    ]

    def _is_row_available(self, row: pd.Series) -> bool:
        """Check if row contains any sold/booked keywords in ANY column."""
        import re
        
        for val in row.values:
            if pd.notna(val):
                val_str = str(val).lower()
                val_str_original = str(val)
                
                # Check sold/booked keywords
                if any(keyword in val_str for keyword in self.SOLD_KEYWORDS):
                    return False
                
                # Check realtor booking patterns (names in status)
                for pattern in self.BOOKING_PATTERNS:
                    if re.search(pattern, val_str_original):
                        return False
        
        return True

    def _filter_available(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filter out sold and booked apartments."""
        if df is None or df.empty:
            return df
        
        # Check ALL columns for sold/booked keywords
        mask = df.apply(self._is_row_available, axis=1)
        filtered = df[mask]
        
        removed = len(df) - len(filtered)
        if removed > 0:
            print(f"  Filtered {removed} sold/booked, {len(filtered)} remaining")
        
        return filtered

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

            # Force scan folders first (bypass scan cache)
            logger.info("Scanning all folders...")
            self.drive_manager.scan_all_folders(use_cache=False)
            
            # Get actual folder names from Google Drive
            logger.info("Fetching folder names...")
            self.developer_names_mapping = self.drive_manager.get_folder_names_mapping()
            logger.info(f"Found {len(self.developer_names_mapping)} folder names")

            # Load developer addresses from local JSON
            self.developer_addresses_mapping = load_developer_addresses()
            logger.info(f"Loaded {len(self.developer_addresses_mapping)} developer addresses")
            
            # Now get inventory data (will use fresh scan results)
            raw_data = self.drive_manager.get_inventory_data(use_cache=False)
            
            # Filter out sold/booked apartments
            self.inventory_cache = {}
            total_before = 0
            total_after = 0
            
            for developer_name, df in raw_data.items():
                if df is not None:
                    total_before += len(df)
                    filtered_df = self._filter_available(df)
                    total_after += len(filtered_df)
                    self.inventory_cache[developer_name] = filtered_df
            
            self.last_update = datetime.now()
            
            logger.info(f"Inventory refreshed: {len(self.inventory_cache)} developers, "
                       f"{total_after} available (filtered {total_before - total_after} sold/booked)")
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
        offset: int = 0,
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
                matched = []
                row_dict = row.to_dict()

                # Budget
                if budget_col and budget_max is not None:
                    apt_budget = self.normalize_budget(str(row_dict.get(budget_col, "")))
                    if apt_budget is not None:
                        if budget_min is not None and budget_min <= apt_budget <= budget_max:
                            score += 30
                            matched.append("✅ Цена")
                        elif apt_budget <= budget_max:
                            score += 20
                            matched.append("✅ Цена")
                        elif apt_budget <= budget_max * 1.1:
                            score += 10
                            matched.append("⚠️ Цена (+10%)")

                # Size
                if size_col and size_min is not None and size_max is not None:
                    apt_size = self.normalize_size(str(row_dict.get(size_col, "")))
                    if apt_size is not None:
                        if size_min <= apt_size <= size_max:
                            score += 25
                            matched.append("✅ Площадь")
                        elif size_min * 0.9 <= apt_size <= size_max * 1.1:
                            score += 15
                            matched.append("⚠️ Площадь (±10%)")

                # Rooms
                if rooms_col and rooms_count is not None:
                    apt_rooms = self.normalize_rooms(str(row_dict.get(rooms_col, "")))
                    if apt_rooms is not None:
                        if apt_rooms == rooms_count:
                            score += 25
                            matched.append("✅ Комнаты")
                        elif abs(apt_rooms - rooms_count) == 1:
                            score += 10
                            matched.append("⚠️ Комнаты (±1)")

                # Location
                if location_col and location:
                    apt_location = str(row_dict.get(location_col, "")).lower()
                    query = location.lower().strip()
                    if query and (query in apt_location or any(w in apt_location for w in query.split())):
                        score += 15
                        matched.append("✅ Локация")

                # Ready status
                if status_col and ready_status:
                    apt_status = str(row_dict.get(status_col, "")).lower()
                    rs = ready_status.lower().strip()
                    if rs and rs in apt_status:
                        score += 10
                        matched.append("✅ Статус")

                if score > 0:
                    results.append(
                        InventoryMatch(
                            developer=developer_name,
                            score=score,
                            data=row_dict,
                            matched_criteria=matched,
                        )
                    )

        # Sort by score descending
        results.sort(key=lambda m: m.score, reverse=True)
        
        # Apply diversity: max 2 per developer, round-robin selection
        developer_counts = {}
        diverse_results = []
        
        for match in results:
            dev = match.developer
            if developer_counts.get(dev, 0) < 2:  # Max 2 per developer
                diverse_results.append(match)
                developer_counts[dev] = developer_counts.get(dev, 0) + 1
            if len(diverse_results) >= offset + max_results:
                break
        
        return diverse_results[offset:offset + max_results]

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

        # Range: 70-100
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*-\s*(\d+(?:[.,]\d+)?)", text)
        if m:
            return self.normalize_size(m.group(1)), self.normalize_size(m.group(2))

        # "от X" / "не менее X" / "min X" -> X to infinity
        m = re.search(r"(?:от|не менее|минимум|min)\s*(\d+(?:[.,]\d+)?)", text)
        if m:
            return self.normalize_size(m.group(1)), float("inf")

        # "до X" / "не более X" -> 0 to X
        m = re.search(r"(?:до|не более|максимум|max)\s*(\d+(?:[.,]\d+)?)", text)
        if m:
            return 0.0, self.normalize_size(m.group(1))

        # Single number -> ±20%
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

    # Georgian to Russian translation map for common terms
    TRANSLATIONS = {
        'ზღვის': 'Море',
        'ქალაქის': 'Город',
        'ქალაქისა': 'Город',
        'მთის': 'Горы',
        'მთისა': 'Горы',
        'ზღვის,': 'Море,',
        'ზღვისქალაქის': 'Море/Город',
        'ზღვისქალაქისამთის': 'Море/Город/Горы',
        '/Sea': '/Море',
        '/City': '/Город',
        '/Mountains': '/Горы',
        'Sea': 'Море',
        'City': 'Город',
        'Mountains': 'Горы',
        'and': 'и',
    }

    @classmethod
    def translate_text(cls, text: str) -> str:
        """Translate Georgian/common terms to Russian."""
        if not text:
            return text
        result = str(text)
        for geo, rus in cls.TRANSLATIONS.items():
            result = result.replace(geo, rus)
        return result

    def format_match(self, match: InventoryMatch) -> str:
        """Format a match for display - simple and readable."""
        data = match.data

        # Extract key fields
        apt = data.get('ბინა/apartment', data.get('№', ''))
        size = data.get('საერთო ფართი/ Total area', data.get('Площадь', data.get('size', '')))
        price = data.get('სრული ღირებულება/Total price', data.get('Стоимость', data.get('price', '')))
        floor = data.get('Этаж', '')
        rooms = data.get('Тип', '')

        # Get original folder key for address lookup
        folder_key = match.developer

        # Clean developer name - use Google Drive folder names if available
        developer = folder_key
        if self.developer_names_mapping and folder_key in self.developer_names_mapping:
            developer = self.developer_names_mapping[folder_key]
        elif folder_key in DEVELOPER_NAMES:
            developer = DEVELOPER_NAMES[folder_key]
        elif folder_key.lower().startswith('folder_'):
            # Fallback: extract number and create friendly name
            try:
                num = folder_key.split('_')[1]
                developer = f"ЖК #{num}"
            except (IndexError, ValueError):
                developer = "Жилой комплекс"

        # Get address for this developer
        address = ""
        if self.developer_addresses_mapping and folder_key in self.developer_addresses_mapping:
            address = self.developer_addresses_mapping[folder_key]
        elif folder_key in DEVELOPER_ADDRESSES:
            address = DEVELOPER_ADDRESSES[folder_key]

        # Format price nicely
        price_str = ''
        if price:
            if isinstance(price, (int, float)):
                price_str = f"${price:,.0f}"
            else:
                price_str = str(price)
        
        # Simple format: one line per apartment
        if address:
            parts = [f"🏢 <b>{developer}</b> 📍{address}"]
        else:
            parts = [f"🏢 <b>{developer}</b>"]

        # Room and size
        room_size = []
        if rooms:
            room_size.append(rooms)
        if size:
            room_size.append(f"{size}м²")
        if room_size:
            parts.append(" | ".join(room_size))
        
        # Floor
        if floor:
            parts.append(f"этаж {floor}")
        
        # Price
        if price_str:
            parts.append(f"💰 {price_str}")
        
        return " • ".join(parts) + "\n"


# Backward-compatible singleton
from integrations.google_drive import drive_manager  # noqa: E402

inventory_matcher = InventoryMatcher(drive_manager=drive_manager)


__all__ = ["InventoryMatcher", "InventoryMatch", "inventory_matcher"]
