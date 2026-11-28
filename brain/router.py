"""Multi-LLM router v6 — pooled free providers, per-model quotas.
- Pool of DIFFERENT providers only, one key per provider (never
  multi-account / multi-project rotation to multiply one provider's
  quota — that would violate providers' Terms of Service).
- Per-(entry, model) usage: provider_usage is keyed by
  (provider=entry_name, model, date). Groq limits are PER MODEL
  (200k TPD each), so the v0.5 bug — one combined "groq" counter
  for 120b+20b — is fixed. Migration from the v0.5-shaped table
  (PRIMARY KEY(provider, date), no model column) runs here in
  _ensure_usage_table: old rows are preserved with model='' and
  count conservatively toward every entry of that provider family
  (their model split is unknowable); new rows are per-model.
- Entries (config/providers.yaml): Groq gpt-oss-20b / gpt-oss-120b /
  qwen3.8-27b (180k tokens/day each), Cerebras gpt-oss-120b (1M/day;
  free-tier status DISPUTED — see providers.yaml — disabled on
  401/403/404), NVIDIA NIM nemotron-3.5-super-vl-120b (10k req/day;
  trial terms say testing/evaluation only, NOT production — overflow
  tier, never primary), Gemini flash-lite 3.5/3.1 (500 RPD each),
  Gemma 4 31b (14,400 RPD, TPM-managed with a 9s rpm guard),
  gemini-3-flash-preview LAST resort (20 RPD), OpenRouter :free
  emergency spare only (50 req/day, account-wide, shared across its
  entries).
- Routing: preference order per tier (routing.simple_order /
  hard_order in YAML), then least-used-first WITHIN the tier — the
  entry with the most remaining daily budget (min of request- and
  token-cap fractions) goes first; stable sort keeps YAML order on
  ties. Exhausted / Retry-After-banned / circuit-open / rpm-guarded
  entries are skipped.
- Classified retries (transient only, backoff+jitter, Retry-After),
  circuit breaker per entry, TPM vs TPD 429 classification
  (Retry-After<=120s = tpm ban that long; daily/quota text = tpd ban
  to midnight UTC), structured JSON log per LLM call (entry,
  cached_tokens from usage.prompt_tokens_details.cached_tokens).
- reasoning_effort="low" everywhere; include_reasoning=False sent
  ONLY to Groq-family entries (unverified for the others).
- v0.7: Gemini usage rows are keyed by PACIFIC date (Gemini RPD resets
  at midnight Pacific, UTC-8), every other family by UTC date
  (_date_for). pool_snapshot() / pool_remaining_replies() expose the
  live capacity in replies for the fair-share quota layer; chat()
  takes cheap_only + intent and records each successful reply's
  tokens once via memory.record_reply_tokens (EWMA input).
- Output caps (default, when handlers don't pass max_tokens):
  groq 3000, gemini 4000, cerebras/nvidia/openrouter 3000
  (config/providers.yaml caps.output_tokens — the docstring said
  groq 1500 before v1.17, which was stale).
  Handlers pass max_tokens=3000 (v1.17), which overrides per call.
  Groq calls are additionally clamped so estimated prompt + max
  output stays under 7,500 (Groq 8,000 TPM window).
- 401/403/404 (bad key / retired model / dead free tier) DISABLES
  that entry in-memory for the process lifetime, logs server-side,
  and the router continues to the next entry — never a group-facing
  message about keys. NO_KEYS_MSG only when NO provider has a key.
- _status_of uses exc.status_code / exc.response.status_code ONLY —
  never substring-matches status codes in exception text.
- Token estimate: max(1, len(text)//2). Arabic runs ~0.5-0.66
  tokens/char, so len//3 undercounted ~2x. 0.5 is the safe middle.
"""
import asyncio
import json
import random
import re
import sqlite3
import time
import logging
import httpx
import yaml
from pathlib import Path
from openai import AsyncOpenAI

from brain import telemetry as _telemetry
from core.config import data_dir

logger = logging.getLogger("bahgat")

NO_KEYS_MSG = "يا عم، المفاتيح لسه متظبطتش — سيف لازم يدخل مفاتيح Gemini و Groq الأول."
FAIL_MSG = "الموديلات واقعة دلوقتي، جرب تاني كمان شوية."

# Settings attribute per provider family (env var names live in YAML).
_FAMILY_SETTINGS_ATTR = {
    "gemini": "gemini_api_key",
    "groq": "groq_api_key",
    "cerebras": "cerebras_api_key",
    "nvidia": "nvidia_api_key",
    "openrouter": "openrouter_api_key",
}

# Entries that may serve replies in cheap-only (degraded) mode. Never
# gemini-3-flash-preview (20 RPD, last resort) or nvidia-nemotron
# (trial terms: testing/evaluation only) as a cheap-mode primary.
_CHEAP_ENTRY_NAMES = frozenset(
    {
        "groq-20b",
        "cerebras-120b",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-gemma",
    }
)

# Fallback average tokens/reply (research estimate) until the EWMA in
# brain.memory has measured real calls.
_FALLBACK_AVG_TOKENS = 1050.0

