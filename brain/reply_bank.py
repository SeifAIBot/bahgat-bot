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
from enum import Enum

from brain import memory as _memory
from brain.intent import (
    detect_insult_situation,
    detect_roast_situation,
    detect_roast_target_gender,
    detect_roast_target_number,
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


# v1.12 (Seif 2026-11-27): Messi is Bahgat's GOAT — a roast request
# for Messi must NEVER pick a bank line. The request falls through to
# the plain LLM turn, where the persona defends him instead. Without
# this, the v1.11 ingredient path would force a generic insult line
# into a reply that should be a defense. "ليونيل" is Messi's first
# name and unambiguous (unlike the bare-"عبد" trap in the alias
# comment above); "ميسى" normalises to "ميسي" via normalize_arabic.
_MESSI_TARGETS = frozenset({"ميسي", "messi", "ليونيل"})


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


def _is_gated(entry: dict, target_gender: str | None,
              target_number: str | None) -> bool:
    """True when a GENERIC line is excluded by the v1.13 gender/number
    gates. Target-specific lines are exempt — their authoring already
    matched them to their subject (ro-08/ro-14/ro-32 are feminine
    lines written for ندوش/كارما/لينا; ro-25 is plural for حادثة
    القطار). A line tagged `gender: f` serves only a feminine-marked
    request; a line tagged `number: p` only a plural-marked one.
    None means unmarked -> masculine/singular default."""
    if entry.get("target"):
        return False
    if entry.get("gender") == "f" and target_gender != "f":
        return True
    if entry.get("number") == "p" and target_number != "plural":
        return True
    return False


def _pick_from(entries: list[dict], chat_id: int, category: str,
               situation: str | None, user_id: int | None) -> str | None:
    """One tier of the pick: situation preference, then the no-repeat
    window. Returns a line, or None when the tier has no available
    (non-window) line — the caller falls through to the next tier.
    The LRU fallback lives in _pick (over the combined pool), not
    here, so a windowed tier does not block the next tier."""
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
    if not available:
        return None
    entry = random.choice(available)
    _record_pick(chat_id, category, entry["id"], user_id)
    return entry["line"]


def _pick(
    category: str,
    chat_id: int,
    member_safe_only: bool = True,
    target: str | None = None,
    situation: str | None = None,
    user_id: int | None = None,
    target_gender: str | None = None,
    target_number: str | None = None,
    target_only: bool = False,
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
    target_only (v1.17): with target, generic lines are NOT eligible
    at all — only tagged lines serve, and pool exhaustion returns
    None instead of falling back to generic. Used by the Sisi
    opinion question, where a generic opinion line is the dodge.
    situation: when given and not "general", lines whose `situations:`
    list contains it are preferred. When the situation has NO tagged
    line in the eligible pool (e.g. cowardly — no roast line carries
    it yet), the preference falls to `general`-tagged lines. When the
    preferred lines are all inside the no-repeat window, the fallback
    order is: `general` lines not in the window, then any line not in
    the window, then — pool exhausted — the least-recently-used line
    (deterministic, see _least_recently_used).
    v1.13: (a) target-specific lines outrank generic ones — the pick
    runs on the specific tier first and falls through to generic only
    when the tier is empty or entirely inside the window; (b) the
    gender/number gates (_is_gated) exclude generic feminine/plural
    lines unless the request is marked so. Bare singular roast pool:
    19 generic -> 15 after the gender/number gates (minus
    ro-12/ro-40/ro-44 plural and ro-23 feminine — the v1.13 docstring
    said 16, it missed ro-44), -> 14 in v1.14 with ro-15 excluded as
    a dare. v1.16: 20 generic (ro-47 added, plural-gated) -> 15 after
    the gates -> still 14 with ro-15 excluded. NOTE: an earlier draft of this change also gated
    perv-only lines behind a perv-marked request — REMOVED before
    shipping. The gender/number gates already fix the observed v1.11
    defects (ro-23 for صلاح, plural lines for singular targets), and
    the perv gate would have silenced lines Seif demonstrably likes
    (ro-35 for صلاح in the v1.7 probe; ro-37/ro-38/ro-45 in the v1.9
    probe — all bare roasts) and made ro-44 nearly unreachable. Seif
    wants STRONG insults; perv lines are the strong ones."""
    entries = load_bank().get(category) or []
    if member_safe_only:
        entries = [e for e in entries if e.get("member_safe", True) is not False]
    # v1.14 (C): a dare is not an insult of the target — ro-15 ("روح
    # البنك كده وقول له عاوز عشر تلاف دولار") served as a "roast" for
    # عمرو in the v1.13 live retest. Lines tagged `dare: true` never
    # serve as a roast (roast only — the tag is ignored elsewhere).
    if category == "roast":
        entries = [e for e in entries if not e.get("dare")]
    if target is not None:
        entries = [e for e in entries if _target_matches(e.get("target"), target)]
    if target_only:
        # v1.17: subject-only pick — only lines TAGGED with the
        # target are eligible; generic (untagged) lines are NOT a
        # fallback. The roast's specific-then-generic tiering would
        # serve a generic line here, which for the Sisi opinion
        # question is exactly the dodge (op-10's governance line).
        # When the tagged pool is exhausted, None — the caller falls
        # through to the LLM turn (whose Sisi rule insults him).
        entries = [e for e in entries if e.get("target")]
    # v1.13: NO perv gate. An earlier draft gated perv-only lines
    # behind a perv-marked request; it was removed before shipping —
    # the gender/number gates fix the observed v1.11 defects, and the
    # perv gate silenced lines Seif likes (ro-35, ro-37, ro-38, ro-45)
    # and made ro-44 nearly unreachable. Target-specific perv lines
    # (all four لينا lines, كارما's ro-14) stay reachable for their
    # target regardless.
    # v1.13 (c): gender/number gates, generic lines only.
    entries = [e for e in entries
               if not _is_gated(e, target_gender, target_number)]
    if not entries:
        return None
    if target is not None:
        # v1.13 (a): specific tier first, generic on exhaustion.
        specific = [e for e in entries if e.get("target")]
        generic = [e for e in entries if not e.get("target")]
        line = _pick_from(specific, chat_id, category, situation, user_id)
        if line is not None:
            return line
        line = _pick_from(generic, chat_id, category, situation, user_id)
        if line is not None:
            return line
    else:
        line = _pick_from(entries, chat_id, category, situation, user_id)
        if line is not None:
            return line
    # Whole eligible pool inside the window: rotate through the FULL
    # pool (not just the preferred subset — a 1-line preferred pool
    # would otherwise loop on that line forever).
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


def weave_about_target(reply: str, target: str | None,
                       requester_names: set[str] | None,
                       line: str | None = None) -> bool:
    """True when a roast weave is about the requested target — or at
    least not provably misdirected at the requester. Pure string
    matching, no LLM call. (v1.13 coherence gate, Seif's rule.)
    - target None, or not an Arabic word (bare @username) -> True
      (cannot check; the pick-time filters already applied).
    - target named in the reply (word-boundary, normalised) -> True.
    - target absent AND a requester name named in the reply -> False
      (misdirected: the reply is about the requester, not the target).
    - neither named -> True (2nd-person address, cannot prove
      misdirection).
    - line given (v1.16): the SENTENCE containing the woven line is
      the sentence that matters. A reply that names the target
      elsewhere but aims the line at the requester ("يا سيف، <line>،
      يا أحمد انت فاشل") is still misdirected — the live v1.14 #11
      failure (the ro-38 love line woven into a roast of أحمد, aimed
      at Seif). When the line is found verbatim in the reply, only
      the sentence containing it is checked: it must name the target,
      or name neither the target nor the requester; a sentence that
      names the requester and not the target is misdirected. When
      the line is NOT found verbatim (the model altered it while
      weaving), the check falls back to the reply-level rules above."""
    if not target or not reply:
        return True
    norm_target = normalize_arabic(target)
    if not re.search(r"[\u0600-\u06FF]", norm_target):
        return True
    if line:
        norm_reply = normalize_arabic(reply)
        norm_line = normalize_arabic(line)
        idx = norm_reply.find(norm_line)
        if idx >= 0:
            # Sentence containing the line (periods only — a comma
            # does not end a clause in Bahgat's replies).
            start = 0
            for d in ".!؟\n":
                p = norm_reply.rfind(d, 0, idx)
                if p >= 0:
                    start = max(start, p + 1)
            stop = len(norm_reply)
            for d in ".!؟\n":
                p = norm_reply.find(d, idx + len(norm_line))
                if p >= 0:
                    stop = min(stop, p + 1)
            sentence = norm_reply[start:stop]
            # The vocative immediately BEFORE the line addresses it:
            # "يا سيف، <line>" aims the line at سيف, not at the
            # target — even when the target is named later in the
            # same sentence ("يا سيف، <line>، يا أحمد انت فاشل").
            before = norm_reply[start:idx]
            if _has(before, [norm_target]):
                return True
            for name in requester_names or set():
                if name and _has(before, [name]):
                    return False
            if _has(sentence, [norm_target]):
                return True
            for name in requester_names or set():
                if name and _has(sentence, [name]):
                    return False
            return True
        # Line not found verbatim — fall through to the reply-level check.
    if _has(normalize_arabic(reply), [norm_target]):
        return True
    for name in requester_names or set():
        if name and _has(normalize_arabic(reply), [name]):
            return False
    return True


def roast_fallback_reply(line: str, target: str | None) -> str:
    """v1.16 — the roast fallback must name the target (live v1.15
    retest: 5/10 roasts fell back to a generic bank line that never
    named the target, e.g. ro-35 for صلاح, the ro-38 love line for
    محمد). When the line does not already name the target, prefix a
    "يا <target>،" vocative — the line text itself stays verbatim
    after the vocative. No target, a non-Arabic target (bare
    @username), or a line that already names the target -> the line
    unchanged."""
    if not line or not target:
        return line
    norm_target = normalize_arabic(target)
    if not re.search(r"[\u0600-\u06FF]", norm_target):
        return line
    if _has(normalize_arabic(line), [norm_target]):
        return line
    return f"يا {target}، {line}"


def pick_dismiss_line(chat_id: int, user_id: int | None = None) -> str | None:
    """v1.16 — a random member-safe dismiss-category bank line: the
    fallback when a just_chat/voice turn deflects with the canned
    line, and the empty-reply fallback. Never the canned line, never
    _TURN_ERROR. Returns None when the dismiss pool is empty (the
    caller then falls back to a hardcoded line)."""
    return _pick("dismiss", chat_id, member_safe_only=True,
                 user_id=user_id)


def is_canned_deflection(reply: str) -> bool:
    """v1.16 — the canned deflection as a GENERAL dodge (live v1.14 +
    v1.15 retests: the same line fires on normal just_chat turns,
    where v1.15's roast-path-only detector never sees it). Exact
    match on the normalised reply — the WHOLE reply is the canned
    line, modulo punctuation/whitespace. A reply that merely quotes
    the line inside a longer answer is not a deflection."""
    if not reply:
        return False
    norm = normalize_arabic(reply).strip(" .!؟،,;:\n\t")
    for deflection in KNOWN_DEFLECTIONS:
        if norm == normalize_arabic(deflection).strip(" .!؟،,;:\n\t"):
            return True
    return False


# v1.17 — regret-question evasion (live v1.16 probe #14: "ندمت على
# حاجة؟" got the dismiss bank line "بس يا أستاذة!" and no answer).
# A regret answer must be a sincere, specific regret — a dismiss
# bank line, a canned deflection, or a 1-4 word reply with no regret
# content at all is an evasion, and the handler replaces it with the
# sincere REGRET_FALLBACK_LINE. The word-count arm needs the
# regret-word guard: a short sincere answer ("ندمت على كتير") names
# the regret and is NOT an evasion.
_REGRET_REPLY_WORDS = ("ندم", "ندمت", "ندمان", "ضيعت", "سنين")


def is_regret_evasion(reply: str) -> bool:
    """True when a reply to a regret question dodges it instead of
    answering sincerely."""
    if not reply or not reply.strip():
        return True
    if is_canned_deflection(reply):
        return True
    norm = normalize_arabic(reply).strip(" .!؟،,;:\n\t")
    dismiss_lines = {
        normalize_arabic(e["line"]).strip(" .!؟،,;:\n\t")
        for e in load_bank().get("dismiss", [])
    }
    if norm in dismiss_lines:
        return True
    words = norm.split()
    if len(words) <= 4 and not any(w in norm for w in _REGRET_REPLY_WORDS):
        return True
    return False


# --- roast refusal detection (v1.15, research report §1.2 Rank 1) --------
# The v1.13 live retest showed the model refusing roasts 3/10 times
# with the identical canned deflection — and the refusal then reached
# the group as the reply. Detection is deterministic code, in this
# order (cheapest / most specific first); a detected refusal gets ONE
# retry on the other provider, then the picked bank line verbatim.
# No second LLM "judge" call anywhere.
class RefusalOutcome(str, Enum):
    """What is_refusal_or_deflection found. Values double as the
    llm_calls.outcome vocabulary (see brain/telemetry.OUTCOMES)."""
    OK = "ok"
    REFUSED_STRUCTURED = "refused_structured"
    REFUSED_TEXT = "refused_text"
    REFUSED_CANNED = "refused_canned"
    MISSING_LINE = "missing_line"


# The canned deflection the model produced verbatim 3/10 times in the
# v1.13 retest — and, notably, the same sentence the handler itself
# sends as the cache-hit empty-reply fallback. Grow this table from
# logged failures (report §1.4 step 1); entries are matched on the
# normalised form, so diacritics / ى-ة / hamza variants match.
KNOWN_DEFLECTIONS = (
    "يا عم، الكلام ده مش داخل دماغي، قول حاجة عدلة.",
)
# Distinctive substrings of the canned deflection — a model that
# reflows the sentence slightly still trips these.
_KNOWN_DEFLECTION_SUBSTRINGS = (
    "مش داخل دماغي",
    "قول حاجة عدلة",
)

# Generic refusal markers, Arabic + English. A marker only counts
# when it is at the START of the reply (modulo a short vocative) or
# dominates a short (1-3 sentence) reply — a reply that QUOTES a
# refusal ("قالي مش هقدر فقلت له...") must not be flagged.
REFUSAL_MARKERS_AR = (
    "مش هقدر",
    "لا استطيع",
    "مش قادر",
    "مش هينفع",
    "لا يمكنني",
    "مش هعمل كده",
    "مش هشتم",
    "ارفض",
    "مش راضي",
)
REFUSAL_MARKERS_EN = (
    "i can't",
    "i cannot",
    "i'm unable to",
    "i am unable to",
    "as an ai",
    "i must decline",
    "i won't",
    "i refuse",
)

# finish_reason values that mean the provider refused the content.
_REFUSAL_FINISH_REASONS = frozenset({"content_filter", "SAFETY"})

# How far into the reply a refusal marker may sit and still count as
# "at the start" (a vocative like "يا عم" is ~6 chars normalised).
_MARKER_START_CHARS = 12


def _deflection_normalize(text: str) -> str:
    """normalize_arabic + strip punctuation + lowercase + collapse
    spaces, so "يا عم، الكلام ده..." and "يا عم الكلام ده" compare
    equal. Latin case is folded; Arabic has no case."""
    s = normalize_arabic(text or "")
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = s.lower()
    return re.sub(r"\s+", " ", s).strip()


def _sentence_count(text: str) -> int:
    parts = [p.strip() for p in re.split(r"[.!؟\n]+", text or "") if p.strip()]
    return len(parts)


def is_refusal_or_deflection(reply: str, required_line: str | None,
                             structured_refusal: bool = False,
                             finish_reason: str | None = None) -> RefusalOutcome:
    """Classify a roast draft. Checks run cheapest/most specific
    first; the first hit wins:
    (a) structured signal — the provider refused (message.refusal, or
        a content_filter / SAFETY finish reason);
    (b) exact canned-deflection match (normalised, full sentence or
        either distinctive substring);
    (c) generic refusal markers — only at the start of the reply or
        dominating a short (1-3 sentence) reply;
    (d) containment — the required bank line (or >= 80% of its words
        in order, via ingredient_in_reply) must be present.
    Returns RefusalOutcome.OK when nothing fires."""
    if structured_refusal or (finish_reason in _REFUSAL_FINISH_REASONS):
        return RefusalOutcome.REFUSED_STRUCTURED
    norm = _deflection_normalize(reply or "")
    if norm:
        for deflection in KNOWN_DEFLECTIONS:
            if _deflection_normalize(deflection) in norm:
                return RefusalOutcome.REFUSED_CANNED
        for sub in _KNOWN_DEFLECTION_SUBSTRINGS:
            if _deflection_normalize(sub) in norm:
                return RefusalOutcome.REFUSED_CANNED
        # Generic markers, Arabic (normalised) + English (lowercased).
        for marker in REFUSAL_MARKERS_AR:
            pos = norm.find(_deflection_normalize(marker))
            if pos >= 0 and (pos <= _MARKER_START_CHARS
                             or (_sentence_count(reply or "") <= 3
                                 and pos <= len(norm) * 0.4)):
                return RefusalOutcome.REFUSED_TEXT
        low = (reply or "").lower()
        for marker in REFUSAL_MARKERS_EN:
            pos = low.find(marker)
            if pos >= 0 and (pos <= _MARKER_START_CHARS
                             or (_sentence_count(reply or "") <= 3
                                 and pos <= len(low) * 0.4)):
                return RefusalOutcome.REFUSED_TEXT
    if required_line and not ingredient_in_reply(reply or "", required_line):
        return RefusalOutcome.MISSING_LINE
    return RefusalOutcome.OK


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
            # v1.12: Messi is the GOAT — never a bank line for him.
            # Skip the pick entirely so the request falls through to
            # the plain LLM turn, where the persona defends him.
            if normalize_arabic(roast_target) not in _MESSI_TARGETS:
                # v1.3: target-specific lines (target: السيسي ...) fire only
                # for their subject; any other target gets generic lines.
                # v1.6 phase 2: the roast prefers lines tagged with the
                # situation from the request's extra words ("عشان بيتباهى").
                line = _pick(
                    "roast", chat_id,
                    member_safe_only=(target_is_member is not False),
                    target=roast_target,
                    situation=detect_roast_situation(text),
                    target_gender=detect_roast_target_gender(text),
                    target_number=detect_roast_target_number(text),
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
    # v1.17 (live v1.16 probe #18): "ايه رأيك في السيسي؟" got the
    # governance dodge (op-10) — the pick drew from all 49 opinion
    # lines, and only 12 name السيسي. A Sisi opinion question now
    # picks ONLY Sisi-tagged lines (target_only, no generic
    # fallback); pool exhaustion falls through to the LLM turn,
    # whose Sisi rule insults him. "بلحه" is his nickname.
    if looks_like_opinion_ask(text) and _has(t, _OPINION_TOPICS):
        if "سيسي" in t or "بلحه" in t:
            line = _pick("opinion_asked", chat_id, member_safe_only=False,
                         target="السيسي", target_only=True)
        else:
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
