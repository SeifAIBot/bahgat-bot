"""Mood 0-100. Insult raises it fast, praise calms it down.

Decay is TIME-BASED ONLY and lives in brain/memory.py (get_member:
-10/hour, floor 30, persisted on read). This module deliberately does NO
per-message decay — the old "-5 per non-insult message" dragged a calm
member to 0 within a friendly 10-message chat, and combined with the
read-decay it was two clocks fighting each other.
"""


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
