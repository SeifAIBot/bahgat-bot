"""Bahgat reply bank — v1.2 retrieval fast-path (224 entries).

Bahgat's REAL lines (persona/bahgat/reply_bank.yaml, built from his own
transcripts — never invented) served verbatim for the highest-frequency
persona moments: insult comebacks, roasts on request, jokes, his
Sisi/takfir stance, challenges, condolences, greetings. Checked BEFORE
the LLM (like detect_fast_reply): instant, zero quota, zero tokens —
and the only method that guarantees a real lazma lands verbatim (see
docs/research-persona-methods.md §1, method #1, ranked highest impact).

Rules, enforced here in code (never left to the prompt):
- Only verbatim/cleaned/user lines are served. "approximate" lines
  (uncertain speaker attribution in the transcripts) are loaded but
  never served. "user" lines are owner-authored (Seif wrote them on
  the insults page — source: user-submitted), NOT Bahgat transcript
  lines, and are served exactly like verbatim/cleaned.
- op-05 / op-30 ("مش عارف" hedges) are never served: their own bank
  notes say prefer searching over the hedge.
- MEMBER SAFETY (v1.2, Seif 2026-11-26): bank lines carrying a
  father/mother/family insult are tagged `member_safe: false` in the YAML
  and are served ONLY when the insult target is a RESOLVED non-member.
  Member-directed insults stay person-only. Enforcement:
  - insulted comebacks: the target is always the sender (a member) —
    member-safe lines only, always.
  - roast ("اشتم X"): family-insult lines only when target_is_member
    is False (resolved non-member). Unresolved (None) fails safe to
    member-safe lines. Never at the owner (target_is_owner).
  - opinion lines are ABOUT السيسي/التكفير (non-member subjects), so
    their pool is not member-restricted — the line's target is never a
    group member. Every other category picks member-safe only.
- The owner is NEVER served an insult/challenge/dismiss/roast line — the
  agreed rule (owner never insulted) is enforced by the is_owner /
  target_is_owner gates, not by the model remembering it.
- Insult comebacks fire only when the insult targets the bot: the
  message mentions "بهجت" or is a reply to the bot's message. A member
  insulting another member is not the bot being insulted.
- Opinion lines are topic-gated: they are Bahgat's Sisi/takfir stance,
  so they only fire when the question is ABOUT السيسي / التكفير /
  الكفر / الإخوان. Serving "السيسي كافر" as the answer to a golden-
  billion question would be off-topic nonsense.
- TARGET-SPECIFICITY (v1.3, Seif 2026-11-26): bank lines tagged
  `target: <subject>` in the YAML fire ONLY when the roast target
  names that subject (normalised substring match + a small alias map
  — e.g. "سيسي" and "بلحة" match السيسي). A line with no `target:`
  field is generic and fits any target. When no line fits the roast
  target, the pool falls back to generic lines only — never a
  mismatched target-specific line (live bug: "اشتم صلاح" served
  ro-21 "عاوز يغير في القرآن يا متناك؟", a Sisi line). If even the
  generic pool is empty, no bank line is served (the LLM handles it)
  rather than a non-sequitur.
- Rotation: random pick per trigger category, excluding the last 5
  lines served from that category in that chat (in-memory only), so
  the same comeback does not repeat every time.
- Contextual selection (v1.6 phase 2): every served insulted/roast
  line carries `situations:` tags in the YAML, and _pick() prefers
  lines tagged with the situation detected from the incoming message
  (brain.intent.detect_insult_situation / detect_roast_situation).
  When the situation has no tagged lines, or the tagged lines are all
  used up, it falls back to least-recently-used `general` lines, then
  to any unused line, then — pool exhausted — to the
  least-recently-used line outright (deterministic, so small pools
  rotate in full cycles instead of repeating at random).
- No-repeat window (v1.6 phase 2): the last 25 lines served from a
  category in a chat are excluded, PERSISTED in bot_state via
  brain.memory (get_recent_bank_lines / record_bank_line) so the
  window survives restarts — plus a per-user window (last 10 lines
  served to that user) so the same person never gets the same comeback
  twice in a row even after the chat window slid past it. The old
  in-memory last-5 (_last_used) is still maintained and consulted as
  a union, so it degrades gracefully if the store is unavailable.
- The matcher never raises: a missing/unparsable bank file just means
  no bank reply (the LLM path handles the turn).
"""
import os
import random
import re

from brain import memory as _memory
from brain.intent import (
    detect_insult_situation,
    detect_roast_situation,
    extract_insult_target,
    looks_like_insult,
    looks_like_opinion_ask,
    normalize_arabic,
)

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is installed; defensive only.
    yaml = None

