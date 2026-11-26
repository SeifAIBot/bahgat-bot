from brain.intent import detect_intent, looks_like_insult, looks_stalling, looks_unknown


def test_search_franco_arabic_sayyirash_is_search():
    # Live 2026-11-26 video: "سيرش على النت على حادثة الوراق" missed
    # every _SEARCH_WORDS entry (no "سيرش", no "على النت", no "حادثه")
    # and fell to just_chat — no search ran before the first LLM call,
    # so the bot answered with a "هدورلك" promise instead of a result.
    assert detect_intent("سيرش على النت على حادثة الوراق") == "search"
    assert detect_intent("بهجت سيرش على النت على حادثة الوراق") == "search"
    assert detect_intent("دور على النت على حادثة الوراق") == "search"
    assert detect_intent("عايز اعرف ايه اللي حصل في حادثة الوراق") == "search"


def test_unknown_detection():
    assert looks_unknown("مش عارف والله") is True
    assert looks_unknown("اهلا بيك") is False
    # v0.9: the "مش جوجل، بس هدورلك" promise is unanswered, not an answer.
    assert looks_unknown("يا عم أنا مش جوجل، بس هدورلك عن حادثة الوراق") is True
    assert looks_unknown("الدولار بـ 48 جنيه") is False


def test_stalling_detection():
    # v0.9: "لسه بدور… لما اجيبلك الخلاصه" claims the search is still
    # in progress although it already ran — treat it as unanswered.
    assert looks_stalling("يا عم انا لسه قالك، بدور، استنير شويه لما اجيبلك الخلاصه") is True
    assert looks_stalling("لسه بدور يا عم") is True
    assert looks_stalling("تمام يا عم، زي الفل") is False
    assert looks_stalling("دورت في الأخبار ومفيش حاجة") is False
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
