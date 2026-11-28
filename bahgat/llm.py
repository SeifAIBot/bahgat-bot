"""LLM client — ordered multi-provider fallback.

config/providers.yaml lists the providers in the order they are tried. Each
entry is an OpenAI-compatible endpoint: base_url + model + the env var that
holds its key + its own timeout. chat() walks the chain and returns the
first usable answer; a failure (network error, timeout, rate limit, empty
completion, content refusal) moves to the next entry. 401/403/404 means a
dead key or a retired model, so that entry is dropped for the rest of the
process run.

Keys come from env vars (or .env through Settings), never from code. There
is no quota tracking or fair-share here on purpose: the fallback chain is
the capacity plan, and bahgat/stats.py keeps the minimal counters.

v2.2: per-attempt timeout 15 s (20 s NVIDIA), total turn budget ~30 s,
one retry only for 429/5xx/timeout honouring Retry-After, and a 10-minute
cooldown after 2 consecutive failures (LiteLLM cooldown in miniature).
"""
import asyncio
import logging
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from bahgat import stats

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 400
DEFAULT_TIMEOUT_SECONDS = 15.0
# Whole-turn budget across the chain (expert review §1): beyond this a
# Telegram user re-triggers anyway, so serve a bank reply instead.
TURN_BUDGET_SECONDS = 30.0
# Consecutive failures before a provider is cooled down, and for how long.
COOLDOWN_AFTER_FAILURES = 2
COOLDOWN_SECONDS = 600.0
# Statuses worth exactly one retry (same entry, short backoff).
_RETRYABLE_STATUS = (408, 429, 500, 502, 503, 504)

# Auth / not-found / retired model: the entry will never work in this
# process, so stop paying a round-trip for it.
_DISABLE_STATUS = (401, 403, 404)
# finish_reason values that mean the provider filtered the answer
# (OpenAI "content_filter"; Gemini via the OpenAI-compat "SAFETY").
_REFUSAL_FINISH_REASONS = frozenset({"content_filter", "safety"})

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "providers.yaml"