# Fallback base URLs if an entry omits base_url (YAML is authoritative).
PROVIDER_ENDPOINTS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "groq": "https://api.groq.com/openai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}
TRANSIENT = (408, 429, 500, 502, 503, 504)
# Auth / not-found / retired-model: disable the entry, never retry it.
_DISABLE_STATUS = (401, 403, 404)
# v1.15 latency bounds (research report §2.2 Rank 1): ONE explicit
# client timeout for every provider call — connect 5 s, read 25 s
# (the per-call bound), write 10 s, pool 5 s — AND max_retries=0 on
# the SDK client. The SDK's default is a 600 s timeout with 2
# retries, which multiplied the router's own retry loop (up to 2
# attempts per entry x N entries) into the 172-428 s turns seen live.
# The retry layer is the router's own loop (max_retries_per_provider
# in YAML, default 1) — exactly ONE layer retries, the SDK never
# does. config/providers.yaml timeout_seconds (20/30) is now unused
# (kept in the YAML for compat); this explicit timeout governs.
_CLIENT_TIMEOUT = httpx.Timeout(connect=5.0, read=25.0, write=10.0, pool=5.0)
# finish_reason values that mean the provider refused the content
# (OpenAI "content_filter"; Gemini via OpenAI-compat "SAFETY").
_REFUSAL_FINISH_REASONS = frozenset({"content_filter", "SAFETY"})
_DAILY_WORDS = ("daily", "quota", "tpd", "tokens per day", "per day")
_OPENROUTER_REFERER = "https://t.me/Bahgoti_bot"
_OPENROUTER_TITLE = "Bahgat Bot"


def load_providers():
    p = Path(__file__).resolve().parents[1] / "config" / "providers.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _status_of(exc):
    """Status code from the exception object ONLY — never substring-match
    codes in the exception text (a URL or token count containing "404"
    used to misclassify). Returns None when unparseable (treated as
    transient with backoff by the caller)."""
    s = getattr(exc, "status_code", None)
    if s is not None:
        try:
            return int(s)
        except (TypeError, ValueError):
            return None
    resp = getattr(exc, "response", None)
    if resp is not None:
        s = getattr(resp, "status_code", None)
        if s is not None:
            try:
                return int(s)
            except (TypeError, ValueError):
                return None
    return None


def _retry_after(exc, default=None):
    """Retry-After in seconds from headers, then from the error body.
    Returns None when absent."""
    try:
        resp = getattr(exc, "response", None)
        if resp is not None:
            headers = getattr(resp, "headers", None) or {}
            for k, v in dict(headers).items():
                if str(k).lower() == "retry-after" and v:
                    return float(v)
    except Exception:
        pass
    try:
        m = re.search(r"retry[-_ ]?after['\"]?\s*[:=]\s*(\d+(?:\.\d+)?)", str(exc), re.IGNORECASE)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return default


def _seconds_until_midnight_utc() -> int:
    now = time.gmtime()
    return int(86400 - (now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec))


def _classify_429(exc_or_text, retry_after=None):
    """Pure helper: ("tpm"|"tpd"|"unknown", seconds).

    - retry_after <= 120s -> tpm, ban exactly retry_after (per-minute limit).
    - error text mentions daily/quota/TPD -> tpd, ban until midnight UTC.
    - otherwise -> unknown, ban retry_after (cap 3600s), or 60s default.
    """
    text = exc_or_text if isinstance(exc_or_text, str) else str(exc_or_text or "")
    low = text.lower()
    ra = None
    if retry_after is not None:
        try:
            ra = float(retry_after)
        except (TypeError, ValueError):
            ra = None
    if ra is not None and ra <= 120:
        return ("tpm", ra)
    if any(k in low for k in _DAILY_WORDS):
        return ("tpd", _seconds_until_midnight_utc())
    if ra is not None:
        return ("unknown", min(ra, 3600))
    return ("unknown", 60)


def _completion_kwargs(family, model, messages, temperature, mct, hard):
    """Per-family Chat Completions kwargs for one attempt (v1.17:
    extracted so the NVIDIA thinking switch is unit-testable).
    - reasoning_effort="low" on EVERY call (Groq's default is
      medium; reasoning shares the output budget with the visible
      answer, so a medium trace can eat the cap before the reply
      starts).
    - include_reasoning=False only for Groq (unverified elsewhere).
    - Chat turns only (not hard/search): repetition penalties, and
      for NVIDIA, thinking OFF — Nemotron thinks by default and the
      trace shares max_tokens with the visible answer (the Lightning
      sibling returns reasoning-only content with default params,
      see config/providers.yaml). Disabling thinking gives the whole
      cap to the visible reply. Hard turns keep thinking: search
      synthesis benefits from it. The wire field is
      max_completion_tokens (there is no `output_tokens` on Chat
      Completions — the v1.13 "output_tokens 3000" wording was a
      misnomer for this field)."""
    kwargs = {"model": model, "messages": messages, "temperature": temperature,
              "max_completion_tokens": mct, "reasoning_effort": "low"}
    if family == "groq":
        kwargs["include_reasoning"] = False
    if not hard:
        # v1.13: repetition penalties for chat turns only. Search
        # turns keep factual consistency (temperature 0.25, no
        # penalties). Positive values penalise token reuse within one
        # generation; cross-turn repetition is handled by the
        # handler's opener check, not here.
        kwargs["frequency_penalty"] = 0.5
        kwargs["presence_penalty"] = 0.3
        if family == "nvidia":
            kwargs["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": False}}
    return kwargs


def _reasoning_tokens(usage) -> int:
    try:
        d = getattr(usage, "completion_tokens_details", None)
        if d is None:
            return 0
        if isinstance(d, dict):
            return int(d.get("reasoning_tokens") or 0)
        return int(getattr(d, "reasoning_tokens", 0) or 0)
    except Exception:
        return 0


def _cached_tokens(usage) -> int:
    try:
        d = getattr(usage, "prompt_tokens_details", None)
        if d is None:
            return 0
        if isinstance(d, dict):
            return int(d.get("cached_tokens") or 0)
        return int(getattr(d, "cached_tokens", 0) or 0)
    except Exception:
        return 0


