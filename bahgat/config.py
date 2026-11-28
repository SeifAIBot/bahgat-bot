"""Config loading — pydantic-settings + .env resolved against the project
root (not CWD, so `python main.py` works from anywhere). No secrets in code.

The LLM fallback chain lives in config/providers.yaml (one entry per
provider: model, base_url, key env var, timeout); bahgat/llm.py walks it in
order. Keys arrive as env vars (exported or through .env) and are never
logged.
"""
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def project_root() -> Path:
    return _PROJECT_ROOT


def data_dir() -> Path:
    """Runtime state (bahgat.db, downloads/, voice/, bot.log).

    Default <project root>/data. Set BAHGAT_DATA_DIR to a persistent
    volume on hosts with an ephemeral filesystem. Read at call time."""
    override = os.environ.get("BAHGAT_DATA_DIR", "").strip()
    if override:
        return Path(override)
    return _PROJECT_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_PROJECT_ROOT / ".env", extra="ignore")

    telegram_bot_token: str = ""
    owner_id: int = 0

    # LLM. The ordered fallback chain is config/providers.yaml; each entry
    # names the env var holding its key, so several providers run side by
    # side. The fields below are optional overrides, not a provider switch:
    #   LLM_CHAIN     comma-separated entry (or family) names, in try order
    #   LLM_PROVIDER  move one family/entry to the front; the rest still
    #                 backs it up, so this never leaves a single model
    #   LLM_MODEL / LLM_BASE_URL / LLM_API_KEY  retarget the FIRST entry only
    llm_chain: str = ""
    llm_provider: str = ""
    llm_model: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    # Provider keys — read from .env here, then from the process env in
    # bahgat/llm.py. One key per provider; never commit them.
    # (v2.2: Cerebras and OpenRouter are OUT by owner call — skip both.)
    groq_api_key: str = ""
    nvidia_api_key: str = ""
    gemini_api_key: str = ""

    # RVC voice worker (a SEPARATE service — never embedded in this
    # 1 GB container). Empty = Edge TTS only. When set, bahgat/voice.py
    # tries the worker first and falls back to Edge TTS on any failure.
    rvc_url: str = ""
    # Optional egress proxy for yt-dlp downloads only (e.g. a WARP
    # wireproxy at socks5://127.0.0.1:1080). Empty = direct. If the
    # proxy is down, yt-dlp fails and the bot falls back as usual.
    ytdlp_proxy_url: str = ""

    log_level: str = "INFO"
    # Drop Telegram's pending-update backlog on startup so the bot never
    # chews through stale messages with LLM calls after downtime.
    drop_pending_updates: bool = True
    # Comma-separated Telegram chat ids the bot may answer in. Empty = all.
    allowed_chat_ids: str = ""

    def allowed_chat_ids_set(self) -> set:
        out = set()
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
        raise RuntimeError("TELEGRAM_BOT_TOKEN missing — set it in .env, never in code or chat")
    if not s.owner_id:
        raise RuntimeError("OWNER_ID missing — the owner's Telegram numeric ID")
    return s