# Base URLs used when an entry leaves base_url out of the YAML.
FAMILY_ENDPOINTS = {
    "groq": "https://api.groq.com/openai/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}

# Groq sits behind Cloudflare and 403s the default Python UA.
_GROQ_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class Provider:
    """One entry of the fallback chain."""

    name: str
    family: str
    model: str
    base_url: str
    env_key: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


def load_providers(path=None) -> list:
    """Read config/providers.yaml into Provider objects, in chain order.

    File order is the chain order. An optional `routing.order` list of
    entry names overrides it without moving blocks around."""
    p = Path(path) if path else _CONFIG_PATH
    if not p.exists():
        raise LLMError(f"provider config missing: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise LLMError(f"provider config is not valid YAML ({p}): {e}") from e

    providers = []
    for entry in raw.get("providers") or []:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        name = str(entry["name"]).strip()
        family = str(entry.get("family") or name).strip().lower()
        model = str(entry.get("model") or "").strip()
        base_url = str(entry.get("base_url") or FAMILY_ENDPOINTS.get(family, "")).strip()
        env_key = str(entry.get("env_key") or "").strip()
        if not (model and base_url and env_key):
            logger.warning("provider entry %s skipped: model/base_url/env_key "
                           "incomplete", name)
            continue
        try:
            timeout = float(entry.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT_SECONDS
        providers.append(Provider(name=name, family=family, model=model,
                                  base_url=base_url, env_key=env_key,
                                  timeout_seconds=timeout))

    order = (raw.get("routing") or {}).get("order") or []
    if order:
        by_name = {p_.name: p_ for p_ in providers}
        ranked = [by_name[n] for n in order if n in by_name]
        unknown = [n for n in order if n not in by_name]
        if unknown:
            logger.warning("routing.order names unknown entries: %s", unknown)
        providers = ranked + [p_ for p_ in providers if p_.name not in set(order)]
    return providers


def _status_of(exc) -> int | None:
    """HTTP status of an SDK error, when it carries one."""
    for attr in ("status_code", "status", "http_status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def _classify_error(exc) -> str:
    """Bucket an exception into a stats status (expert review §1.2)."""
    status = _status_of(exc)
    if status == 429:
        return "rate_limited"
    if status in (401, 403):
        return "auth"
    if status == 404:
        return "not_found"
    if isinstance(exc, asyncio.TimeoutError) or "imeout" in type(exc).__name__:
        return "timeout"
    return "error"


def _retry_after_seconds(exc) -> float | None:
    """Retry-After (seconds) from an error's response headers, if any."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    raw = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def _ordered(providers, settings) -> list:
    """Apply the optional chain / primary overrides from settings."""
    chain_env = (getattr(settings, "llm_chain", "") or "").strip()
    if chain_env:
        picked = []
        for wanted in (w.strip().lower() for w in chain_env.split(",")):
            if not wanted:
                continue
            matched = [p for p in providers
                       if p.name.lower() == wanted or p.family.lower() == wanted]
            if not matched:
                logger.warning("LLM_CHAIN names unknown provider %r — ignored", wanted)
            for p in matched:
                if p not in picked:
                    picked.append(p)
        if picked:
            return picked

    # Legacy single-provider var: move that family to the front, keep the
    # rest of the chain behind it so a dead provider still falls back.
    family = (getattr(settings, "llm_provider", "") or "").strip().lower()
    if family:
        front = [p for p in providers
                 if p.family.lower() == family or p.name.lower() == family]
        if front:
            return front + [p for p in providers if p not in front]
        logger.warning("LLM_PROVIDER names unknown provider %r — using the "
                       "full chain", family)
    return list(providers)


class LLMClient:
    def __init__(self, settings, providers=None):
        providers = list(providers if providers is not None else load_providers())
        if not providers:
            raise LLMError("no providers configured — see config/providers.yaml")
        providers = _ordered(providers, settings)

        # Legacy single-provider overrides: they retarget the FIRST entry
        # only, so the rest of the chain still backs it up.
        first = providers[0]
        model = (getattr(settings, "llm_model", "") or "").strip()
        base_url = (getattr(settings, "llm_base_url", "") or "").strip()
        if model or base_url:
            providers[0] = replace(first, model=model or first.model,
                                   base_url=base_url or first.base_url)
        self._settings = settings
        self._primary_name = providers[0].name
        self._primary_key = (getattr(settings, "llm_api_key", "") or "").strip()

        chain, missing = [], []
        for provider in providers:
            if not self._key_for(provider):
                missing.append(provider.env_key)
                continue
            chain.append(provider)
        if not chain:
            keys = ", ".join(dict.fromkeys(missing)) or "GROQ_API_KEY"
            raise LLMError(f"no LLM provider has a key set — set one of "
                           f"{keys} in .env, never in code")

        self.chain = chain
        self.missing = list(dict.fromkeys(missing))
        self._disabled = set()
        self._fail_streak: dict[str, int] = {}
        self._clients = {}
        self.last_provider = None
        logger.info("LLM chain (%d): %s%s", len(chain),
                    ", ".join(p.name for p in chain),
                    f" | no key: {', '.join(self.missing)}" if missing else "")

    # -- keys --------------------------------------------------------------
    @staticmethod
    def _key(settings, provider) -> str:
        """The provider's key: Settings (which reads .env) first, then the
        process environment. Never logged, never returned to callers."""
        value = getattr(settings, provider.env_key.lower(), "") or ""
        if not value:
            value = os.environ.get(provider.env_key, "")
        return (value or "").strip()

    def _key_for(self, provider) -> str:
        """Key used for this entry (LLM_API_KEY pins the first one)."""
        if provider.name == self._primary_name and self._primary_key:
            return self._primary_key
        return self._key(self._settings, provider)

    # -- clients -----------------------------------------------------------
    def _client(self, provider):
        """One AsyncOpenAI client per entry, created on first use.

        max_retries=0: the SDK's own retries would multiply this chain's
        walk into minutes-long turns. The chain's own retry (<=1, only
        for 429/5xx/timeout, honouring Retry-After) lives in _attempt()."""
        client = self._clients.get(provider.name)
        if client is not None:
            return client
        # Lazy import: the openai package is only needed at runtime, not for
        # tests of the rest of the bot.
        from openai import AsyncOpenAI

        headers = None
        if provider.family == "groq":
            headers = _GROQ_HEADERS
        client = AsyncOpenAI(
            api_key=self._key_for(provider),
            base_url=provider.base_url,
            timeout=provider.timeout_seconds,
            max_retries=0,
            default_headers=headers,
        )
        self._clients[provider.name] = client
        return client

    # -- main entry --------------------------------------------------------
    async def chat(self, messages, temperature=0.7,
                   max_tokens=DEFAULT_MAX_TOKENS) -> str:
        """Walk the chain. Returns the first usable reply text (stripped).
        Raises LLMError only when every provider failed or the whole-turn
        budget (~30 s) ran out — the caller then serves a bank reply."""
        deadline = time.monotonic() + TURN_BUDGET_SECONDS
        failures = []
        for idx, provider in enumerate(self.chain):
            if provider.name in self._disabled or stats.is_dead(provider.name):
                continue
            if time.monotonic() >= deadline:
                failures.append("turn budget exceeded")
                break
            t0 = time.monotonic()
            next_name = next(
                (p.name for p in self.chain[idx + 1:]
                 if p.name not in self._disabled
                 and not stats.is_dead(p.name)),
                None)
            try:
                text = await self._attempt(provider, messages, temperature,
                                           max_tokens, deadline)
            except LLMError as e:  # empty completion / filtered answer
                status = "blocked" if "refused" in str(e) else "empty"
                stats.record(provider.name, provider.model, status,
                             (time.monotonic() - t0) * 1000,
                             fallback_to=next_name)
                self._note_failure(provider, status)
                logger.warning("provider %s gave no usable answer: %s",
                               provider.name, e)
                failures.append(f"{provider.name}: {e}")
                continue
            except Exception as e:  # network / timeout / rate limit / API
                status = _classify_error(e)
                stats.record(provider.name, provider.model, status,
                             (time.monotonic() - t0) * 1000,
                             fallback_to=next_name)
                if _status_of(e) in _DISABLE_STATUS:
                    self._disabled.add(provider.name)
                    logger.warning(
                        "provider %s disabled for this run (status=%s, "
                        "model=%s) — bad key or retired model",
                        provider.name, _status_of(e), provider.model)
                else:
                    logger.warning("provider %s failed (%s%s)",
                                   provider.name, type(e).__name__,
                                   f", status={_status_of(e)}"
                                   if _status_of(e) else "")
                self._note_failure(provider, status)
                failures.append(f"{provider.name}: {type(e).__name__}"
                                f"{f' {_status_of(e)}' if _status_of(e) else ''}")
                continue
            stats.record(provider.name, provider.model, "ok",
                         (time.monotonic() - t0) * 1000)
            self._fail_streak[provider.name] = 0
            self.last_provider = provider.name
            return text
        raise LLMError("every LLM provider failed — " + "; ".join(failures))

    def _note_failure(self, provider, status: str) -> None:
        """Consecutive-failure streak; 2 in a row cools the provider down
        for 10 minutes (LiteLLM cooldown in miniature)."""
        streak = self._fail_streak.get(provider.name, 0) + 1
        self._fail_streak[provider.name] = streak
        if streak >= COOLDOWN_AFTER_FAILURES:
            stats.mark_dead(provider.name, status, COOLDOWN_SECONDS)
            logger.warning("provider %s cooled down for %ds after %d "
                           "consecutive failures (%s)",
                           provider.name, COOLDOWN_SECONDS, streak, status)

    async def _attempt(self, provider, messages, temperature, max_tokens,
                       deadline) -> str:
        """One entry, with at most one retry for 429/5xx/timeout,
        honouring Retry-After. Empty completions and refusals are never
        retried — the same prompt fails the same way twice."""
        last_exc = None
        for attempt_no in range(2):
            try:
                client = self._client(provider)
                resp = await client.chat.completions.create(
                    model=provider.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                choice = resp.choices[0] if getattr(resp, "choices", None) else None
                finish = (getattr(choice, "finish_reason", "") or "").lower()
                if finish in _REFUSAL_FINISH_REASONS:
                    raise LLMError(f"refused ({finish})")
                message = getattr(choice, "message", None)
                text = (getattr(message, "content", "") or "").strip()
                if not text:
                    raise LLMError("empty completion")
                return text
            except LLMError:
                raise
            except Exception as e:
                last_exc = e
                status = _status_of(e)
                is_timeout = (isinstance(e, asyncio.TimeoutError)
                              or "imeout" in type(e).__name__)
                retryable = (status in _RETRYABLE_STATUS) or is_timeout
                if attempt_no == 0 and retryable:
                    wait = min(_retry_after_seconds(e) or 1.0, 2.0)
                    if time.monotonic() + wait < deadline:
                        await asyncio.sleep(wait)
                        continue
                raise
        raise last_exc  # pragma: no cover - loop always raises first

    # -- introspection -----------------------------------------------------
    @property
    def provider_name(self) -> str:
        """First entry of the chain (kept for logs and compatibility)."""
        return self.chain[0].name

    @property
    def model(self) -> str:
        return self.chain[0].model

    async def close(self):
        for client in self._clients.values():
            try:
                await client.close()
            except Exception:
                pass
        self._clients.clear()
