"""Search follow-up queries (v0.7e).

Regression: Seif asked "عايز اعرف ايه الحصل في حادثة الوراق المهاردة",
then "ايه الحصل". The bot searched the literal follow-up and grounded
its answer on song lyrics instead of the Waraq incident. Short
follow-ups must inherit the topic from recent history.
"""
from tg.handlers import _search_query


def _hist(*user_texts):
    return [{"role": "user", "content": f"[Seif Allah Mo]: {t}"} for t in user_texts]


def test_followup_inherits_waraq_topic():
    history = _hist(
        "عامل ايه يا بهجت",
        "قولي نكته",
        "يا وسخ",
        "عايز اعرف ايه الحصل في حادثة الوراق المهاردة",
    )
    q = _search_query("ايه الحصل", history)
    assert "الوراق" in q
    assert "ايه الحصل" in q


def test_self_contained_message_unchanged():
    history = _hist("عايز اعرف ايه الحصل في حادثة الوراق المهاردة")
    q = _search_query("ايه سعر الدولار النهارده في مصر", history)
    assert q == "ايه سعر الدولار النهارده في مصر"


def test_no_topic_in_history_unchanged():
    history = _hist("عامل ايه يا بهجت", "قولي نكته", "يا وسخ")
    assert _search_query("ايه الحصل", history) == "ايه الحصل"
    assert _search_query("ايه الحصل", []) == "ايه الحصل"


def test_assistant_turns_ignored_and_prefix_stripped():
    history = [
        {"role": "assistant", "content": "تمام يا عم، زي الفل. انت عامل ايه، جايبلي ايه النهارده؟"},
        {"role": "user", "content": "[Seif Allah Mo]: عايز اعرف ايه الحصل في حادثة الوراق المهاردة"},
    ]
    q = _search_query("ايه الحصل", history)
    assert "الوراق" in q
    assert "Seif Allah Mo" not in q


def test_latest_substantive_turn_wins():
    history = _hist(
        "عايز اعرف ايه الحصل في حادثة الوراق المهاردة",
        "عايز اعرف نتيجة مباراة الاهلي والزمالك امبارح",
    )
    q = _search_query("ايه النتيجة", history)
    assert "الاهلي" in q
    assert "الوراق" not in q