_BANK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "persona", "bahgat", "reply_bank.yaml"
)
# Lines never served even though they are in the file: the hedges (their own
# notes say prefer searching) and anything with uncertain attribution.
_BLOCKED_IDS = {"op-05", "op-30"}
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
# Death / condolence words. Word-boundary matching, so "ماتش" (match)
# never fires the condolence line.
_CONDOLENCE_WORDS = [
    "مات", "توفي", "اتوفي", "توفت", "البقاء لله", "عزاء", "الله يرحم",
]

_bank_cache = None
_last_used: dict[tuple[int, str], list[str]] = {}


def _has(text: str, words) -> bool:
    """Word-boundary match on normalised text (mirrors brain.intent._has)."""
    return any(
        re.search(rf"(?<!\w){re.escape(normalize_arabic(w))}(?!\w)", text)
        for w in words
    )


def looks_like_challenge(text: str) -> bool:
    """True when the message challenges/argues with the bot (v1.3).

    Mirrors the bank's challenge branch (_CHALLENGE_WORDS): "انت غلط",
    "كلامك غلط", "مش صحيح", "بتخرف", "انت مش فاهم". Used by the
    handler to mark a turn provoked for voice_check().
    """
    return _has(normalize_arabic(text), _CHALLENGE_WORDS)


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


# Normalised aliases for target-specific roast subjects (v1.3).
# Substring matching (see _target_matches) already covers "سيسي" and
# "عبد الفتاح السيسي" (both contain / are contained by "السيسي"); the
# alias map covers spellings that share no substring with the subject.
# Deliberately NOT aliased: bare "عبد" — extract_insult_target captures
# only one word, so "اشتم عبد الله" also yields "عبد", and aliasing it
# would serve Sisi lines for unrelated عبد-prefixed names. Those fall
# back to generic lines instead (safe, just less specific).
_TARGET_ALIASES = {
    "السيسي": {"بلحه", "بلحة"},
    "كيسنجر": {"كسينجر"},
}


def _target_matches(line_target, roast_target: str | None) -> bool:
    """True when a bank line may serve for this roast target. A line
    with no `target:` field is generic and fits any target; a tagged
    line fits only when the target names its subject (normalised
    substring match either way, plus the alias map). `line_target`
    may be a single subject string or a list of them."""
    if line_target is None:
        return True
    rt = normalize_arabic(roast_target or "")
    if not rt:
        return False
    subjects = (
        line_target if isinstance(line_target, (list, tuple)) else [line_target]
    )
    for subject in subjects:
        s = normalize_arabic(str(subject))
        if not s:
            continue
        if s in rt or rt in s:
            return True
        if rt in {normalize_arabic(a) for a in _TARGET_ALIASES.get(s, ())}:
            return True
    return False


def _recent_ids(chat_id: int, category: str,
                user_id: int | None = None) -> set[str]:
    """Line ids excluded from the next pick: the in-memory last-5
    (_last_used) UNION the persisted chat window (last 25) UNION the
    per-user window (last 10 for that user). A store error degrades to
    the in-memory window only — never raises."""
    recent = set(_last_used.get((chat_id, category), []))
    try:
        recent.update(_memory.get_recent_bank_lines(chat_id, category))
        if user_id is not None:
            recent.update(
                _memory.get_recent_bank_lines(chat_id, category, user_id))
    except Exception:
        pass
    return recent


def _least_recently_used(entries: list[dict], chat_id: int,
                         category: str) -> dict | None:
    """The eligible line whose last serving is oldest: earliest in the
    persisted chat window wins; a line absent from the window (only
    possible via the in-memory window) counts as least recent; a
    `general`-tagged line wins ties — the neutral fallback. Used only
    when the whole eligible pool sits inside the no-repeat window."""
    if not entries:
        return None
    try:
        window = _memory.get_recent_bank_lines(chat_id, category)
    except Exception:
        window = []
    order = {line_id: i for i, line_id in enumerate(window)}

    def _key(e):
        return (order.get(e["id"], -1),
                0 if "general" in (e.get("situations") or []) else 1)

    return min(entries, key=_key)


def _record_pick(chat_id: int, category: str, line_id: str,
                 user_id: int | None = None) -> None:
    """Record a served line in the in-memory last-5 AND the persisted
    chat + per-user windows. Never raises."""
    key = (chat_id, category)
    _last_used[key] = (_last_used.get(key, []) + [line_id])[-5:]
    try:
        _memory.record_bank_line(chat_id, category, line_id, user_id=user_id)
    except Exception:
        pass


