"""Bahgat reply bank — v1.1 retrieval fast-path.

Bahgat's REAL lines (persona/bahgat/reply_bank.yaml, built from his own
transcripts — never invented) served verbatim for the highest-frequency
persona moments: insult comebacks, jokes, his Sisi/takfir stance,
challenges, greetings. Checked BEFORE the LLM (like detect_fast_reply):
instant, zero quota, zero tokens — and the only method that guarantees
a real lazma lands verbatim (see docs/research-persona-methods.md §1,
method #1, ranked highest impact).

Rules, enforced here in code (never left to the prompt):
- Only verbatim/cleaned lines are served. "approximate" lines (uncertain
  speaker attribution in the transcripts) are loaded but never served.
- op-05 ("مش عارف، أنا مش عارف صراحة") is never served: its own bank
  note says prefer searching over the hedge.
- The owner is NEVER served an insult/challenge/dismiss line — the
  agreed rule (owner never insulted) is enforced by the is_owner gate,
  not by the model remembering it.
- Insult comebacks fire only when the insult targets the bot: the
  message mentions "بهجت" or is a reply to the bot's message. A member
  insulting another member is not the bot being insulted.
- Opinion lines are topic-gated: they are Bahgat's Sisi/takfir stance,
  so they only fire when the question is ABOUT السيسي / التكفير /
  الكفر / الإخوان. Serving "السيسي كافر" as the answer to a golden-
  billion question would be off-topic nonsense.
- Rotation: random pick per trigger category, excluding the last 5
  lines served from that category in that chat (in-memory only), so
  the same comeback does not repeat every time.
- The matcher never raises: a missing/unparsable bank file just means
  no bank reply (the LLM path handles the turn).
"""
import os
import random
import re

from brain.intent import looks_like_insult, looks_like_opinion_ask, normalize_arabic

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is installed; defensive only.
    yaml = None

_BANK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "persona", "bahgat", "reply_bank.yaml"
)
# Lines never served even though they are in the file: the hedge (its own
# note says prefer searching) and anything with uncertain attribution.
_BLOCKED_IDS = {"op-05"}
_BLOCKED_CONFIDENCE = {"approximate"}

# Trigger words (normalised form; matching normalises both sides, same
# rule as brain.intent._has). "نكته" covers "نكتة" (ة -> ه).
_GREETING_WORDS = [
    "اهلا", "السلام عليكم", "وعليكم السلام", "صباح الخير",
    "مساء الخير", "هاي", "مرحبا",
]
_JOKE_WORDS = ["نكته", "اضحكني"]
# Word-boundary matching, so both the bare form and the ال- form are
# needed ("التكفير" does not match the word "تكفير").
_OPINION_TOPICS = ["السيسي", "تكفير", "التكفير", "كافر", "الكافر", "الاخوان"]
_CHALLENGE_WORDS = [
    "انت غلط", "كلامك غلط", "مش صحيح", "بتخرف", "انت مش فاهم",
]

_bank_cache = None
_last_used: dict[tuple[int, str], list[str]] = {}


def _has(text: str, words) -> bool:
    """Word-boundary match on normalised text (mirrors brain.intent._has)."""
    return any(
        re.search(rf"(?<!\w){re.escape(normalize_arabic(w))}(?!\w)", text)
        for w in words
    )


def load_bank(path: str | None = None) -> dict[str, list[dict]]:
    """Parse the bank YAML into {category: [entries]}. Cached after the
    first load; reload_bank() clears the cache (tests). Entries that
    must never be served are dropped here, not at match time."""
    global _bank_cache
    if _bank_cache is not None and path is None:
        return _bank_cache
    bank: dict[str, list[dict]] = {}
    if yaml is None:
        return bank
    try:
        with open(path or _BANK_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return bank
    for entry in data.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("id") in _BLOCKED_IDS:
            continue
        if entry.get("confidence") in _BLOCKED_CONFIDENCE:
            continue
        line = (entry.get("line") or "").strip()
        trigger = (entry.get("trigger") or "").strip()
        if not line or not trigger:
            continue
        bank.setdefault(trigger, []).append(entry)
    if path is None:
        _bank_cache = bank
    return bank


def reload_bank() -> None:
    """Clear the load cache (tests)."""
    global _bank_cache
    _bank_cache = None
    _last_used.clear()


def _pick(category: str, chat_id: int) -> str | None:
    """Random line from a category, excluding the last 5 served from it
    in this chat (rotation so the same comeback does not repeat)."""
    entries = load_bank().get(category) or []
    if not entries:
        return None
    key = (chat_id, category)
    recent = _last_used.get(key, [])
    available = [e for e in entries if e["id"] not in recent]
    if not available:
        available = list(entries)
        recent = []
    entry = random.choice(available)
    recent = (recent + [entry["id"]])[-5:]
    _last_used[key] = recent
    return entry["line"]


def match_reply_bank(
    text: str,
    *,
    chat_id: int,
    is_owner: bool = False,
    is_reply_to_bot: bool = False,
) -> str | None:
    """Return a verbatim Bahgat line for this message, or None.

    Priority: insulted > joke > opinion > challenge > greeting — a
    message carrying two signals ("اهلا يا بهجت انت حمار") must get
    the comeback, not the greeting."""
    t = normalize_arabic(text or "")
    words = t.split()
    targeted = "بهجت" in words or is_reply_to_bot

    # Insulted: the bot is the target, and never the owner.
    if not is_owner and targeted and looks_like_insult(text):
        line = _pick("insulted", chat_id)
        if line is not None:
            return line

    # Joke request ("قول نكته" / "قولي نكته" / "هات نكته").
    if _has(t, _JOKE_WORDS):
        line = _pick("joke_request", chat_id)
        if line is not None:
            return line

    # Opinion: only Bahgat's own Sisi/takfir stance, only on that topic.
    if looks_like_opinion_ask(text) and _has(t, _OPINION_TOPICS):
        line = _pick("opinion_asked", chat_id)
        if line is not None:
            return line

    # Challenge / argument: dismiss or answer back. Never at the owner.
    if not is_owner and _has(t, _CHALLENGE_WORDS):
        line = _pick("challenge", chat_id) or _pick("dismiss", chat_id)
        if line is not None:
            return line

    # Greeting: short message only, so "اهلا يا بهجت انت حمار" (long,
    # insult) never lands here — the insult branch above already won.
    if len(words) <= 3 and _has(t, _GREETING_WORDS):
        line = _pick("greeting", chat_id)
        if line is not None:
            return line

    return None
