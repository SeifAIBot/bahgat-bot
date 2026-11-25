"""Config loading — pydantic-settings + .env resolved against the project
root (not CWD, so `python main.py` works from anywhere). No secrets hardcoded."""
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    """Where the bot's runtime state lives (bahgat.db, heartbeat.json,
    downloads/, voice/).

    Default is <project root>/data. Set BAHGAT_DATA_DIR to point it at a
    persistent volume instead — e.g. /data on Northflank, where the
    container filesystem is ephemeral and only the mounted volume survives
    restarts. Read at call time (not import time) so tests and the health
    server always see the current value; the module-level DB_PATH constants
    in brain/memory.py, tg/handlers.py and tg/app.py are resolved once at
    import from this function, so the env var must be set before the
    process starts (as it is when set in a host dashboard).
    """
    override = os.environ.get("BAHGAT_DATA_DIR", "").strip()
    if override:
        return Path(override)
    return _PROJECT_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_PROJECT_ROOT / ".env", extra="ignore")
    telegram_bot_token: str = ""
    owner_id: int = 0
    gemini_api_key: str = ""
    groq_api_key: str = ""
    # Optional extra providers (router v6). Empty = that provider is
    # skipped silently; the bot starts fine without any of them.
    cerebras_api_key: str = ""
    nvidia_api_key: str = ""
    openrouter_api_key: str = ""
    log_level: str = "INFO"
    # Drop Telegram's pending-update backlog on startup (default True: after
    # downtime the bot must NOT chew through stale messages with LLM calls).
    # Set DROP_PENDING_UPDATES=false on a host that sleeps/restarts often
    # (e.g. a free PaaS) so messages sent while the bot was down are
    # delivered on wake instead of silently discarded — Telegram holds
    # updates for up to 24h.
    drop_pending_updates: bool = True
    # Comma-separated Telegram chat ids the bot may answer in, e.g. "-1001234567890,-100987654321".
    # Empty = allow all chats (intentional for now: only the test-group *invite link*
    # https://t.me/+RN2Fksh8-KU3NWI0 is known, not its numeric id; set this once
    # the numeric id is known — see docs/DEPLOY.md). app.py logs a warning when empty.
    allowed_chat_ids: str = ""

    def allowed_chat_ids_set(self) -> set[int]:
        out: set[int] = set()
        for part in self.allowed_chat_ids.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.add(int(part))
            except ValueError:
                continue
        return out


def load_settings() -> Settings:
    s = Settings()
    if not s.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN missing — set it in .env (via Secure Vault, never in chat)")
    if not s.owner_id:
        raise RuntimeError("OWNER_ID missing — Seif's Telegram numeric ID only")
    return s