def _refusal_signal(resp):
    """(refused, finish_reason) from a completions response (v1.15):
    OpenAI SDK exposes a refusal as choice.message.refusal; Gemini
    via the OpenAI-compatible endpoint reports finish_reason SAFETY
    (OpenAI: content_filter). Either one is a structured refusal —
    the model did not produce a usable reply."""
    try:
        choices = getattr(resp, "choices", None) or []
        choice = choices[0] if choices else None
    except Exception:
        return False, None
    if choice is None:
        return False, None
    finish = getattr(choice, "finish_reason", None)
    msg = getattr(choice, "message", None)
    refusal = getattr(msg, "refusal", None) if msg is not None else None
    if refusal is not None:
        return True, finish
    if finish in _REFUSAL_FINISH_REASONS:
        return True, finish
    return False, finish


def _error_kind(exc, status):
    """Short error class for the telemetry row (never the raw text)."""
    if status == 429:
        return "rate_limit"
    if status == 400:
        return "http_400"
    if type(exc).__name__ in ("APITimeoutError",) or isinstance(
            exc, (httpx.TimeoutException, asyncio.TimeoutError)):
        return "timeout"
    if status is not None:
        return "http"
    return "api"


def _record_attempt(turn_id, step, provider, model, total_ms, *,
                    status="ok", http_status=None, finish_reason=None,
                    tokens_in=None, tokens_out=None, retry_after=None,
                    temperature=None, error_kind=None, outcome="ok"):
    """One telemetry row per provider attempt (v1.15). Never raises —
    telemetry must never break a turn. TTFT equals total: these calls
    are not streamed, so there is no first token to time separately."""
    try:
        from brain.prompt import PROMPT_VERSION
    except Exception:
        PROMPT_VERSION = ""
    _telemetry.record_llm_call(
        turn_id, step, provider, model, total_ms,
        status=status, http_status=http_status,
        finish_reason=finish_reason, tokens_in=tokens_in,
        tokens_out=tokens_out, retry_after=retry_after,
        prompt_version=PROMPT_VERSION, temperature=temperature,
        error_kind=error_kind, outcome=outcome)


class CircuitBreaker:
    def __init__(self, threshold=3, open_seconds=60):
        self.threshold, self.open_seconds = threshold, open_seconds
        self.failures = 0
        self.open_until = 0.0

    def allow(self):
        return time.time() >= self.open_until

    def record_success(self):
        self.failures = 0
        self.open_until = 0.0

    def record_failure(self):
        self.failures += 1
        if self.failures >= self.threshold:
            self.open_until = time.time() + self.open_seconds
            self.failures = 0


