# Realtor Bot Architecture (Refactor)

## Goals

- Keep **user-facing behavior** intact (same Telegram commands and flows).
- Improve maintainability: split large modules, introduce clear layers.
- Improve safety: input validation/sanitization, rate limiting, better error handling.
- Improve performance: caching (TTL), lazy loading, avoid repeated heavy operations.
- Prepare for future growth: switchable DB backend, switchable LLM provider.

## High-Level Structure

```
realtor-bot/
  main.py
  bot/
    config.py
    handlers.py               # facade (re-exports)
    client_handlers.py        # client flows (/start, dialog, voice)
    realtor_handlers.py       # realtor flows (/register, /clients, callbacks)
    drive_handlers.py         # /drive_setup, /inventory, /search, /folders
    llm_handler.py            # backward-compatible wrapper
  core/
    container.py              # Dependency Injection factory (lazy singletons)
    llm_service.py            # LLM provider abstraction + fallback
    middleware.py             # logging / errors / rate limiting
  database/
    models.py                 # Pydantic models (validation + sanitization)
    repository.py             # Repository interface
    json_repository.py        # JSON backend (MVP, backward compatible)
    db.py                     # legacy facade
  integrations/
    google_drive.py           # Drive manager (retry + caching)
    inventory.py              # inventory matcher (TTL cache)
    google_sheets.py          # optional CRM integration
  utils/
    helpers.py                # sanitization + small helpers
```

## Execution Flow

### main.py
- Loads settings from `.env` via `bot.config.settings` (pydantic-settings).
- Builds `python-telegram-bot` `Application`.
- Registers:
  - `ConversationHandler` for realtor registration (`/register` → phone → company)
  - `ConversationHandler` for client LLM dialog (`/start` → message/voice)
  - Command handlers (`/clients`, `/stats`, `/drive_setup`, etc.)
  - Callback handler for inline buttons
  - Low-priority text handler for Drive OAuth code input

### Dependency Injection
- `core.container.Container` is the single place where services are created.
- Services are **lazy-loaded** and cached:
  - Repository (`JSONRepository` by default)
  - LLM Service (`LLMService`) with fallback chain
  - Google Drive manager (`GoogleDriveManager`) with TTL caching
  - Inventory matcher (`InventoryMatcher`) with TTL caching

## Key Best Practices Applied

### 1) Validation & Security
- Data models moved to **Pydantic** (`database/models.py`).
- User input is sanitized via `utils.helpers.sanitize_user_text`.
- Rate limiting via `core.middleware.RateLimiter` decorator.

### 2) Error Handling & Logging
- Per-handler middleware wrappers: logging + rate limiting + error handling.
- Global PTB error handler in `main.py`.

### 3) Performance
- Inventory loading uses TTL caching:
  - Drive scans are cached (`cachetools.TTLCache`).
  - Inventory data is cached with TTL in `InventoryMatcher`.
- Heavy sync operations (Google API / pandas) should be called via `asyncio.to_thread`.

### 4) DB Layer (Repository Pattern)
- `database/repository.py` defines the interface.
- `database/json_repository.py` implements the MVP backend and keeps the JSON schema:
  ```json
  {
    "realtors": {"<id>": {...}},
    "clients": {"<id>": {...}},
    "client_counter": 123
  }
  ```
- This makes migration to SQL easy: add `SQLRepository` implementing the same interface.

### 5) LLM Provider Abstraction
- `core/llm_service.py` provides:
  - provider base interface
  - OpenAI provider
  - Anthropic provider
  - fallback chain (tries next provider on errors)
  - optional streaming interface

## How to Extend

### Add a New Command
1. Add handler function to the appropriate module:
   - `client_handlers.py` (client)
   - `realtor_handlers.py` (realtor)
   - `drive_handlers.py` (drive/inventory)
2. Wrap it with `@with_middleware`.
3. Register it in `main.py` via `CommandHandler`.

### Add a New DB Backend (PostgreSQL)
1. Create `database/sql_repository.py` implementing `BaseRepository`.
2. Set in `.env`:
   - `DATABASE_BACKEND=postgresql`
   - `DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname`
3. Update `core/container.py` to import and instantiate the SQL repository.

### Add a New LLM Provider
1. Create a new provider class implementing `LLMProviderBase`.
2. Add enum value to `LLMProvider`.
3. Extend `LLMService._setup_provider`.
4. Configure `.env` to select provider and API key.

## Operational Notes (VPS, 24/7)
- Keep `.env` with required keys:
  - `TELEGRAM_BOT_TOKEN`
  - `OPENAI_API_KEY` (or set `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY`)
- Google Drive OAuth requires `credentials.json` and will store token in `token.pickle`.

