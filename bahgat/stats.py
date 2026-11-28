"""Minimal observability — RED counters, stdlib only (expert review §5).

In-memory, last-100-calls window, no server, no exporter, no database.
One JSON log line per LLM call (lengths, never prompts or replies) and
one owner-only /stats command. If the bot ever grows, these counters map
1:1 onto prometheus_client without changing call sites.

Never use user_id, chat_id, username, prompt text or model output as a
label — that is the cardinality explosion the guides warn about.
"""
import collections
import json
import logging
import statistics
import time

logger = logging.getLogger(__name__)

# provider -> {"ok": n, "timeout": n, "rate_limited": n, "auth": n,
#              "not_found": n, "empty": n, "blocked": n, "error": n}
_requests: dict[str, dict[str, int]] = collections.defaultdict(
    lambda: collections.defaultdict(int))
_fallbacks: dict[str, int] = collections.defaultdict(int)
_bank_fallbacks: dict[str, int] = collections.defaultdict(int)
# (provider, model) -> deque of durations in ms, capped at 100
_durations: dict[tuple[str, str], collections.deque] = collections.defaultdict(
    lambda: collections.deque(maxlen=100))
_dead: dict[str, dict] = {}  # provider -> {"reason": str, "until": float}


def record(provider: str, model: str, status: str, ms: float,
           fallback_to: str | None = None) -> None:
    """One LLM attempt: count it, time it, log one JSON line."""
    _requests[provider][status] += 1
    _durations[(provider, model)].append(ms)
    if fallback_to:
        _fallbacks[f"{provider}->{fallback_to}"] += 1
    logger.info(json.dumps({
        "event": "llm_call", "provider": provider, "model": model,
        "status": status, "ms": round(ms, 1),
        **({"fallback_to": fallback_to} if fallback_to else {}),
    }, ensure_ascii=False))


def record_bank_fallback(reason: str) -> None:
    """A turn answered from the bank because the LLM chain failed."""
    _bank_fallbacks[reason] += 1


def mark_dead(provider: str, reason: str, cooldown_seconds: float = 600) -> None:
    _dead[provider] = {"reason": reason, "until": time.monotonic() + cooldown_seconds}


def is_dead(provider: str) -> bool:
    entry = _dead.get(provider)
    if not entry:
        return False
    if time.monotonic() >= entry["until"]:
        del _dead[provider]
        return False
    return True


def snapshot() -> dict:
    """Plain-dict view for /stats: per-provider counts, success rate,
    p50/p95 latency, dead/cooled-down providers, bank fallbacks."""
    providers = {}
    for provider, counts in _requests.items():
        total = sum(counts.values())
        ok = counts.get("ok", 0)
        times = sorted(
            ms for (p, _m), dq in _durations.items() if p == provider for ms in dq)
        providers[provider] = {
            "total": total,
            "ok": ok,
            "success_rate": round(ok / total, 2) if total else 0.0,
            "failures": {k: v for k, v in counts.items() if k != "ok" and v},
            "p50_ms": round(statistics.median(times)) if times else None,
            "p95_ms": (round(times[min(len(times) - 1, int(len(times) * 0.95))])
                       if times else None),
            "dead": is_dead(provider),
        }
    return {
        "providers": providers,
        "fallbacks": dict(_fallbacks),
        "bank_fallbacks": dict(_bank_fallbacks),
    }


def reset() -> None:
    _requests.clear()
    _fallbacks.clear()
    _bank_fallbacks.clear()
    _durations.clear()
    _dead.clear()