class BrainRouter:
    def __init__(self, settings):
        self.settings = settings
        self.cfg = load_providers()
        self.keys = {
            fam: getattr(settings, attr, "") or ""
            for fam, attr in _FAMILY_SETTINGS_ATTR.items()
        }
        self.entries = list(self.cfg.get("providers", []) or [])
        self.breakers = {e["name"]: CircuitBreaker() for e in self.entries}
        # Resolved from BAHGAT_DATA_DIR (default <project root>/data).
        self.db = data_dir() / "bahgat.db"
        self._clients = {}
        # Entries disabled at runtime by 401/403/404 (bad key / dead
        # free tier / retired model). In-memory only, per process.
        self._disabled = set()
        # Last call start (time.monotonic) per entry, for rpm guards.
        self._last_call = {}
        # v1.15: structured signal of the latest attempt (provider /
        # model / finish_reason / refusal / http_status) for the
        # handler's roast-refusal check; {} before any attempt.
        self.last_call_meta = {}
        enabled = [e["name"] for e in self.entries if self.keys.get(e.get("family"))]
        missing = [e["name"] for e in self.entries if not self.keys.get(e.get("family"))]
        logger.info("router v6 providers enabled=%s disabled(no key)=%s",
                    enabled, missing)

    # -- config helpers ----------------------------------------------------
    @property
    def quota_cfg(self):
        """The `quota:` section of providers.yaml (fair-share weights,
        saturation threshold, borrow multiple, floor, planning haircut),
        or {} when the section is absent. Handlers pass it through to
        the memory quota calls."""
        cfg = self.cfg.get("quota") or {}
        return cfg if isinstance(cfg, dict) else {}

    def _provider_cfg(self, name):
        """Entry dict by entry name; a family name returns its first entry."""
        for p in self.entries:
            if p.get("name") == name:
                return p
        for p in self.entries:
            if p.get("family") == name:
                return p
        return {}

    def _entry(self, name):
        for p in self.entries:
            if p.get("name") == name:
                return p
        return None

    def _model_for(self, name, key="model"):
        cfg = self._provider_cfg(name)
        return cfg.get(key) or cfg.get("model")

    def _caps(self):
        return self.cfg.get("caps", {}) or {}

    def _output_tokens(self, family):
        out = (self._caps().get("output_tokens", {}) or {})
        try:
            return int(out.get(family, 1500))
        except (TypeError, ValueError):
            return 1500

    def _max_retries(self):
        try:
            return int((self.cfg.get("routing", {}) or {}).get("max_retries_per_provider", 1))
        except (TypeError, ValueError):
            return 1

    # -- clients -----------------------------------------------------------
    def _client(self, name):
        """AsyncOpenAI client for an entry name or a family name.

        Clients are cached per family (one client serves every entry
        of that family — entries differ by model, not by endpoint).
        """
        entry = self._entry(name)
        family = entry.get("family") if entry else name
        if family in self._clients:
            return self._clients[family]
        headers = None
        if family == "groq":
            # Groq sits behind Cloudflare: a default Python UA gets 403.
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
        elif family == "openrouter":
            # OpenRouter requires these headers on every request.
            headers = {"HTTP-Referer": _OPENROUTER_REFERER, "X-Title": _OPENROUTER_TITLE}
        cfg = self._provider_cfg(name)
        base_url = cfg.get("base_url") or PROVIDER_ENDPOINTS.get(family)
        # v1.15: explicit httpx timeout (connect 5 / read 25 / write 10 /
        # pool 5) + max_retries=0 on the SDK client. The SDK default
        # (600 s timeout, 2 retries) multiplied the router's own retry
        # loop into 172-428 s turns; the router's own loop
        # (max_retries_per_provider in YAML) is the single retry layer.
        # config/providers.yaml timeout_seconds is now unused.
        c = AsyncOpenAI(api_key=self.keys[family], base_url=base_url,
                        timeout=_CLIENT_TIMEOUT, max_retries=0,
                        default_headers=headers)
        self._clients[family] = c
        return c

    async def close(self):
        for c in self._clients.values():
            try:
                await c.close()
            except Exception:
                pass
        self._clients.clear()

    # -- usage / quota (SQLite provider_usage, per entry+model) ------------
    @staticmethod
    def _today_str():
        return time.strftime("%Y-%m-%d", time.gmtime())

    @staticmethod
    def _date_for(family, now=None):
        """Calendar date a family's daily quota resets on.

        Gemini RPD resets at midnight PACIFIC (UTC-8), not UTC — keying
        Gemini usage by the UTC date would over/under-count by up to 8h
        around the reset (see docs/research-quota-capacity.md §1/§3).
        Every other family resets at midnight UTC. `now` is a Unix
        timestamp (default: time.time()); tests pass it explicitly.
        _today_str() stays the plain UTC helper for other callers."""
        ts = time.time() if now is None else now
        if family == "gemini":
            ts -= 8 * 3600
        return time.strftime("%Y-%m-%d", time.gmtime(ts))

    def _family_of(self, name, model=None):
        """Family for an entry name / family name / model id."""
        entry = self._entry(name)
        if entry is not None:
            return entry.get("family") or name
        if model:
            for e in self.entries:
                if e.get("model") == model:
                    return e.get("family") or name
        return name

    def _ensure_usage_table(self, c):
        """Create the v6 provider_usage table, migrating a v0.5-shaped
        one (PRIMARY KEY(provider, date), no model column) in place:
        old rows are copied with model='' and preserved; the new
        PRIMARY KEY is (provider, model, date)."""
        c.execute("""CREATE TABLE IF NOT EXISTS provider_usage
                     (provider TEXT, model TEXT DEFAULT '', date TEXT,
                      requests INTEGER DEFAULT 0, tokens_in INTEGER DEFAULT 0,
                      tokens_out INTEGER DEFAULT 0, exhausted_until REAL,
                      PRIMARY KEY(provider, model, date))""")
        cols = [r[1] for r in c.execute("PRAGMA table_info(provider_usage)")]
        if "model" not in cols:
            c.execute("ALTER TABLE provider_usage ADD COLUMN model TEXT DEFAULT ''")
            c.execute("""CREATE TABLE provider_usage_v2
                         (provider TEXT, model TEXT DEFAULT '', date TEXT,
                          requests INTEGER DEFAULT 0, tokens_in INTEGER DEFAULT 0,
                          tokens_out INTEGER DEFAULT 0, exhausted_until REAL,
                          PRIMARY KEY(provider, model, date))""")
            c.execute("""INSERT INTO provider_usage_v2
                         (provider, model, date, requests, tokens_in, tokens_out, exhausted_until)
                         SELECT provider, COALESCE(model, ''), date, requests,
                                tokens_in, tokens_out, exhausted_until
                         FROM provider_usage""")
            c.execute("DROP TABLE provider_usage")
            c.execute("ALTER TABLE provider_usage_v2 RENAME TO provider_usage")
            logger.info("provider_usage migrated to per-model schema (v0.5 rows kept as model='')")
        c.commit()

    def _resolve_usage_key(self, name, model=None):
        """(provider_col, model_col) for a usage read/write.

        Entry name -> (entry_name, entry_model). Family name ->
        (family, '') — the legacy v0.5 shape. A bare model id resolves
        to its entry."""
        entry = self._entry(name)
        if entry is not None:
            return (entry["name"], model or entry.get("model") or "")
        if model:
            for e in self.entries:
                if e.get("model") == model:
                    return (e["name"], model)
        return (name, model or "")

    def _entry_usage(self, entry):
        """(requests, tokens_in, tokens_out) today for one entry.

        Sums the entry's own per-model row plus any legacy v0.5 row
        (provider=family, model=''), whose model split is unknowable
        so it counts conservatively toward every entry of the family.
        Rows are keyed by the family's reset date (_date_for: Pacific
        for Gemini, UTC otherwise).
        """
        try:
            self.db.parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(self.db)
            try:
                self._ensure_usage_table(c)
                row = c.execute(
                    "SELECT COALESCE(SUM(requests),0), COALESCE(SUM(tokens_in),0), "
                    "COALESCE(SUM(tokens_out),0) FROM provider_usage WHERE date=? AND "
                    "((provider=? AND model=?) OR (provider=? AND model=''))",
                    (self._date_for(entry.get("family")), entry["name"], entry.get("model") or "",
                     entry.get("family") or "")).fetchone()
            finally:
                c.close()
            return (int(row[0] or 0), int(row[1] or 0), int(row[2] or 0))
        except Exception as e:
            logger.warning("provider_usage read failed for %s: %s", entry.get("name"), e)
            return (0, 0, 0)

    def _provider_usage_today(self, name, model=None):
        """(requests, tokens_in, tokens_out) for today — today in the
        family's own reset timezone (_date_for: Pacific for Gemini).

        Back-compat wrapper: an entry name (or entry name + model)
        returns that entry's per-model usage; a family name returns
        the combined usage of the family (legacy rows + all its
        entries' rows)."""
        entry = self._entry(name)
        if entry is not None:
            return self._entry_usage(entry)
        if model:
            for e in self.entries:
                if e.get("model") == model:
                    return self._entry_usage(e)
        try:
            self.db.parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(self.db)
            try:
                self._ensure_usage_table(c)
                names = [e["name"] for e in self.entries if e.get("family") == name]
                placeholders = ",".join("?" for _ in names) if names else "''"
                row = c.execute(
                    f"SELECT COALESCE(SUM(requests),0), COALESCE(SUM(tokens_in),0), "
                    f"COALESCE(SUM(tokens_out),0) FROM provider_usage WHERE date=? AND "
                    f"(provider=? OR provider IN ({placeholders}))",
                    (self._date_for(name), name, *names)).fetchone()
            finally:
                c.close()
            return (int(row[0] or 0), int(row[1] or 0), int(row[2] or 0))
        except Exception as e:
            logger.warning("provider_usage read failed for %s: %s", name, e)
            return (0, 0, 0)

    def _quota_exhausted(self, name, model=None):
        """True if a Retry-After / daily ban is still active for this
        entry (entry name) or family (family name: any of its rows).
        Ban rows are keyed by the family's reset date (_date_for)."""
        try:
            self.db.parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(self.db)
            try:
                self._ensure_usage_table(c)
                provider_col, model_col = self._resolve_usage_key(name, model)
                entry = self._entry(name)
                date = self._date_for(self._family_of(name, model))
                if entry is not None:
                    rows = c.execute(
                        "SELECT exhausted_until FROM provider_usage WHERE date=? AND "
                        "((provider=? AND model=?) OR (provider=? AND model=''))",
                        (date, provider_col, model_col,
                         entry.get("family") or "")).fetchall()
                else:
                    rows = c.execute(
                        "SELECT exhausted_until FROM provider_usage WHERE date=? AND provider=?",
                        (date, provider_col)).fetchall()
            finally:
                c.close()
            return bool(any(r[0] and time.time() < r[0] for r in rows))
        except Exception as e:
            logger.warning("quota check failed for %s: %s", name, e)
            return False

    def _exhausted_until(self, entry):
        """Latest exhausted_until timestamp for one entry's rows today
        (family reset date), or None when no ban row exists / unknown."""
        try:
            self.db.parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(self.db)
            try:
                self._ensure_usage_table(c)
                row = c.execute(
                    "SELECT MAX(exhausted_until) FROM provider_usage WHERE date=? AND "
                    "((provider=? AND model=?) OR (provider=? AND model=''))",
                    (self._date_for(entry.get("family")), entry["name"],
                     entry.get("model") or "", entry.get("family") or "")).fetchone()
            finally:
                c.close()
            val = row[0] if row else None
            return float(val) if val else None
        except Exception as e:
            logger.warning("exhausted_until read failed for %s: %s", entry.get("name"), e)
            return None

    def _mark_exhausted(self, name, seconds=3600, model=None):
        try:
            self.db.parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(self.db)
            try:
                self._ensure_usage_table(c)
                provider_col, model_col = self._resolve_usage_key(name, model)
                c.execute("""INSERT INTO provider_usage(provider, model, date, requests, exhausted_until)
                             VALUES(?,?,?,0,?)
                             ON CONFLICT(provider, model, date) DO UPDATE
                             SET exhausted_until=excluded.exhausted_until""",
                          (provider_col, model_col, self._date_for(self._family_of(name, model)), time.time() + seconds))
                c.commit()
            finally:
                c.close()
        except Exception as e:
            logger.warning("mark exhausted failed for %s: %s", name, e)

    def _record_usage(self, name, tokens_in, tokens_out, model=None):
        try:
            self.db.parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(self.db)
            try:
                self._ensure_usage_table(c)
                provider_col, model_col = self._resolve_usage_key(name, model)
                c.execute("""INSERT INTO provider_usage(provider, model, date, requests, tokens_in, tokens_out)
                             VALUES(?,?,?,?,?,?)
                             ON CONFLICT(provider, model, date) DO UPDATE SET
                             requests=requests+1, tokens_in=tokens_in+excluded.tokens_in,
                             tokens_out=tokens_out+excluded.tokens_out""",
                          (provider_col, model_col, self._date_for(self._family_of(name, model)), 1, tokens_in, tokens_out))
                c.commit()
            finally:
                c.close()
        except Exception as e:
            logger.warning("record usage failed for %s: %s", name, e)

    # -- capacity snapshot (v0.7, for the fair-share quota layer) -----------
    def pool_snapshot(self):
        """One dict per provider entry, in the shape
        memory.compute_pool_remaining(entries, avg_tokens=...) expects:
        {name, family, model, daily_cap_requests, daily_cap_tokens,
        requests_used, tokens_used, disabled, exhausted_until}.
        Usage is read for the family's own reset date (_date_for);
        disabled covers the in-memory 401/403/404 set AND a live ban;
        exhausted_until is None when no ban row exists."""
        out = []
        for e in self.entries:
            reqs, tin, tout = self._entry_usage(e)
            out.append({
                "name": e.get("name"),
                "family": e.get("family"),
                "model": e.get("model"),
                "daily_cap_requests": e.get("daily_cap_requests"),
                "daily_cap_tokens": e.get("daily_cap_tokens"),
                "requests_used": reqs,
                "tokens_used": tin + tout,
                "disabled": e.get("name") in self._disabled or self._quota_exhausted(e["name"]),
                "exhausted_until": self._exhausted_until(e),
            })
        return out

    def _avg_tokens_per_reply(self):
        """Blended average tokens/reply from memory's EWMA (lazy import
        to avoid a brain.memory <-> brain.router cycle); falls back to
        the 1,050 research estimate when memory has not measured any
        calls yet (or the function is missing)."""
        try:
            from brain import memory as _memory
            fn = getattr(_memory, "avg_tokens_per_reply", None)
            if fn is None:
                return _FALLBACK_AVG_TOKENS
            value = float(fn() or 0)
            return value if value > 0 else _FALLBACK_AVG_TOKENS
        except Exception as e:
            logger.warning("avg_tokens_per_reply failed, using fallback: %s", e)
            return _FALLBACK_AVG_TOKENS

    def pool_remaining_replies(self):
        """Capacity in replies, via memory.compute_pool_remaining over
        pool_snapshot() at the measured average tokens/reply:
        {"pool_replies", "full_pool_replies", "avg_tokens", "per_entry"}.
        Fail-CLOSED when memory.compute_pool_remaining is missing (or
        errors): pool_replies 0.0, so the quota layer denies rather than
        overspending a pool it cannot measure."""
        entries = self.pool_snapshot()
        avg = self._avg_tokens_per_reply()
        fallback = {"pool_replies": 0.0, "full_pool_replies": 0.0,
                    "avg_tokens": avg, "per_entry": entries}
        try:
            from brain import memory as _memory
            compute = getattr(_memory, "compute_pool_remaining", None)
            if compute is None:
                logger.warning("compute_pool_remaining missing — capacity fail-closed at 0")
                return fallback
            try:
                result = compute(entries, avg_tokens=avg)
            except TypeError:
                result = compute(entries, avg)
            if not isinstance(result, dict) or "pool_replies" not in result:
                logger.warning("compute_pool_remaining returned no pool_replies — fail-closed")
                return fallback
            result.setdefault("full_pool_replies", result.get("pool_replies", 0.0))
            result.setdefault("avg_tokens", avg)
            result.setdefault("per_entry", entries)
            return result
        except Exception as e:
            logger.warning("pool_remaining_replies failed, fail-closed: %s", e)
            return fallback

    def _record_reply_tokens(self, intent, total_tokens):
        """Feed one successful reply's cost (prompt + completion tokens,
        reasoning included in completion_tokens) into memory's EWMA.
        Called exactly once per successful chat() reply; a missing
        memory function is a no-op (never crashes the reply)."""
        try:
            from brain import memory as _memory
            fn = getattr(_memory, "record_reply_tokens", None)
            if fn is None:
                return
            fn(intent, int(total_tokens))
        except Exception as e:
            logger.warning("record_reply_tokens failed: %s", e)

    # -- routing ------------------------------------------------------------
    def _remaining_fraction(self, entry):
        """Fraction of daily budget left (min over request/token caps);
        1.0 when uncapped. Used for least-used-first ordering."""
        reqs, tin, tout = self._entry_usage(entry)
        fracs = []
        rc = entry.get("daily_cap_requests")
        if rc:
            try:
                fracs.append(max(0.0, (float(rc) - reqs) / float(rc)))
            except (TypeError, ValueError):
                pass
        tc = entry.get("daily_cap_tokens")
        if tc:
            try:
                fracs.append(max(0.0, (float(tc) - (tin + tout)) / float(tc)))
            except (TypeError, ValueError):
                pass
        return min(fracs) if fracs else 1.0

    def _entry_blocked(self, entry):
        """Daily cap hit (requests / tokens) or a live ban. OpenRouter's
        50 req/day cap is account-wide, so it sums all OpenRouter entries."""
        reqs, tin, tout = self._entry_usage(entry)
        rc = entry.get("daily_cap_requests")
        if rc:
            try:
                if reqs >= int(rc):
                    return True
            except (TypeError, ValueError):
                pass
        tc = entry.get("daily_cap_tokens")
        if tc:
            try:
                if tin + tout >= int(tc):
                    return True
            except (TypeError, ValueError):
                pass
        if entry.get("family") == "openrouter":
            caps = [e.get("daily_cap_requests") for e in self.entries
                    if e.get("family") == "openrouter" and e.get("daily_cap_requests")]
            if caps:
                total = sum(self._entry_usage(e)[0] for e in self.entries
                            if e.get("family") == "openrouter")
                if total >= min(int(x) for x in caps):
                    return True
        return self._quota_exhausted(entry["name"])

    def _rpm_guard_active(self, entry):
        """Gemma TPM guard: min seconds between calls for this entry."""
        try:
            guard = float(entry.get("rpm_guard_seconds") or 0)
        except (TypeError, ValueError):
            return False
        if guard <= 0:
            return False
        last = self._last_call.get(entry["name"])
        if last is None:
            return False
        return (time.monotonic() - last) < guard

    def _build_plan(self, hard, cheap_only=False):
        """Preference-ordered entries for this tier, least-used first.

        Order comes from routing.simple_order / hard_order in YAML;
        the stable sort by remaining budget fraction only reorders
        entries whose usage differs (ties keep YAML order).
        cheap_only=True (degraded mode) filters the plan to the cheap
        tiers only — never gemini-3-flash-preview or nvidia-nemotron
        as a primary in cheap mode."""
        routing = self.cfg.get("routing", {}) or {}
        order = routing.get("hard_order" if hard else "simple_order") or \
            [e["name"] for e in self.entries]
        by_name = {e["name"]: e for e in self.entries}
        plan = []
        for name in order:
            e = by_name.get(name)
            if e is None:
                continue
            if cheap_only and name not in _CHEAP_ENTRY_NAMES:
                continue
            if not self.keys.get(e.get("family")):
                continue
            if name in self._disabled:
                continue
            tier = e.get("tier", "both")
            if hard and tier not in ("hard", "both"):
                continue
            if not hard and tier not in ("simple", "both"):
                continue
            plan.append(e)
        plan.sort(key=self._remaining_fraction, reverse=True)
        return plan

    def _disable_entry(self, entry, status, exc):
        """401/403/404: bad key, retired model, or a free tier that no
        longer exists (e.g. Cerebras). Disable in-memory, log
        server-side only — never a group-facing message."""
        self._disabled.add(entry["name"])
        logger.warning("provider entry %s disabled (status=%s, model=%s): %s",
                       entry["name"], status, entry.get("model"), exc)

    # -- tokens -------------------------------------------------------------
    @staticmethod
    def estimate_tokens(text: str) -> int:
        # Arabic ~0.5-0.66 tokens/char (see module docstring); len//3 (0.33)
        # undercounted ~2x, so every downstream token decision was wrong 2x.
        return max(1, len(text) // 2)

    # -- main entry ---------------------------------------------------------
    async def chat(self, messages, hard=False, temperature=None, max_tokens=None,
                   cheap_only=False, intent=None, turn_id=None, step=None,
                   exclude_providers=None):
        """cheap_only: restrict the plan to the cheap tiers (degraded
        mode). intent: the caller's intent ("chat"/"search"/...), used
        only as the EWMA bucket for memory.record_reply_tokens — called
        exactly once per successful reply with tin+tout (reasoning
        tokens are inside completion_tokens).
        v1.15: turn_id/step tag every telemetry row of this call (one
        turn_id per handler turn, propagated by the handler); step
        names the call ("main", "search_retry", ...). exclude_providers
        is a set of family names to skip — the roast retry uses it to
        go to the OTHER provider after a refusal, never the same model.
        last_call_meta (dict) holds the latest attempt's structured
        signal (provider/model/finish_reason/refusal/http_status) for
        the handler's refusal check; {} when no attempt ran."""
        if not any(self.keys.values()):
            return (NO_KEYS_MSG, "none", 0)
        if temperature is None:
            temperature = 0.25 if hard else 0.7
        turn_id = turn_id or _telemetry.new_turn_id()
        step = step or "main"
        self.last_call_meta = {}

        plan = self._build_plan(hard, cheap_only=cheap_only)
        if exclude_providers:
            plan = [e for e in plan
                    if e.get("family") not in exclude_providers]
        if not plan:
            return (NO_KEYS_MSG, "none", 0)

        est_in = self.estimate_tokens(" ".join(
            str(m.get("content", "")) for m in messages if isinstance(m, dict)))
        attempts = self._max_retries() + 1
        last_err = None
        for entry in plan:
            name, family, model = entry["name"], entry.get("family"), entry.get("model")
            if name in self._disabled:
                continue
            if self._entry_blocked(entry):
                continue
            if self._rpm_guard_active(entry):
                logger.info("rpm guard skipping %s", name)
                continue
            breaker = self.breakers.setdefault(name, CircuitBreaker())
            if not breaker.allow():
                continue
            if max_tokens is not None:
                mct = max_tokens
            else:
                mct = self._output_tokens(family)
            # Groq 8,000 TPM window: keep estimated prompt + max output < 7,500.
            if family == "groq" and est_in + mct > 7500:
                mct = max(400, 7500 - est_in)
            try:
                client = self._client(family)
            except Exception as e:
                logger.exception("router client %s error", family)
                last_err = e
                continue
            kwargs = _completion_kwargs(
                family, model, messages, temperature, mct, hard)
            self._last_call[name] = time.monotonic()
            length_retried = False
            for attempt in range(attempts):
                t0 = time.perf_counter()
                try:
                    resp = await client.chat.completions.create(**kwargs)
                    text = resp.choices[0].message.content or ""
                    finish = getattr(resp.choices[0], "finish_reason", None) if resp.choices else None
                    usage = getattr(resp, "usage", None)
                    tin = getattr(usage, "prompt_tokens", 0) or est_in
                    tout = getattr(usage, "completion_tokens", 0) or self.estimate_tokens(text)
                    reasoning = _reasoning_tokens(usage)
                    cached = _cached_tokens(usage)
                    refused, finish = _refusal_signal(resp)
                    if refused:
                        # v1.15: structured refusal (message.refusal /
                        # content_filter / SAFETY) — no usable reply.
                        # Do NOT retry this entry: the same model
                        # refuses again. Record it and move to the
                        # next entry in the plan.
                        self.last_call_meta = {
                            "provider": family, "model": model,
                            "finish_reason": finish, "refusal": True,
                            "http_status": 200,
                        }
                        _record_attempt(
                            turn_id, step, family, model,
                            (time.perf_counter() - t0) * 1000,
                            finish_reason=finish, tokens_in=tin,
                            tokens_out=tout, temperature=temperature,
                            outcome="refused_structured")
                        last_err = RuntimeError("refused by provider")
                        break
                    if finish == "length":
                        # v1.13: a length-truncated draft must NEVER be
                        # sent as-is (live 2026-11-27: replies cut off
                        # mid-word, one consisting of only the opener).
                        # Reasoning tokens count against
                        # max_completion_tokens, so a reasoning-heavy
                        # turn can eat the whole budget before the
                        # visible reply starts. Retry once with a
                        # doubled cap.
                        # v1.17: if the retry ALSO truncates, do NOT
                        # return the truncated draft (the v1.13 code
                        # did — "return the longest draft we have" —
                        # which shipped 3/38 mid-word replies live in
                        # v1.16). Treat this entry as failed for the
                        # turn and try the NEXT entry in the plan; if
                        # every entry truncates, chat() falls through
                        # to the short honest FAIL_MSG below — never a
                        # mid-word fragment.
                        logger.warning("reply truncated by length, provider=%s entry=%s", family, name)
                        if family == "groq":
                            new_mct = min(mct * 2, max(mct, 7500 - est_in))
                        else:
                            new_mct = min(mct * 2, 6000)
                        if not length_retried and new_mct > mct:
                            length_retried = True
                            mct = new_mct
                            kwargs["max_completion_tokens"] = mct
                            continue
                        self._record_usage(name, tin, tout, model=model)
                        breaker.record_success()
                        self._record_reply_tokens(intent or "chat", tin + tout)
                        logger.info(json.dumps({
                            "provider": family, "entry": name, "model": model,
                            "latency_ms": int((time.perf_counter() - t0) * 1000),
                            "tokens_in": tin, "tokens_out": tout,
                            "reasoning_tokens": reasoning, "cached_tokens": cached,
                            "finish_reason": finish,
                            "max_tokens": mct,
                            "retries": attempt, "status": "ok",
                            "truncated": True,
                        }, ensure_ascii=False))
                        self.last_call_meta = {
                            "provider": family, "model": model,
                            "finish_reason": finish, "refusal": False,
                            "http_status": 200,
                        }
                        _record_attempt(
                            turn_id, step, family, model,
                            (time.perf_counter() - t0) * 1000,
                            finish_reason=finish, tokens_in=tin,
                            tokens_out=tout,
                            temperature=temperature, outcome="truncated")
                        last_err = RuntimeError(
                            "reply truncated twice by length")
                        break
                    if not text.strip():
                        raise RuntimeError("empty reply from model")
                    self._record_usage(name, tin, tout, model=model)
                    breaker.record_success()
                    # EWMA input: exactly once per successful reply.
                    self._record_reply_tokens(intent or "chat", tin + tout)
                    logger.info(json.dumps({
                        "provider": family, "entry": name, "model": model,
                        "latency_ms": int((time.perf_counter() - t0) * 1000),
                        "tokens_in": tin, "tokens_out": tout,
                        "reasoning_tokens": reasoning, "cached_tokens": cached,
                        "finish_reason": finish,
                        "max_tokens": mct,
                        "retries": attempt, "status": "ok",
                    }, ensure_ascii=False))
                    self.last_call_meta = {
                        "provider": family, "model": model,
                        "finish_reason": finish, "refusal": False,
                        "http_status": 200,
                    }
                    _record_attempt(
                        turn_id, step, family, model,
                        (time.perf_counter() - t0) * 1000,
                        finish_reason=finish, tokens_in=tin,
                        tokens_out=tout, temperature=temperature)
                    return (text, family, tout)
                except asyncio.CancelledError:
                    # The turn deadline (or shutdown) cancelled the
                    # call mid-flight: record it, then re-raise so
                    # the deadline converts it to TimeoutError.
                    _record_attempt(
                        turn_id, step, family, model,
                        (time.perf_counter() - t0) * 1000,
                        temperature=temperature, error_kind="cancelled",
                        outcome="error")
                    raise
                except Exception as e:
                    status = _status_of(e)
                    latency_ms = int((time.perf_counter() - t0) * 1000)
                    last_err = e
                    self.last_call_meta = {
                        "provider": family, "model": model,
                        "finish_reason": None, "refusal": False,
                        "http_status": status,
                    }
                    _record_attempt(
                        turn_id, step, family, model, latency_ms,
                        status="error", http_status=status,
                        retry_after=_retry_after(e),
                        temperature=temperature,
                        error_kind=_error_kind(e, status),
                        outcome="blocked_400" if status == 400 else "error")
                    if status == 429:
                        kind, seconds = _classify_429(e, _retry_after(e))
                        self._mark_exhausted(name, seconds=seconds, model=model)
                        breaker.record_failure()
                        logger.info(json.dumps({
                            "provider": family, "entry": name, "model": model,
                            "latency_ms": latency_ms,
                            "tokens_in": 0, "tokens_out": 0, "reasoning_tokens": 0,
                            "cached_tokens": 0,
                            "finish_reason": None, "retries": attempt, "status": "error",
                            "error_code": 429, "rate_limit_kind": kind,
                        }, ensure_ascii=False))
                        break
                    if status is not None and status in _DISABLE_STATUS:
                        self._disable_entry(entry, status, e)
                        breaker.record_failure()
                        logger.info(json.dumps({
                            "provider": family, "entry": name, "model": model,
                            "latency_ms": latency_ms,
                            "tokens_in": 0, "tokens_out": 0, "reasoning_tokens": 0,
                            "cached_tokens": 0,
                            "finish_reason": None, "retries": attempt, "status": "error",
                            "error_code": status, "disabled": True,
                        }, ensure_ascii=False))
                        break
                    if status is not None and status not in TRANSIENT:
                        logger.warning("provider %s entry %s failed fast status=%s: %s",
                                       family, name, status, e)
                        breaker.record_failure()
                        logger.info(json.dumps({
                            "provider": family, "entry": name, "model": model,
                            "latency_ms": latency_ms,
                            "tokens_in": 0, "tokens_out": 0, "reasoning_tokens": 0,
                            "cached_tokens": 0,
                            "finish_reason": None, "retries": attempt, "status": "error",
                            "error_code": status,
                        }, ensure_ascii=False))
                        break
                    if attempt == attempts - 1:
                        breaker.record_failure()
                        logger.info(json.dumps({
                            "provider": family, "entry": name, "model": model,
                            "latency_ms": latency_ms,
                            "tokens_in": 0, "tokens_out": 0, "reasoning_tokens": 0,
                            "cached_tokens": 0,
                            "finish_reason": None, "retries": attempt, "status": "error",
                            "error_code": status,
                        }, ensure_ascii=False))
                        break
                    wait = random.uniform(0, min(6.0, 0.4 * (2 ** attempt)))
                    ra = _retry_after(e, 0) or 0
                    await asyncio.sleep(max(wait, ra))
        if last_err is not None:
            logger.warning("all providers failed: %s", last_err)
        return (FAIL_MSG, "none", 0)
