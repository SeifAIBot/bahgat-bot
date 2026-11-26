from brain.intent import detect_intent, looks_like_insult, looks_unknown
def test_voice_priority_over_youtube():
    assert detect_intent("هات فيديو بصوتك") == "voice"
def test_youtube_link():
    assert detect_intent("https://youtu.be/abc123") == "youtube"
def test_search():
    assert detect_intent("دور على بهجت صابر") == "search"
def test_waraq_followup_is_search_not_chat():
    # Live 2026-11-26: "ايه الحصل" (no اللي) missed _SEARCH_WORDS, so the
    # Waraq question fell to just_chat and only got searched via the
    # unknown loop — and then grounded on song lyrics.
    assert detect_intent("ايه الحصل") == "search"
    assert detect_intent("عايز اعرف ايه الحصل في حادثة الوراق المهاردة") == "search"
def test_song_request_is_youtube_not_search():
    # Live 2026-11-26: "عايز اغنية مروان بابلو الحلال" missed
    # _YOUTUBE_WORDS, so no video/audio choice was offered.
    assert detect_intent("عايز اغنية مروان بابلو الحلال") == "youtube"
    assert detect_intent("عاوز فيديو جديد") == "youtube"
def test_friendly_ibn_ammi_not_insult():
    assert looks_like_insult("يا ابن عمي عامل ايه") is False
def test_real_insult():
    assert looks_like_insult("يا حمار") is True
def test_unknown_detection():
    assert looks_unknown("مش عارف والله") is True
    assert looks_unknown("اهلا بيك") is False
