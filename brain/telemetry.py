"""LLM call + turn instrumentation (v1.15, research report §2.3).

Two SQLite tables in the same bahgat.db the rest of the bot uses:

- ``llm_calls`` — one row per low-level provider attempt (every
  ``client.chat.completions.create`` call, success or failure), timed
  with ``time.perf_counter()``. TTFT equals total for non-streaming
  calls (there is no first token to time before the whole response
  arrives); the column exists so a future streaming call can fill it
  in properly.
- ``turns`` — one row per handler turn: wall-clock total, how many
  router.chat() calls it made, the final outcome, and a reply preview
  (<= 80 chars).

METADATA ONLY — no prompts, no completions, no user text are ever
stored here. The reply preview is the only user-visible text, and it
is capped at 80 chars (the same cap the report specifies).

Every function here is defensive: telemetry must never break a turn,
so any SQLite error is logged and swallowed (the caller gets None /
an empty list). ``DB_PATH`` is a module attribute so tests can point
it at a throwaway DB (see tests/conftest.py ``tmp_db``).
"""
import logging
import sqlite3
import time
import uuid

from core.config import data_dir

logger = logging.getLogger("bahgat")

DB_PATH = data_dir() / "bahgat.db"

# Outcome vocabulary for llm_calls.outcome (research report §1.4):
# ok = the call returned a usable reply; refused_structured = the
# provider signalled a refusal (choice.message.refusal, or a
# content_filter / SAFETY finish reason); refused_text /
# refused_canned / missing_line = the roast-path text checks (see
# brain/reply_bank.is_refusal_or_deflection); blocked_400 = the
# provider answered HTTP 400; fallback_rescued = a cross-provider
# retry produced a good reply after a refusal; bank_sent = the turn
# ended by sending a bank line verbatim. Transport failures use
# "error" with error_kind saying which (timeout / rate_limit / http /
# api / cancelled) — they are not roast outcomes.
# A turn counts as "slow" for /diag at 10 s of wall clock — well under
# the 60 s turn deadline, so slow turns show up before they time out.
SLOW_TURN_MS = 10_000


