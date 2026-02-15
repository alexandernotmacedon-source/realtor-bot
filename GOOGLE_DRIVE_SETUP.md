# Google Drive Integration Setup

## Prerequisites

1. Create a Google Cloud Project
2. Enable Google Drive API
3. Create OAuth 2.0 credentials
4. Download `credentials.json`

## Setup Steps

### 1. Create Google Cloud Project
- Go to https://console.cloud.google.com/
- Create new project (e.g., "Realtor Bot")
- Select the project

### 2. Enable Google Drive API
- Go to "APIs & Services" → "Library"
- Search for "Google Drive API"
- Click "Enable"

### 3. Configure OAuth Consent Screen
- Go to "APIs & Services" → "OAuth consent screen"
- Select "External" (for testing) or "Internal" (if you have Google Workspace)
- Fill in app name: "Realtor Bot"
- Add support email
- Save

### 4. Create OAuth 2.0 Credentials
- Go to "APIs & Services" → "Credentials"
- Click "Create Credentials" → "OAuth client ID"
- Application type: "Desktop app"
- Name: "Realtor Bot Desktop"
- Click "Create"
- Download JSON file
- Rename to `credentials.json`
- Place in `realtor-bot/` directory

### 5. Test Users (Important!)
- Go to "OAuth consent screen" → "Test users"
- Add Sofia's Gmail address
- This is required while app is in "Testing" mode

## Bot Commands

Once setup is complete, users can:

1. `/drive_setup` - Start Google Drive authorization
2. Follow the link and authorize
3. Send the auth code back to bot
4. `/inventory` - View available apartments
5. `/search бюджет=150000 комнаты=2` - Search by criteria
6. `/folders` - View configured folders

## Folder Configuration

Add folder mappings in `bot/config.py`:

```python
GOOGLE_DRIVE_FOLDERS = {
    'Like House': '1zstD8eqbp6S_k-Dc-0ptlSF_etd_WNY8',
    'One Development': '1uY91KJWgeAA-pu4weJddDwb54lgeKErJ',
}
```

## Expected Excel Format

Inventory files should have columns like:
- Проект / Project
- Комнаты / Rooms / Type
- Площадь / Area / Size / м²
- Цена / Price / Budget / GEL
- Статус / Status
- Этаж / Floor

The bot will auto-detect column names.
