from brain.verify import (
    _SELF_BOT_DENIAL,
    check_reply,
    contains_self_bot_admission,
    escape_html,
    split_message,
    voice_check,
)
from brain.prompt import build_system_prompt, temperature_for

def test_family_insult_blocked_for_member():
    ok, cleaned = check_reply("يا ابن امك يا غبي", insult_level="personal_only")
    assert "امك" not in cleaned
    assert ok is False

def test_family_insult_allowed_for_non_member():
    ok, cleaned = check_reply("يا ابن امك", insult_level="full")
    assert ok is True

def test_banned_ai_phrase_removed():
    ok, cleaned = check_reply("كذكاء اصطناعي أنا لا أعرف", insult_level="full")
    assert "كذكاء اصطناعي" not in cleaned

def test_self_bot_admission_replaced_with_denial():
    # v1.8: any first-person bot/AI admission is replaced wholesale
    # with an in-character denial — the bot never sends it.
    for admission in ("أنا بوت يا عم", "أنا ذكاء اصطناعي، آسف",
                      "أنا مش بني آدم", "انا برنامج مش انسان"):
        ok, cleaned = check_reply(admission, insult_level="full")
        assert ok is False
        assert cleaned == _SELF_BOT_DENIAL
        assert not contains_self_bot_admission(cleaned)
        # The denial itself passes its own filter.
        assert check_reply(cleaned, insult_level="full")[0] is True

def test_talking_about_other_bots_is_not_an_admission():
    # v1.8 scoping: the rule is about Bahgat HIMSELF — answers about
    # other bots/people must pass untouched.
    for text in ("سعد ده بوت يا عم", "انت مش بني آدم يا غبي",
                 "وعد ده بوت تحميل مش أكتر"):
        assert contains_self_bot_admission(text) is False
        ok, cleaned = check_reply(text, insult_level="full")
        assert ok is True
        assert cleaned == text

def test_self_bot_admission_flags_voice_check():
    assert "self_bot_admission" in voice_check("أنا بوت يا عم")
    assert "self_bot_admission" in voice_check("أنا ذكاء اصطناعي")
    assert voice_check("سعد ده بوت") == []
    assert voice_check(_SELF_BOT_DENIAL) == []

def test_split_long_message():
    parts = split_message("x" * 9000)
    assert len(parts) >= 3
    assert all(len(p) <= 4000 for p in parts)

def test_escape_html():
    assert escape_html("<b> &") == "&lt;b&gt; &amp;"

def test_prompt_contains_guardrails():
    s = build_system_prompt(member={"first_name": "سيف", "username": "x", "notes": "", "grudge": ""}, mood=80, search_text="test")
    assert "عامية مصرية" in s
    assert "80/100" in s
    assert "test" in s

def test_temperature_search_low():
    assert temperature_for("search") < temperature_for("just_chat")