def new_turn_id() -> str:
    """Short unique id for one handler turn (propagated to every LLM
    call the turn makes)."""
    return uuid.uuid4().hex[:12]


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _ensure_tables(c) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS llm_calls (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   turn_id TEXT, step TEXT, provider TEXT, model TEXT,
                   started_at REAL, ttft_ms REAL, total_ms REAL,
                   status TEXT, http_status INTEGER,
                   finish_reason TEXT, tokens_in INTEGER,
                   tokens_out INTEGER, retry_after REAL,
                   prompt_version TEXT, temperature REAL,
                   error_kind TEXT, outcome TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS turns (
                   turn_id TEXT PRIMARY KEY, chat_id INTEGER,
                   user_id INTEGER, kind TEXT, started_at REAL,
                   total_ms REAL, calls INTEGER, outcome TEXT,
                   reply_preview TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_llm_calls_turn "
              "ON llm_calls(turn_id, id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_llm_calls_provider "
              "ON llm_calls(provider, started_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_turns_started "
              "ON turns(started_at)")


def init_telemetry() -> None:
    """Create the tables (idempotent). Safe to call at startup."""
    try:
        c = _conn()
        try:
            _ensure_tables(c)
            c.commit()
        finally:
            c.close()
    except Exception:
        logger.warning("telemetry init failed", exc_info=True)


def record_llm_call(turn_id, step, provider, model, total_ms, *,
                    ttft_ms=None, status="ok", http_status=None,
                    finish_reason=None, tokens_in=None, tokens_out=None,
                    retry_after=None, prompt_version="", temperature=None,
                    error_kind=None, outcome="ok"):
    """Insert one llm_calls row. Returns the row id, or None when the
    write failed (telemetry never raises)."""
    try:
        c = _conn()
        try:
            _ensure_tables(c)
            cur = c.execute(
                """INSERT INTO llm_calls
                   (turn_id, step, provider, model, started_at,
                    ttft_ms, total_ms, status, http_status,
                    finish_reason, tokens_in, tokens_out, retry_after,
                    prompt_version, temperature, error_kind, outcome)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (turn_id, step, provider, model, time.time(),
                 total_ms if ttft_ms is None else ttft_ms, total_ms,
                 status, http_status, finish_reason, tokens_in,
                 tokens_out, retry_after, prompt_version, temperature,
                 error_kind, outcome))
            c.commit()
            return cur.lastrowid
        finally:
            c.close()
    except Exception:
        logger.warning("telemetry record_llm_call failed", exc_info=True)
        return None


def update_call_outcome(turn_id, step, outcome) -> None:
    """Overwrite the outcome of the LATEST llm_calls row for
    (turn_id, step) — used by the handler when a later check regrades
    a call (e.g. a retry that rescued a refused roast)."""
    try:
        c = _conn()
        try:
            _ensure_tables(c)
            c.execute(
                """UPDATE llm_calls SET outcome=? WHERE id = (
                       SELECT id FROM llm_calls
                       WHERE turn_id=? AND step=?
                       ORDER BY id DESC LIMIT 1)""",
                (outcome, turn_id, step))
            c.commit()
        finally:
            c.close()
    except Exception:
        logger.warning("telemetry update_call_outcome failed", exc_info=True)


def record_turn(turn_id, chat_id, user_id, kind, total_ms, calls,
                outcome, reply_preview=""):
    """Insert one turns row (INSERT OR REPLACE — a turn id is written
    once, but a re-record after a crash must not raise)."""
    try:
        c = _conn()
        try:
            _ensure_tables(c)
            c.execute(
                """INSERT OR REPLACE INTO turns
                   (turn_id, chat_id, user_id, kind, started_at,
                    total_ms, calls, outcome, reply_preview)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (turn_id, chat_id, user_id, kind, time.time(),
                 total_ms, calls, outcome, (reply_preview or "")[:80]))
            c.commit()
        finally:
            c.close()
    except Exception:
        logger.warning("telemetry record_turn failed", exc_info=True)


def calls_for_turn(turn_id):
    """All llm_calls rows for a turn, oldest first (dicts)."""
    try:
        c = _conn()
        try:
            _ensure_tables(c)
            rows = c.execute(
                """SELECT step, provider, model, total_ms, status,
                          http_status, finish_reason, tokens_in,
                          tokens_out, error_kind, outcome
                   FROM llm_calls WHERE turn_id=? ORDER BY id""",
                (turn_id,)).fetchall()
            return [dict(zip(
                ("step", "provider", "model", "total_ms", "status",
                 "http_status", "finish_reason", "tokens_in", "tokens_out",
                 "error_kind", "outcome"),
                r)) for r in rows]
        finally:
            c.close()
    except Exception:
        logger.warning("telemetry calls_for_turn failed", exc_info=True)
        return []


def recent_slow_turns(limit=10):
    """The last `limit` slow turns (wall clock >= SLOW_TURN_MS, or a
    timeout/error outcome), newest first (dicts)."""
    try:
        c = _conn()
        try:
            _ensure_tables(c)
            rows = c.execute(
                """SELECT turn_id, kind, total_ms, calls, outcome,
                          started_at FROM turns
                   WHERE total_ms >= ? OR outcome IN ('timeout', 'error')
                   ORDER BY started_at DESC LIMIT ?""",
                (SLOW_TURN_MS, limit)).fetchall()
            return [dict(zip(
                ("turn_id", "kind", "total_ms", "calls", "outcome",
                 "started_at"), r)) for r in rows]
        finally:
            c.close()
    except Exception:
        logger.warning("telemetry recent_slow_turns failed", exc_info=True)
        return []


def _percentile(sorted_values, pct):
    if not sorted_values:
        return None
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def provider_latency_stats():
    """Per-provider p50/p95 of total_ms over successful calls, plus
    the call count (dicts). Computed in Python from the stored rows."""
    try:
        c = _conn()
        try:
            _ensure_tables(c)
            rows = c.execute(
                "SELECT provider, total_ms FROM llm_calls "
                "WHERE status='ok' AND total_ms IS NOT NULL").fetchall()
        finally:
            c.close()
    except Exception:
        logger.warning("telemetry provider_latency_stats failed", exc_info=True)
        return []
    by_provider = {}
    for provider, total_ms in rows:
        by_provider.setdefault(provider or "?", []).append(float(total_ms))
    out = []
    for provider in sorted(by_provider):
        values = sorted(by_provider[provider])
        p50 = _percentile(values, 50)
        p95 = _percentile(values, 95)
        out.append({"provider": provider, "calls": len(values),
                    "p50_ms": None if p50 is None else round(p50),
                    "p95_ms": None if p95 is None else round(p95)})
    return out
