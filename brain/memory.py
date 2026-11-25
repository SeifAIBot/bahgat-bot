"""Per-member memory — SQLite. Sync calls are fast local I/O (ms); long
work (yt-dlp, ffmpeg) is run in asyncio.to_thread() by callers, never here.

Schema is created ONCE at startup via init_db() (module-level _SCHEMA_DONE
flag); _conn() only opens a connection + WAL pragma after that. Mood decay
is time-based on read: -10 per hour since updated_at, min 30 base, and the
decayed mood is PERSISTED back — this is the single decay mechanism
(brain/mood.py does no per-message decay).
"""
import logging
import re
import sqlite3
import time
from pathlib import Path

from core.config import data_dir

logger = logging.getLogger(__name__)

# Resolved once at import from BAHGAT_DATA_DIR (default <project root>/data).
# On a host with a persistent volume (e.g. Northflank /data) the env var
# must be set before the process starts — see docs/DEPLOY-NORTHFLANK.md.
DB_PATH = data_dir() / "bahgat.db"
_SCHEMA_DONE = False

try:  # core.rules owns the canonical stripper once another workstream adds it.
    from core.rules import strip_instruction_patterns as _core_strip
except ImportError:  # core/rules.py has no strip_instruction_patterns yet (v0.4).
    _core_strip = None

try:  # core.rules owns the canonical Arabic normaliser (v0.5+).
    from core.rules import normalize_arabic as _core_normalize
except ImportError:  # pragma: no cover - core/rules.py always has it now.
    _core_normalize = None

# --- v0.7 fair-share quota -----------------------------------------------
# The fixed per-user / per-group caps (v0.6: 100/user/day, 1500/group/day,
# owner exempt) are GONE. Capacity is computed live from provider budgets
# (compute_pool_remaining) and divided among the ACTIVE users by weighted
# max-min fair sharing (see docs/research-quota-fairshare.md). These are
# the module-level defaults, mirrored in config/providers.yaml under
# `quota:`; quota_cfg dicts passed to check_and_consume_quota /
# fair_share_info override them per call (missing keys fall back here),
# so this module works with no config passed at all.
QUOTA_OWNER_WEIGHT = 1.25        # owner share is 1.25x a member's share
QUOTA_MEMBER_WEIGHT = 1.0
QUOTA_ACTIVE_WINDOW_DAYS = 7     # rolling window for the active set
QUOTA_SATURATION_THRESHOLD = 0.50  # >=50% of pool used -> strict (share), else generous (ceiling)
QUOTA_BORROW_MULTIPLE = 2.0      # borrow ceiling = 2x fair share
QUOTA_FLOOR_REPLIES = 20         # a user under the floor is never blocked by the share check
QUOTA_PLANNING_HAIRCUT = 0.20    # plan on 80% of the raw pool (free tiers churn / 429)
# Tokens-per-reply measurement (docs/research-quota-capacity.md):
# EWMA lambda 0.15 per intent; cold-start blend with the configured 1,050
# estimate, prior weight 30 calls, until real measurements accumulate.
EWMA_LAMBDA = 0.15
COLD_START_TOKENS_PER_REPLY = 1050
COLD_START_PRIOR_CALLS = 30
TOKEN_STATS_MIN_AVG = 50         # avg_tokens_per_reply() never returns less
# Degrade-mode hysteresis (fraction of full pool remaining): enter cheap
# below 20%, exit only above 30% (dead band), dwell 15 min once entered.
DEGRADE_ENTER_FRACTION = 0.20
DEGRADE_EXIT_FRACTION = 0.30
DEGRADE_DWELL_SECONDS = 900
_QUOTA_DEFAULTS = {
    "owner_weight": QUOTA_OWNER_WEIGHT,
    "member_weight": QUOTA_MEMBER_WEIGHT,
    "active_window_days": QUOTA_ACTIVE_WINDOW_DAYS,
    "saturation_threshold": QUOTA_SATURATION_THRESHOLD,
    "borrow_multiple": QUOTA_BORROW_MULTIPLE,
    "floor_replies": QUOTA_FLOOR_REPLIES,
    "planning_haircut": QUOTA_PLANNING_HAIRCUT,
}
# v0.6b (2026-11-25, Seif's call): NO hourly burst cap — people talk freely.
# Anti-spam is pacing instead: one reply per user per 10s, queued never
# dropped (see tg/handlers.py USER_REPLY_PACE_SECONDS). The hourly_usage
# table is still written (per-hour counts for /stats) but never blocks.
CACHE_TTL_SECONDS = 3600     # exact-match response cache TTL (1 hour)
CACHE_MAX_ROWS = 500         # prune response_cache to the last 500 rows
CACHE_MAX_REPLY_CHARS = 1000  # cap on a stored cached reply

# Local fallback: instruction-injection phrases stripped from stored
# notes/grudge (and from prompt memory blocks) so a member cannot plant
# instructions that later get injected back into the system prompt.
_INSTRUCTION_PATTERNS = [
    r"تجاهل التعليمات", r"تجاهل ما سبق", r"انسى التعليمات",
    r"تجاهل كل التعليمات", r"برومبت النظام", r"تعليمات النظام",
    r"system prompt", r"ignore (all |previous |above )?instructions",
    r"disregard (all )?(previous )?instructions", r"you are now",
    r"تصرف كأنك",
]