def _pick(
    category: str,
    chat_id: int,
    member_safe_only: bool = True,
    target: str | None = None,
    situation: str | None = None,
    user_id: int | None = None,
) -> str | None:
    """Random line from a category, preferring lines tagged with
    `situation` (v1.6 phase 2) and excluding the no-repeat window
    (persisted last 25 per chat + last 10 per user + in-memory last 5).
    member_safe_only=True (default) excludes lines tagged
    `member_safe: false` — family-insult lines, served only when the
    caller has established a resolved non-member target.
    target (roast only): when given, only generic lines (no `target:`
    field) and lines whose `target:` matches it are eligible; when no
    line fits, the pool is the generic lines only — and if there are
    no generic lines either, None (never a mismatched line). When
    target is None (every other category) there is no filtering.
    situation: when given and not "general", lines whose `situations:`
    list contains it are preferred. When the situation has NO tagged
    line in the eligible pool (e.g. cowardly — no roast line carries
    it yet), the preference falls to `general`-tagged lines. When the
    preferred lines are all inside the no-repeat window, the fallback
    order is: `general` lines not in the window, then any line not in
    the window, then — pool exhausted — the least-recently-used line
    (deterministic, see _least_recently_used)."""
    entries = load_bank().get(category) or []
    if member_safe_only:
        entries = [e for e in entries if e.get("member_safe", True) is not False]
    if target is not None:
        entries = [e for e in entries if _target_matches(e.get("target"), target)]
    if not entries:
        return None
    preferred = entries
    if situation and situation != "general":
        tagged = [e for e in entries
                  if situation in (e.get("situations") or [])]
        if tagged:
            preferred = tagged
        else:
            generic = [e for e in entries
                       if "general" in (e.get("situations") or [])]
            if generic:
                preferred = generic
    recent = _recent_ids(chat_id, category, user_id)
    available = [e for e in preferred if e["id"] not in recent]
    if not available:
        generic = [e for e in entries
                   if "general" in (e.get("situations") or [])]
        available = [e for e in generic if e["id"] not in recent]
    if not available:
        available = [e for e in entries if e["id"] not in recent]
    if available:
        entry = random.choice(available)
    else:
        # Whole eligible pool inside the window: rotate through the
        # FULL pool (not just the preferred subset — a 1-line preferred
        # pool would otherwise loop on that line forever).
        entry = _least_recently_used(entries, chat_id, category)
        if entry is None:
            return None
    _record_pick(chat_id, category, entry["id"], user_id)
    return entry["line"]


# v1.11 (Seif 2026-11-27): bank INSULT lines (insulted + roast) are
# INGREDIENTS, never standalone replies. When one is picked, the
# handler feeds it into the LLM turn, which must weave the exact line
# into the middle of a fuller, contextual reply — the line is never
# sent verbatim on its own. All pick-time filters still apply
# (member_safe, target-specificity, situation tags, no-repeat window),
# and the owner gates below are untouched. The other categories
# (joke_request, greeting, opinion_asked, condolence, challenge,
# dismiss) stay verbatim: a joke, a stance, condolences, a greeting,
# a debate line or a two-word dismissal IS the reply's content —
# weaving it into longer text would dilute or distort it.

# Categories whose picked line becomes an LLM ingredient (v1.11).
INGREDIENT_CATEGORIES = frozenset({"insulted", "roast"})


def ingredient_in_reply(reply: str, line: str) -> bool:
    """True when the reply weaves the exact bank line in. Normalised
    substring match first (alef/ة/ى variants match); if the model
    reflowed the line slightly (extra word, different punctuation),
    a word-subsequence check with >= 80% of the line's words in order
    still counts — the point is the line is IN the reply, not that
    every character survived."""
    if not line or not reply:
        return False
    norm_reply = normalize_arabic(reply)
    norm_line = normalize_arabic(line)
    if norm_line and norm_line in norm_reply:
        return True
    words = [w for w in norm_line.split() if len(w) > 1]
    if not words:
        return False
    reply_words = norm_reply.split()
    matched = 0
    pos = 0
    for w in words:
        try:
            pos = reply_words.index(w, pos) + 1
            matched += 1
        except ValueError:
            continue
    return matched / len(words) >= 0.8


def is_standalone_line(reply: str, line: str) -> bool:
    """True when the reply IS the bank line (or barely more) — the
    exact violation of the v1.11 rule. Normalised comparison; a reply
    that adds fewer than 10 characters around the line still counts
    as standalone (e.g. the line + \"يا عم\" is not a fuller reply)."""
    if not line or not reply:
        return False
    norm_reply = normalize_arabic(reply).strip()
    norm_line = normalize_arabic(line).strip()
    if norm_reply == norm_line:
        return True
    return norm_line in norm_reply and len(norm_reply) - len(norm_line) < 10


