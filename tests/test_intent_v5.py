from brain.intent import (
    detect_intent, looks_like_insult, looks_like_praise, looks_unknown,
    extract_insult_target, normalize_arabic,
)


def test_normalisation_hamza_insensitive():
    assert normalize_arabic("أغنية") == normalize_arabic("اغنية")
    assert normalize_arabic("النتيجة") == "النتيجه"


def test_youtube_hamza_less_song():
    assert detect_intent("شغل اغنية ويجز الجديدة") == "youtube"


def test_youtube_hatli():
    assert detect_intent("هاتلي اغنية لعمرو دياب") == "youtube"


def test_search_match_winner():
    assert detect_intent("مين كسب ماتش الاهلي امبارح") == "search"


def test_search_dollar_price():
    assert detect_intent("كام سعر الدولار") == "search"


def test_insult_anta_hmar():
    assert looks_like_insult("يا بهجت انت حمار") is True
    assert looks_like_insult("انت غبي") is True


def test_friendly_ibn_ammi_not_insult():
    assert looks_like_insult("يا ابن عمي") is False


def test_praise():
    assert looks_like_praise("انت جامد يا بهجت") is True
    assert looks_like_praise("شكرا يا بهجت") is True
    assert looks_like_praise("عامل ايه") is False


def test_unknown_markers_widened():
    assert looks_unknown("معرفش والله") is True
    assert looks_unknown("ماعنديش فكرة") is True
    assert looks_unknown("مش فاكر") is True
    assert looks_unknown("اهلا بيك") is False


def test_extract_insult_target():
    assert extract_insult_target("اشتم محمد") == "محمد"
    assert extract_insult_target("اشتم @mohamed") == "mohamed"
    assert extract_insult_target("يا بهجت اشتمي احمد") == "احمد"
    assert extract_insult_target("اشتم") is None
    assert extract_insult_target("عامل ايه يا بهجت") is None
