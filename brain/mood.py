"""Mood 0-100. Insult raises it fast, praise calms it down.

Decay is TIME-BASED ONLY and lives in brain/memory.py (get_member:
-10/hour, floor 30, persisted on read). This module deliberately does NO
per-message decay — the old "-5 per non-insult message" dragged a calm
member to 0 within a friendly 10-message chat, and combined with the
read-decay it was two clocks fighting each other.
"""


import random as _random
import re


def _normalize(text: str) -> str:
    """Light Arabic normalisation for marker matching (same folds as the
    handlers' fallback: strip diacritics/tatweel, أ/إ/آ→ا, ة→ه, ى→ي)."""
    t = re.sub(r"[\u064b-\u0652\u0640]", "", text or "")
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    t = t.replace("ة", "ه").replace("ى", "ي")
    return re.sub(r"\s+", " ", t).strip()


# Markers for the reply-delay bands (v1.9, Instinct flaw-fix): a human
# does not answer everything at the same speed — an urgent "رد بسرعة"
# gets an instant reply, a sad message gets a slow thoughtful one.
_URGENT_MARKERS = (
    "بسرعه", "بسرعة", "حالا", "دلوقتي", "عاجل", "بسررعه", "بسرررعه",
)
_SAD_MARKERS = (
    "زعلان", "حزين", "مكتئب", "تعبان", "مخنوق", "موجوع", "قرفان",
    "زهقان", "مضايق",
)
_QUESTION_STARTERS = (
    "ايه", "ازاي", "ليه", "هل", "مين", "امتى", "فين", "ازاى", "كام",
    "ايه رايك", "ايه رأيك",
)


def _looks_like_question(text: str) -> bool:
    """A direct question: ends with ؟/? or opens with a question word."""
    t = (text or "").strip()
    if t.endswith(("؟", "?")):
        return True
    return any(t.startswith(w) for w in _QUESTION_STARTERS)


def reply_delay_band(mood: int, text: str) -> tuple[float, float]:
    """(lo, hi) seconds for the human-like pause before a reply (v1.9).

    Bands (Instinct's "fixed reply speed" tell): هزار 1–3s, غضب 2–4s,
    استعجال immediate, حزن 4–7s, serious question 3–6s. The bot's own
    anger (mood >= 70) dominates over the user's sadness — a furious
    Bahgat simmers on his own clock. Pure: safe to unit-test."""
    t = _normalize(text)
    if any(m in t for m in _URGENT_MARKERS):
        return (0.0, 0.0)
    if (mood or 0) >= 70:
        return (2.0, 4.0)
    if any(m in t for m in _SAD_MARKERS):
        return (4.0, 7.0)
    if _looks_like_question(t):
        return (3.0, 6.0)
    return (1.0, 3.0)


def reply_delay_seconds(mood: int, text: str, rng=None) -> float:
    """One sampled delay: uniform in the band, then ±30% jitter.

    `rng` needs only .uniform(a, b) (the `random` module by default) —
    tests pass a stub for determinism. Never negative."""
    lo, hi = reply_delay_band(mood, text)
    if hi <= 0:
        return 0.0
    r = rng if rng is not None else _random
    base = r.uniform(lo, hi)
    return max(0.0, base * (1.0 + r.uniform(-0.3, 0.3)))


def update_mood(current: int, insulted: bool, praised: bool = False,
                insult_bump: int = 40) -> int:
    """insult_bump (v1.6 phase 2): how much anger one insult adds.
    Default 40 = the old flat bump, so existing callers are unchanged.
    The handler passes SITUATION_MOOD_BUMP for the detected situation
    (a family attack stings more than a mild mock)."""
    if insulted:
        return min(100, current + insult_bump)
    if praised:
        return max(0, current - 20)
    return current


# Anger bump per detected insult situation (v1.6 phase 2). "general"
# and untagged insults keep the old flat +40.
SITUATION_MOOD_BUMP = {
    "family-attacked": 60,
    "threatened": 50,
    "repeated-insult": 50,
    "sworn-at": 45,
    "called-dumb": 40,
    "general": 40,
    "dismissed": 35,
    "mocked": 30,
}


def should_use_voice(mood: int, asked: bool, topic_interesting: bool,
                     random_roll: float, reply_len: int = 0) -> bool:
    if asked:
        return True
    # Anger NEVER forces voice on its own (that was a bug): an angry voice
    # reply happens only when the user asked for voice. topic_interesting
    # no longer forces voice either.
    if random_roll < 0.05 and reply_len < 200:
        return True
    return False
