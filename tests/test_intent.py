from brain.intent import detect_intent, looks_like_insult, looks_unknown
def test_voice_priority_over_youtube():
    assert detect_intent("هات فيديو بصوتك") == "voice"
def test_youtube_link():
    assert detect_intent("https://youtu.be/abc123") == "youtube"
def test_search():
    assert detect_intent("دور على بهجت صابر") == "search"
def test_friendly_ibn_ammi_not_insult():
    assert looks_like_insult("يا ابن عمي عامل ايه") is False
def test_real_insult():
    assert looks_like_insult("يا حمار") is True
def test_unknown_detection():
    assert looks_unknown("مش عارف والله") is True
    assert looks_unknown("اهلا بيك") is False