def _strip_instruction_patterns(text: str) -> str:
    if _core_strip is not None:
        try:
            return _core_strip(text)
        except Exception:
            pass
    s = str(text or "")
    for pat in _INSTRUCTION_PATTERNS:
        s = re.sub(pat, "", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()


def init_db():
    """Create the schema once. Idempotent; safe to call at startup."""
    global _SCHEMA_DONE
    if _SCHEMA_DONE:
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    try:
        c.execute("PRAGMA journal_mode=WAL")
        schema = Path(__file__).resolve().parents[1] / "memory" / "schema.sql"
        c.executescript(schema.read_text(encoding="utf-8"))
        c.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_processed_updates_received ON processed_updates(received_at)")
        # v0.6 migration: existing DBs already ran the old schema, so create
        # the new tables here too (IF NOT EXISTS) — never re-run executescript
        # per call, and never assume a fresh DB.
        c.execute("""CREATE TABLE IF NOT EXISTS response_cache (
                       normalised_text TEXT, intent TEXT, mood_bucket TEXT,
                       reply TEXT, created_at REAL,
                       PRIMARY KEY(normalised_text, intent, mood_bucket))""")
        c.execute("""CREATE TABLE IF NOT EXISTS hourly_usage (
                       user_id INTEGER, chat_id INTEGER, hour TEXT,
                       count INTEGER DEFAULT 0,
                       PRIMARY KEY(user_id, chat_id, hour))""")
        # v0.7 fair-share quota tables (IF NOT EXISTS, so old DBs migrate):
        # last_triggered = the active set (who triggered the bot, when);
        # token_stats = EWMA tokens/reply per intent for capacity planning.
        c.execute("""CREATE TABLE IF NOT EXISTS last_triggered (
                       user_id INTEGER, chat_id INTEGER,
                       last_triggered_at REAL,
                       PRIMARY KEY(user_id, chat_id))""")
        c.execute("""CREATE TABLE IF NOT EXISTS token_stats (
                       intent TEXT PRIMARY KEY, ewma REAL,
                       n INTEGER, total REAL)""")
        c.commit()
        _SCHEMA_DONE = True
    finally:
        c.close()


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _SCHEMA_DONE:
        init_db()
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _today_utc() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def get_member(user_id):
    c = _conn()
    try:
        row = c.execute("SELECT user_id, username, first_name, notes, mood, grudge, updated_at FROM members WHERE user_id=?", (user_id,)).fetchone()
    finally:
        c.close()
    if not row:
        return {"user_id": user_id, "username": "", "first_name": "", "notes": "", "mood": 30, "grudge": "", "updated_at": time.time()}
    m = {"user_id": row[0], "username": row[1], "first_name": row[2], "notes": row[3], "mood": row[4], "grudge": row[5], "updated_at": row[6] or time.time()}
    # Time-based decay: -10 per hour since last update, never below 30.
    # Persisted back (single decay mechanism): a second read returns the
    # same decayed value instead of decaying again from the stale stored one.
    hours = max(0, (time.time() - m["updated_at"]) / 3600)
    if hours >= 1 and m["mood"] > 30:
        decayed = max(30, m["mood"] - int(hours * 10))
        if decayed != m["mood"]:
            m["mood"] = decayed
            save_member(m)
    return m


def save_member(m):
    notes = _strip_instruction_patterns(m.get("notes", ""))[:200]
    grudge = _strip_instruction_patterns(m.get("grudge", ""))[:500]
    c = _conn()
    try:
        c.execute("""INSERT INTO members(user_id,username,first_name,notes,mood,grudge,updated_at)
                     VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                     username=excluded.username, first_name=excluded.first_name,
                     notes=excluded.notes, mood=excluded.mood, grudge=excluded.grudge, updated_at=excluded.updated_at""",
                  (m["user_id"], m.get("username", ""), m.get("first_name", ""), notes, m.get("mood", 30), grudge, time.time()))
        c.commit()
    finally:
        c.close()


def add_message(chat_id, user_id, role, text):
    c = _conn()
    try:
        c.execute("INSERT INTO messages(chat_id,user_id,role,text,created_at) VALUES(?,?,?,?,?)",
                  (chat_id, user_id, role, text, time.time()))
        # Prune: keep last 200 messages per chat.
        c.execute("""DELETE FROM messages WHERE chat_id=? AND id NOT IN
                     (SELECT id FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT 200)""", (chat_id, chat_id))
        c.commit()
    finally:
        c.close()


def recent_messages(chat_id, limit=8):
    """Newest-first window, oldest-first return, WITH speaker info so the
    LLM can tell who said what (per-member memory collapses without it)."""
    c = _conn()
    try:
        rows = c.execute("""SELECT m.role, m.text, m.user_id, COALESCE(mem.first_name, '')
                            FROM messages m LEFT JOIN members mem ON mem.user_id = m.user_id
                            WHERE m.chat_id=? ORDER BY m.id DESC LIMIT ?""",
                         (chat_id, limit)).fetchall()
    finally:
        c.close()
    return [{"role": r, "content": t, "user_id": u, "first_name": fn}
            for r, t, u, fn in reversed(rows)]


def format_history(rows):
    """Convert recent_messages() rows to plain LLM messages. User turns are
    speaker-tagged ("[name]: text"); assistant turns stay plain."""
    out = []
    for row in rows:
        if row.get("role") == "assistant":
            out.append({"role": "assistant", "content": row.get("content", "")})
        else:
            name = row.get("first_name") or "عضو"
            out.append({"role": "user", "content": f"[{name}]: {row.get('content', '')}"})
    return out


# --- v0.6: exact-match response cache -------------------------------------
# Normalisation reuses core.rules.normalize_arabic (diacritics/tatweel
# stripped, أ/إ/آ -> ا, ة -> ه, ى -> ي, whitespace collapsed) plus
# lowercasing of Latin text. No third copy of the Arabic logic lives here.

def normalize_cache_text(text: str) -> str:
    """Cache key normalisation: canonical Arabic normaliser + lowercase."""
    if _core_normalize is not None:
        try:
            return _core_normalize(text or "").lower()
        except Exception:
            pass
    s = re.sub(r"[\u064b-\u0652\u0640]", "", str(text or ""))
    s = (s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
          .replace("ة", "ه").replace("ى", "ي"))
    return re.sub(r"\s+", " ", s).strip().lower()


def mood_bucket(mood: int) -> str:
    """Cache bucket so an angry roast never leaks into a calm turn."""
    return "angry" if (mood or 0) >= 70 else "calm"


def _bump_counter(c, key: str) -> int:
    """Increment a bot_state integer counter on the given connection."""
    row = c.execute("SELECT value FROM bot_state WHERE key=?", (key,)).fetchone()
    try:
        n = int(row[0]) if row else 0
    except (TypeError, ValueError):
        n = 0
    c.execute("""INSERT INTO bot_state(key, value) VALUES(?,?)
                 ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
              (key, str(n + 1)))
    return n + 1


def get_cached_reply(normalised_text, intent, mood_bucket):
    """Exact-match cache lookup. Returns the reply or None on miss/expiry;
    expired rows are deleted on read. Every lookup bumps the persisted
    cache_hits / cache_misses counters (see get_cache_stats)."""
    key = normalize_cache_text(normalised_text)
    c = _conn()
    try:
        row = c.execute(
            "SELECT reply, created_at FROM response_cache "
            "WHERE normalised_text=? AND intent=? AND mood_bucket=?",
            (key, intent, mood_bucket)).fetchone()
        if row is None:
            _bump_counter(c, "cache_misses")
            c.commit()
            return None
        reply, created_at = row
        if not created_at or time.time() - created_at > CACHE_TTL_SECONDS:
            c.execute(
                "DELETE FROM response_cache "
                "WHERE normalised_text=? AND intent=? AND mood_bucket=?",
                (key, intent, mood_bucket))
            _bump_counter(c, "cache_misses")
            c.commit()
            return None
        _bump_counter(c, "cache_hits")
        c.commit()
        return reply
    finally:
        c.close()


def store_cached_reply(normalised_text, intent, mood_bucket, reply):
    """Store a reply (skips empty replies, caps at 1000 chars, prunes the
    table to the last 500 rows). Callers (handlers) enforce the exclusion
    rules — search/youtube/voice intents, insulted turns, grudges, and
    replies containing citations are never passed here."""
    if not (reply or "").strip():
        return
    key = normalize_cache_text(normalised_text)
    if not key:
        return
    c = _conn()
    try:
        c.execute("""INSERT INTO response_cache(normalised_text, intent, mood_bucket, reply, created_at)
                     VALUES(?,?,?,?,?)
                     ON CONFLICT(normalised_text, intent, mood_bucket) DO UPDATE SET
                     reply=excluded.reply, created_at=excluded.created_at""",
                  (key, intent, mood_bucket, reply[:CACHE_MAX_REPLY_CHARS], time.time()))
        c.execute("""DELETE FROM response_cache WHERE rowid NOT IN
                     (SELECT rowid FROM response_cache
                      ORDER BY created_at DESC, rowid DESC LIMIT ?)""",
                  (CACHE_MAX_ROWS,))
        c.commit()
    finally:
        c.close()


def get_cache_stats():
    """{"hits": n, "misses": n, "hit_rate": float} — counters live in
    bot_state, so they survive restarts."""
    c = _conn()
    try:
        def _n(k):
            row = c.execute("SELECT value FROM bot_state WHERE key=?", (k,)).fetchone()
            try:
                return int(row[0]) if row else 0
            except (TypeError, ValueError):
                return 0
        hits = _n("cache_hits")
        misses = _n("cache_misses")
        total = hits + misses
        return {"hits": hits, "misses": misses,
                "hit_rate": (hits / total if total else 0.0)}
    finally:
        c.close()


# --- v0.6: unknown-retry counters -------------------------------------------
# Handlers bump these when the unknown-retry second LLM call runs:
# unknown_retries = second calls attempted, unknown_retries_rescued =
# second calls that returned a non-unknown reply. /stats reads them via
# get_unknown_stats() (unknown_retry_rate = rescued / retries).

def record_unknown_retry(rescued: bool):
    c = _conn()
    try:
        _bump_counter(c, "unknown_retries")
        if rescued:
            _bump_counter(c, "unknown_retries_rescued")
        c.commit()
    finally:
        c.close()


def get_unknown_stats():
    c = _conn()
    try:
        def _n(k):
            row = c.execute("SELECT value FROM bot_state WHERE key=?", (k,)).fetchone()
            try:
                return int(row[0]) if row else 0
            except (TypeError, ValueError):
                return 0
        retries = _n("unknown_retries")
        rescued = _n("unknown_retries_rescued")
        return {"unknown_retries": retries, "unknown_retries_rescued": rescued,
                "unknown_retry_rate": (rescued / retries if retries else 0.0)}
    finally:
        c.close()


# --- v0.7: fair-share quota (dynamic capacity, active users) ------------
# Replaces the v0.6 fixed caps (100/user/day, 1500/group/day, owner
# exempt). Scheme (docs/research-quota-fairshare.md,
# docs/research-quota-capacity.md): capacity C is computed live from
# provider budgets by the router workstream and passed in as
# capacity_replies; it is divided among the ACTIVE users (triggered the
# bot within the rolling window) by weight — owner 1.25, member 1.0.
# share = C * w / sum(w); ceiling = borrow_multiple * share. Below the
# saturation threshold the ceiling applies (generous: borrow idle
# capacity); at/above it the share applies (strict). A user under the
# floor is never blocked by the share check; the group pool itself is a
# hard ceiling. Already-consumed replies are never clawed back — every
# check is forward-looking only. THE OWNER IS NO LONGER EXEMPT: he gets
# the 1.25 weight instead (exempting him would break sum-to-C and let
# one user drain the pool).
#
# Reasons: "group daily limit reached" / "fair share reached" / "ok".
# The old "user daily limit reached" reason is retired with the fixed cap.
# daily_usage / hourly_usage are still written on every allowed reply
# (per-user/per-group counts for /stats); denied replies never consume.

def _merged_quota_cfg(quota_cfg=None):
    """Module defaults overridden by quota_cfg (missing keys fall back)."""
    cfg = dict(_QUOTA_DEFAULTS)
    if quota_cfg:
        for key, value in quota_cfg.items():
            if key in cfg and value is not None:
                cfg[key] = value
    return cfg


def _is_owner(user_id, owner_id):
    try:
        return owner_id is not None and int(user_id) == int(owner_id)
    except (TypeError, ValueError):
        return False


# --- Active set ------------------------------------------------------------

def record_trigger(user_id, chat_id):
    """Mark (user, chat) as having triggered the bot now (upsert). The
    qualifying action is triggering the bot (mention / "بهجت" / reply to
    the bot) — not sending any group message — so lurkers never dilute
    the denominator. Called by check_and_consume_quota on every turn;
    the handler workstream may also call it directly."""
    c = _conn()
    try:
        c.execute("""INSERT INTO last_triggered(user_id, chat_id, last_triggered_at)
                     VALUES(?,?,?)
                     ON CONFLICT(user_id, chat_id) DO UPDATE SET
                     last_triggered_at=excluded.last_triggered_at""",
                  (int(user_id), int(chat_id), time.time()))
        c.commit()
    finally:
        c.close()


def _query_active_users(chat_id, window_days):
    try:
        window = float(window_days)
    except (TypeError, ValueError):
        window = float(QUOTA_ACTIVE_WINDOW_DAYS)
    cutoff = time.time() - max(0.0, window) * 86400
    c = _conn()
    try:
        rows = c.execute(
            "SELECT user_id FROM last_triggered "
            "WHERE chat_id=? AND last_triggered_at >= ? "
            "ORDER BY last_triggered_at DESC",
            (chat_id, cutoff)).fetchall()
    finally:
        c.close()
    return [int(r[0]) for r in rows]


def active_users(chat_id, window_days=7):
    """User ids that triggered the bot in this chat within the rolling
    window (default 7 days; today is inside the window). Most recent
    first. A returning user is active the moment they trigger the bot
    again — record_trigger() upserts now, no re-activation step."""
    return _query_active_users(chat_id, window_days)


def _resolve_active_users(chat_id, active_param, user_id, window_days):
    """Active set for a quota decision: the caller's list when given,
    else queried from the DB. The triggering user is always in it
    (instantly active on first trigger); an empty set is treated as
    [user_id] — minimum 1, never divide by zero."""
    if active_param is None:
        users = _query_active_users(chat_id, window_days)
    else:
        users = [int(u) for u in active_param]
    if int(user_id) not in users:
        users.append(int(user_id))
    return users


# --- Tokens-per-reply measurement (EWMA + cold-start blend) ----------------
# Callers: the ROUTER workstream calls record_reply_tokens() exactly once
# per SUCCESSFUL reply, with usage.prompt_tokens + usage.completion_tokens
# (reasoning tokens included). Cache hits and failed calls must NEVER call
# this — a cache hit costs 0 tokens and a failed call produced no reply.

def _token_bucket(intent):
    return "search" if intent == "search" else "chat"


def record_reply_tokens(intent, total_tokens):
    """Update the EWMA for an intent bucket ("chat" or "search"; anything
    else is bucketed as "chat"). EWMA lambda 0.15: ewma = 0.15*x + 0.85*ewma
    (first call ewma=x); n+=1; total+=x. Non-positive / non-numeric
    totals are ignored so a bad reading cannot corrupt the average."""
    bucket = _token_bucket(intent)
    try:
        x = float(total_tokens)
    except (TypeError, ValueError):
        return
    if x <= 0:
        return
    c = _conn()
    try:
        row = c.execute(
            "SELECT ewma, n, total FROM token_stats WHERE intent=?",
            (bucket,)).fetchone()
        if row is None:
            ewma, n, total = x, 1, x
        else:
            ewma = EWMA_LAMBDA * x + (1.0 - EWMA_LAMBDA) * float(row[0])
            n = int(row[1] or 0) + 1
            total = float(row[2] or 0.0) + x
        c.execute("""INSERT INTO token_stats(intent, ewma, n, total)
                     VALUES(?,?,?,?)
                     ON CONFLICT(intent) DO UPDATE SET
                     ewma=excluded.ewma, n=excluded.n, total=excluded.total""",
                  (bucket, ewma, n, total))
        c.commit()
    finally:
        c.close()


def avg_tokens_per_reply(intent=None):
    """Blended tokens/reply estimate. Per-intent when `intent` is given
    and that intent has measurements; otherwise blended across intents.
    Cold-start blend with the configured 1,050 estimate:
    avg = (30*1050 + total) / (30 + n), using the stored sum (per intent
    when intent given, else summed across intents). Never returns <= 0;
    clamped to >= 50."""
    bucket = intent if intent in ("chat", "search") else None
    c = _conn()
    try:
        if bucket is not None:
            row = c.execute(
                "SELECT n, total FROM token_stats WHERE intent=?",
                (bucket,)).fetchone()
            if row and int(row[0] or 0) > 0:
                n = int(row[0])
                total = float(row[1] or 0.0)
                return max(float(TOKEN_STATS_MIN_AVG),
                           (COLD_START_PRIOR_CALLS * COLD_START_TOKENS_PER_REPLY + total)
                           / (COLD_START_PRIOR_CALLS + n))
        rows = c.execute("SELECT n, total FROM token_stats").fetchall()
    finally:
        c.close()
    n = sum(int(r[0] or 0) for r in rows)
    total = sum(float(r[1] or 0.0) for r in rows)
    return max(float(TOKEN_STATS_MIN_AVG),
               (COLD_START_PRIOR_CALLS * COLD_START_TOKENS_PER_REPLY + total)
               / (COLD_START_PRIOR_CALLS + n))


# --- Live capacity from provider entries -----------------------------------
# Gemini timezone trap (see docs/research-quota-capacity.md): Gemini RPD
# resets at midnight Pacific (08:00 UTC), NOT midnight UTC like Groq /
# OpenRouter. The router workstream keys Gemini usage rows by Pacific
# date; memory.py itself stays date-agnostic — it consumes the entries
# snapshot it is handed and never interprets a date.
#
# NO fixed reply numbers live in this path: with no entries the pool is
# 0.0 (fail-closed at the capacity level; the handler workstream treats
# C <= 0 as pool-exhausted). The router workstream always passes real
# entries in production.

def _entry_budget(entry, avg, zero_usage=False):
    """(replies, requests_left, tokens_left) for one entry at the given
    avg tokens/reply. replies = min(RPD_left, TPD_left / avg); a cap
    that is None means unbounded on that axis. An entry with NEITHER cap
    contributes 0 replies (fail-closed for planning). Left values are
    clamped at 0; None means that cap does not exist."""
    cap_req = entry.get("daily_cap_requests")
    cap_tok = entry.get("daily_cap_tokens")
    used_req = 0 if zero_usage else int(entry.get("requests_used") or 0)
    used_tok = 0 if zero_usage else int(entry.get("tokens_used") or 0)
    req_left = None if cap_req is None else max(0, int(cap_req) - used_req)
    tok_left = None if cap_tok is None else max(0, int(cap_tok) - used_tok)
    req_replies = float("inf") if req_left is None else float(req_left)
    tok_replies = float("inf") if tok_left is None else tok_left / avg
    replies = min(req_replies, tok_replies)
    if replies == float("inf"):
        replies = 0.0
    return max(0.0, replies), req_left, tok_left


def _entry_disabled(entry, zero_usage=False):
    """True when the entry is disabled, or exhausted_until is in the
    future. In the full-pool computation (zero_usage) exhaustion is
    ignored — the full pool is the healthy-day baseline."""
    if entry.get("disabled"):
        return True
    if zero_usage:
        return False
    exhausted_until = entry.get("exhausted_until")
    if exhausted_until is not None:
        try:
            if float(exhausted_until) > time.time():
                return True
        except (TypeError, ValueError):
            pass
    return False


def _openrouter_family_replies(entries, avg, zero_usage=False):
    """Shared OpenRouter replies: ONE account-wide RPD cap across all
    OpenRouter entries, so the binding cap is the smallest
    daily_cap_requests among them, charged against summed requests_used.
    Token caps (if any entry has one) still bind per entry. Returns
    (family_replies, shared_requests_left) — (0.0, None) with no entries
    or no request cap at all (then the token side alone binds)."""
    or_entries = [e for e in entries
                  if str(e.get("family") or "").lower() == "openrouter"]
    if not or_entries:
        return 0.0, None
    caps = [int(e["daily_cap_requests"]) for e in or_entries
            if e.get("daily_cap_requests") is not None]
    used = 0 if zero_usage else sum(int(e.get("requests_used") or 0)
                                    for e in or_entries)
    shared_left = None if not caps else max(0, min(caps) - used)
    req_replies = float("inf") if shared_left is None else float(shared_left)
    tok_replies = float("inf")
    for e in or_entries:
        _r, _rl, tok_left = _entry_budget(e, avg, zero_usage=zero_usage)
        if tok_left is not None:
            tok_replies = min(tok_replies, tok_left / avg)
    replies = min(req_replies, tok_replies)
    if replies == float("inf"):
        replies = 0.0
    return max(0.0, replies), shared_left


def compute_pool_remaining(entries, avg_tokens=None):
    """Live planning pool from provider entries (pure function except the
    avg default, which reads the EWMA table). Each entry is a dict with
    keys name, family, model, daily_cap_requests (int|None),
    daily_cap_tokens (int|None), requests_used (int), tokens_used (int),
    disabled (bool), exhausted_until (float|None epoch; in the future
    counts as disabled). Per entry: replies = min(RPD_left,
    TPD_left / avg); pool = sum(replies) * (1 - planning_haircut).
    Rules: family "nvidia" (NVIDIA NIM) is EXCLUDED from the planning
    pool entirely (trial terms: testing/evaluation only) — contributes 0
    and is marked excluded. Disabled/exhausted entries contribute 0.
    OpenRouter entries share ONE account-wide 50 RPD cap: the family is
    counted once, against the smallest daily_cap_requests among them.
    full_pool_replies is the same formula with all used=0 and nothing
    disabled (x0.8 too) — the denominator for the degrade-mode fraction.
    Returns {"pool_replies", "full_pool_replies", "avg_tokens",
    "per_entry": [{name, family, replies_remaining, requests_left,
    tokens_left, excluded, disabled}]}. Empty/None entries -> pool 0.0
    and full 0.0 (fail-closed; no fixed fallback number exists here)."""
    if avg_tokens is None:
        avg = avg_tokens_per_reply()
    else:
        try:
            avg = float(avg_tokens)
        except (TypeError, ValueError):
            avg = avg_tokens_per_reply()
        if avg <= 0:
            avg = avg_tokens_per_reply()
    avg = max(float(TOKEN_STATS_MIN_AVG), avg)
    if not entries:
        return {"pool_replies": 0.0, "full_pool_replies": 0.0,
                "avg_tokens": avg, "per_entry": []}
    entries = list(entries)
    or_live, or_live_left = _openrouter_family_replies(entries, avg)
    or_full, or_full_left = _openrouter_family_replies(
        entries, avg, zero_usage=True)
    per_entry = []
    pool = 0.0
    full = 0.0
    or_counted_live = False
    or_counted_full = False
    for entry in entries:
        family = str(entry.get("family") or "")
        name = entry.get("name")
        excluded = family.lower() == "nvidia"
        disabled = _entry_disabled(entry)
        live_replies, req_left, tok_left = _entry_budget(entry, avg)
        # Full pool: all used=0 AND no disabled (healthy-day baseline),
        # so the disabled flag is deliberately ignored here.
        full_replies, _full_req_left, _full_tok_left = _entry_budget(
            entry, avg, zero_usage=True)
        if family.lower() == "openrouter":
            live_replies, req_left = or_live, or_live_left
            full_replies, _full_req_left = or_full, or_full_left
        if excluded:
            live_replies = 0.0
            full_replies = 0.0
        elif disabled:
            live_replies = 0.0
        per_entry.append({
            "name": name, "family": family,
            "replies_remaining": float(live_replies),
            "requests_left": req_left, "tokens_left": tok_left,
            "excluded": bool(excluded), "disabled": bool(disabled),
        })
        if excluded:
            continue
        # Live pool: disabled entries contribute 0. Full pool: every
        # entry counts (healthy-day baseline, disabled ignored).
        if not disabled:
            if family.lower() == "openrouter":
                if not or_counted_live:
                    pool += live_replies
                    or_counted_live = True
            else:
                pool += live_replies
        if family.lower() == "openrouter":
            if not or_counted_full:
                full += full_replies
                or_counted_full = True
        else:
            full += full_replies
    haircut = 1.0 - float(QUOTA_PLANNING_HAIRCUT)
    return {"pool_replies": max(0.0, pool * haircut),
            "full_pool_replies": max(0.0, full * haircut),
            "avg_tokens": avg, "per_entry": per_entry}


# --- Fair-share decision ---------------------------------------------------

def _prune_usage_tables(c):
    c.execute("DELETE FROM daily_usage WHERE date < date('now','-2 days')")
    cutoff = time.strftime("%Y-%m-%dT%H", time.gmtime(time.time() - 2 * 86400))
    c.execute("DELETE FROM hourly_usage WHERE hour < ?", (cutoff,))


def _consume_quota_count(c, user_id, chat_id):
    """Write one consumed reply to daily_usage + hourly_usage (for
    /stats). The caller owns the connection + commit."""
    today = _today_utc()
    hour = time.strftime("%Y-%m-%dT%H", time.gmtime())
    c.execute("""INSERT INTO daily_usage(user_id, chat_id, date, count) VALUES(?,?,?,1)
                 ON CONFLICT(user_id, chat_id, date) DO UPDATE SET count=count+1""",
              (user_id, chat_id, today))
    c.execute("""INSERT INTO hourly_usage(user_id, chat_id, hour, count) VALUES(?,?,?,1)
                 ON CONFLICT(user_id, chat_id, hour) DO UPDATE SET count=count+1""",
              (user_id, chat_id, hour))


def _consume_once(user_id, chat_id):
    c = _conn()
    try:
        _prune_usage_tables(c)
        _consume_quota_count(c, user_id, chat_id)
        c.commit()
    finally:
        c.close()


def fair_share_info(user_id, chat_id, owner_id=None, capacity_replies=None,
                    active_users=None, quota_cfg=None):
    """Fair-share numbers for (user, chat) WITHOUT consuming anything
    (for /stats; the handler workstream uses it). Returns {share,
    ceiling, limit, used_user, used_group, capacity, active_count,
    saturated, mode_limit}: share/ceiling/limit are float reply counts
    (limit is the binding one — share in strict mode, ceiling in
    generous mode; mode_limit is "share" or "ceiling"). With
    capacity_replies None the capacity is unknown: capacity/share/
    ceiling/limit are None and mode_limit is "unknown" (counts and
    active_count are still real)."""
    cfg = _merged_quota_cfg(quota_cfg)
    users = _resolve_active_users(chat_id, active_users, user_id,
                                  cfg["active_window_days"])
    w_user = (cfg["owner_weight"] if _is_owner(user_id, owner_id)
              else cfg["member_weight"])
    total_w = sum(cfg["owner_weight"] if _is_owner(u, owner_id)
                  else cfg["member_weight"] for u in users) or 1.0
    c = _conn()
    try:
        today = _today_utc()
        used_user = c.execute(
            "SELECT COALESCE(SUM(count),0) FROM daily_usage "
            "WHERE user_id=? AND chat_id=? AND date=?",
            (user_id, chat_id, today)).fetchone()[0]
        used_group = c.execute(
            "SELECT COALESCE(SUM(count),0) FROM daily_usage "
            "WHERE chat_id=? AND date=?",
            (chat_id, today)).fetchone()[0]
    finally:
        c.close()
    if capacity_replies is None:
        return {"share": None, "ceiling": None, "limit": None,
                "used_user": int(used_user), "used_group": int(used_group),
                "capacity": None, "active_count": len(users),
                "saturated": False, "mode_limit": "unknown"}
    capacity = max(0.0, float(capacity_replies))
    share = capacity * w_user / total_w
    ceiling = float(cfg["borrow_multiple"]) * share
    saturated = used_group >= float(cfg["saturation_threshold"]) * capacity
    limit = share if saturated else ceiling
    return {"share": share, "ceiling": ceiling, "limit": limit,
            "used_user": int(used_user), "used_group": int(used_group),
            "capacity": capacity, "active_count": len(users),
            "saturated": bool(saturated),
            "mode_limit": "share" if saturated else "ceiling"}


def check_and_consume_quota(user_id, chat_id, owner_id=None,
                            capacity_replies=None, active_users=None,
                            quota_cfg=None):
    """(allowed, reason). Weighted max-min fair share over the live
    capacity (see module header). Check order: group hard ceiling
    first (used_group >= C -> "group daily limit reached"), then the
    floor (used_user < floor_replies -> allow), then the binding limit
    (share when saturated, else borrow ceiling -> "fair share reached").
    Increments only when allowed. If capacity_replies is None the
    caller (handler workstream) has not supplied a capacity: fail OPEN
    with a logged warning "capacity unknown, quota unenforced" (a chat
    bot must not go silent over a missing number) — the reply is still
    counted for /stats. Prunes daily_usage and hourly_usage rows older
    than 2 days on every call. hour key = UTC "%Y-%m-%dT%H"."""
    cfg = _merged_quota_cfg(quota_cfg)
    record_trigger(user_id, chat_id)
    if capacity_replies is None:
        logger.warning("capacity unknown, quota unenforced "
                       "(user_id=%s chat_id=%s)", user_id, chat_id)
        _consume_once(user_id, chat_id)
        return True, "ok"
    info = fair_share_info(user_id, chat_id, owner_id=owner_id,
                           capacity_replies=capacity_replies,
                           active_users=active_users, quota_cfg=cfg)
    if info["used_group"] >= info["capacity"]:
        return False, "group daily limit reached"
    if info["used_user"] < cfg["floor_replies"]:
        _consume_once(user_id, chat_id)
        return True, "ok"
    if info["used_user"] >= info["limit"]:
        return False, "fair share reached"
    _consume_once(user_id, chat_id)
    return True, "ok"


def get_usage_today():
    """{"per_user": {user_id: count}, "group_total": int, "by_chat": {...}}.
    The v0.6 group_limit/user_limit keys are gone with the fixed caps —
    capacity is live now (see compute_pool_remaining)."""
    c = _conn()
    try:
        today = _today_utc()
        per_user = {int(u): int(n) for u, n in c.execute(
            "SELECT user_id, SUM(count) FROM daily_usage WHERE date=? GROUP BY user_id",
            (today,)).fetchall()}
        by_chat = {int(ch): int(n) for ch, n in c.execute(
            "SELECT chat_id, SUM(count) FROM daily_usage WHERE date=? GROUP BY chat_id",
            (today,)).fetchall()}
        return {"per_user": per_user, "group_total": sum(by_chat.values()),
                "by_chat": by_chat}
    finally:
        c.close()


# --- Degrade mode (hysteresis over the pool fraction) ----------------------
# Mode decisions use fraction = pool_remaining / full_pool. Enter "cheap"
# when fraction < 0.20, exit only when fraction > 0.30 (dead band
# 0.20–0.30 holds the current mode), and once a mode is entered stay at
# least 900s (dwell) regardless of the recomputed fraction. Quota
# numbers still update every call — this only decides the mode. Mode +
# mode_since persist in bot_state ("degrade_mode" /
# "degrade_mode_since") so a restart keeps the mode (and its dwell).

def get_degrade_mode():
    """(mode, since, held_by_dwell): mode "normal"|"cheap" (default
    "normal"), since = epoch the current mode was entered (0.0 if never
    set), held_by_dwell = True while inside the 900s dwell window."""
    raw_mode = get_state("degrade_mode")
    mode = raw_mode if raw_mode in ("normal", "cheap") else "normal"
    try:
        since = float(get_state("degrade_mode_since") or 0)
    except (TypeError, ValueError):
        since = 0.0
    held = since > 0 and (time.time() - since) < DEGRADE_DWELL_SECONDS
    return mode, since, held


def update_degrade_mode(pool_fraction):
    """Decide the degrade mode from the pool fraction; returns the
    (possibly unchanged) mode "normal"|"cheap"."""
    if pool_fraction is None:
        return get_degrade_mode()[0]
    try:
        fraction = float(pool_fraction)
    except (TypeError, ValueError):
        return get_degrade_mode()[0]
    mode, _since, held = get_degrade_mode()
    if held:
        return mode
    now = time.time()
    if mode == "normal" and fraction < DEGRADE_ENTER_FRACTION:
        set_state("degrade_mode", "cheap")
        set_state("degrade_mode_since", str(now))
        return "cheap"
    if mode == "cheap" and fraction > DEGRADE_EXIT_FRACTION:
        set_state("degrade_mode", "normal")
        set_state("degrade_mode_since", str(now))
        return "normal"
    return mode


# --- Housekeeping / kv state / YouTube file-id cache -----------------------

def prune_processed_updates(hours=48):
    """Delete processed_updates rows older than `hours`. Returns rows deleted."""
    c = _conn()
    try:
        cur = c.execute("DELETE FROM processed_updates WHERE received_at < ?",
                        (time.time() - hours * 3600,))
        c.commit()
        return cur.rowcount
    finally:
        c.close()


def get_state(key):
    c = _conn()
    try:
        row = c.execute("SELECT value FROM bot_state WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        c.close()


def set_state(key, value):
    c = _conn()
    try:
        c.execute("""INSERT INTO bot_state(key, value) VALUES(?,?)
                     ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                  (key, str(value)))
        c.commit()
    finally:
        c.close()


def get_cached_file(video_id_or_url, audio_only):
    """Telegram file_id for a previously uploaded YouTube result, or None."""
    c = _conn()
    try:
        row = c.execute("SELECT file_id FROM youtube_files WHERE url=? AND audio_only=?",
                        (video_id_or_url, 1 if audio_only else 0)).fetchone()
        return row[0] if row else None
    finally:
        c.close()


def cache_file(video_id_or_url, audio_only, file_id, size_bytes):
    c = _conn()
    try:
        c.execute("""INSERT INTO youtube_files(url, audio_only, file_id, size_bytes, created_at)
                     VALUES(?,?,?,?,?) ON CONFLICT(url, audio_only) DO UPDATE SET
                     file_id=excluded.file_id, size_bytes=excluded.size_bytes,
                     created_at=excluded.created_at""",
                  (video_id_or_url, 1 if audio_only else 0, file_id, size_bytes, time.time()))
        c.commit()
    finally:
        c.close()
