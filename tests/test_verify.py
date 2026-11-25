from brain.verify import check_reply, split_message, escape_html
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
