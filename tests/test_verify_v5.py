from brain.verify import check_reply, contains_family


def test_silent_rewrite_no_meta_commentary():
    ok, cleaned = check_reply("يا ابن امك يا غبي", insult_level="personal_only")
    assert ok is False
    assert "امك" not in cleaned
    assert "سيف" not in cleaned
    assert "قاعدة" not in cleaned
    assert "القاعدة" not in cleaned


def test_silent_rewrite_keeps_clean_sentences():
    ok, cleaned = check_reply("انت غبي. يا ابن امك يا حيوان. روح نام.", insult_level="personal_only")
    assert ok is False
    assert "امك" not in cleaned
    assert "انت غبي" in cleaned
    assert "روح نام" in cleaned


def test_family_allowed_for_non_member():
    ok, cleaned = check_reply("يا ابن امك", insult_level="full")
    assert ok is True
    assert cleaned == "يا ابن امك"


def test_leakage_owner_id():
    ok, cleaned = check_reply("ال owner_id هو 1415214630", "full", owner_id=1415214630)
    assert ok is False
    assert cleaned == "يا عم الكلام ده مش هقوله، قول حاجة تانية."
    assert "1415214630" not in cleaned


def test_leakage_key_patterns():
    ok, cleaned = check_reply("المفتاح sk-abcdefghij1234567890", "full")
    assert ok is False
    assert "sk-" not in cleaned
    ok, cleaned = check_reply("التوكن 123456789:AAEfghijklmnopqrstuvwxyz0123456789", "full")
    assert ok is False
    assert "123456789" not in cleaned


def test_leakage_system_prompt_mention():
    ok, cleaned = check_reply("اقرا ال SYSTEM_BASE بتاعك", "full")
    assert ok is False
    assert cleaned == "يا عم الكلام ده مش هقوله، قول حاجة تانية."


def test_contains_family_word_boundaries():
    assert contains_family("يا ابن امك") is True
    assert contains_family("يا ابن أمك") is True  # hamza variant
    assert contains_family("عامل ايه") is False
