"""
Developer Inventory Quick Reference
Quick access to developer links without full Google Drive integration.
"""

import json
from pathlib import Path
from typing import Dict, List, Any


def load_developer_links() -> Dict[str, Any]:
    """Load developer links from JSON file."""
    links_file = Path(__file__).parent.parent / "data" / "developer_links.json"
    if links_file.exists():
        with open(links_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"developers": [], "google_drive_folders": [], "google_sheets": [], "google_files": []}


def format_developer_list() -> str:
    """Format developer links for display in Telegram."""
    data = load_developer_links()
    
    lines = ["🏢 <b>Застройщики (веб-сайты):</b>\n"]
    
    for dev in data.get("developers", []):
        name = dev.get("name", "Unknown")
        url = dev.get("url", "")
        category = dev.get("category", "")
        lines.append(f"• <a href='{url}'>{name}</a> ({category})")
    
    lines.append(f"\n📁 <b>Google Drive папки:</b> {len(data.get('google_drive_folders', []))}")
    lines.append(f"📊 <b>Google Sheets:</b> {len(data.get('google_sheets', []))}")
    lines.append(f"📄 <b>Файлы:</b> {len(data.get('google_files', []))}")
    
    lines.append("\n💡 <b>Полный список:</b> /folders")
    
    return "\n".join(lines)


def format_all_links() -> str:
    """Format all links including Google Drive."""
    data = load_developer_links()
    
    lines = ["📋 <b>Полный список источников:</b>\n"]
    
    # Websites
    lines.append("<b>🌐 Веб-сайты застройщиков:</b>")
    for dev in data.get("developers", [])[:10]:  # Limit to 10
        name = dev.get("name", "Unknown")
        url = dev.get("url", "")
        lines.append(f"• <a href='{url}'>{name}</a>")
    
    # Google Drive folders
    lines.append(f"\n<b>📁 Google Drive папки ({len(data.get('google_drive_folders', []))}):</b>")
    for folder in data.get("google_drive_folders", [])[:5]:  # Show first 5
        name = folder.get("name", "Unknown")
        folder_id = folder.get("folder_id", "")
        url = f"https://drive.google.com/drive/folders/{folder_id}"
        lines.append(f"• <a href='{url}'>{name}</a>")
    
    if len(data.get("google_drive_folders", [])) > 5:
        lines.append(f"• ... и ещё {len(data.get('google_drive_folders', [])) - 5} папок")
    
    # Google Sheets
    lines.append(f"\n<b>📊 Google Sheets ({len(data.get('google_sheets', []))}):</b>")
    for sheet in data.get("google_sheets", []):
        name = sheet.get("name", "Unknown")
        sheet_id = sheet.get("sheet_id", "")
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
        lines.append(f"• <a href='{url}'>{name}</a>")
    
    lines.append("\n💡 Для поиска по остаткам используйте /search")
    
    return "\n".join(lines)


__all__ = ["load_developer_links", "format_developer_list", "format_all_links"]