def match_reply_bank_categorized(
    text: str,
    *,
    chat_id: int,
    is_owner: bool = False,
    is_reply_to_bot: bool = False,
    target_is_member: bool | None = None,
    target_is_owner: bool = False,
    user_id: int | None = None,
) -> tuple[str, str] | None:
    """Like match_reply_bank, but returns (category, line) so the
    caller knows whether the picked line is an ingredient (v1.11:
    insulted/roast) or a verbatim reply (all other categories).

    Priority: insulted > roast > joke > opinion > condolence >
    challenge > greeting — a message carrying two signals
    ("اهلا يا بهجت انت حمار") must get the comeback, not the greeting.

    target_is_member / target_is_owner describe the ROAST target
    ("اشتم X"), resolved by the caller from the membership cache only
    (no network call — the fast path stays instant). None means
    unresolved and fails safe to member-safe lines."""
    t = normalize_arabic(text or "")
    words = t.split()
    targeted = "بهجت" in words or is_reply_to_bot

    # Insulted: the bot is the target, and never the owner. The target
    # is the sender — always a member — so member-safe lines only.
    # v1.6 phase 2: the comeback prefers lines tagged with the detected
    # situation (what the user did to the bot).
    if not is_owner and targeted and looks_like_insult(text):
        line = _pick("insulted", chat_id,
                     situation=detect_insult_situation(text),
                     user_id=user_id)
        if line is not None:
            return ("insulted", line)

    # Roast request ("اشتم X"): serve a roast line. Never at the owner,
    # never at the bot itself ("اشتم بهجت" goes to the LLM instead).
    # Family-insult lines only for a RESOLVED non-member target.
    roast_target = extract_insult_target(text)
    if roast_target and not target_is_owner:
        if normalize_arabic(roast_target) != "بهجت":
            # v1.3: target-specific lines (target: السيسي ...) fire only
            # for their subject; any other target gets generic lines.
            # v1.6 phase 2: the roast prefers lines tagged with the
            # situation from the request's extra words ("عشان بيتباهى").
            line = _pick(
                "roast", chat_id,
                member_safe_only=(target_is_member is not False),
                target=roast_target,
                situation=detect_roast_situation(text),
                user_id=user_id,
            )
            if line is not None:
                return ("roast", line)

    # Joke request ("قول نكته" / "قولي نكته" / "هات نكته").
    if _has(t, _JOKE_WORDS):
        line = _pick("joke_request", chat_id)
        if line is not None:
            return ("joke_request", line)

    # Opinion: only Bahgat's own Sisi/takfir stance, only on that topic.
    # The lines are ABOUT a non-member subject, never about a group
    # member, so the pool is not member-restricted.
    if looks_like_opinion_ask(text) and _has(t, _OPINION_TOPICS):
        line = _pick("opinion_asked", chat_id, member_safe_only=False)
        if line is not None:
            return ("opinion_asked", line)

    # Condolence: someone died ("مات", "توفي", "البقاء لله" ...).
    if _has(t, _CONDOLENCE_WORDS):
        line = _pick("condolence", chat_id)
        if line is not None:
            return ("condolence", line)

    # Challenge / argument: dismiss or answer back. Never at the owner.
    if not is_owner and _has(t, _CHALLENGE_WORDS):
        line = _pick("challenge", chat_id)
        if line is not None:
            return ("challenge", line)
        line = _pick("dismiss", chat_id)
        if line is not None:
            return ("dismiss", line)

    # Greeting: short message only, so "اهلا يا بهجت انت حمار" (long,
    # insult) never lands here — the insult branch above already won.
    if len(words) <= 3 and _has(t, _GREETING_WORDS):
        line = _pick("greeting", chat_id)
        if line is not None:
            return ("greeting", line)

    return None


def match_reply_bank(
    text: str,
    *,
    chat_id: int,
    is_owner: bool = False,
    is_reply_to_bot: bool = False,
    target_is_member: bool | None = None,
    target_is_owner: bool = False,
    user_id: int | None = None,
) -> str | None:
    """Return a bank line for this message, or None. Thin wrapper over
    match_reply_bank_categorized — kept so existing callers and tests
    keep working. NOTE (v1.11): a returned insulted/roast line is an
    INGREDIENT, not a standalone reply — the handler must weave it
    into an LLM reply (see INGREDIENT_CATEGORIES)."""
    pick = match_reply_bank_categorized(
        text, chat_id=chat_id, is_owner=is_owner,
        is_reply_to_bot=is_reply_to_bot,
        target_is_member=target_is_member,
        target_is_owner=target_is_owner, user_id=user_id,
    )
    return pick[1] if pick is not None else None
