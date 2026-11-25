from core.rules import insult_level, contains_family_insult

def test_member_is_personal_only():
    assert insult_level(123, {123, 456}) == "personal_only"

def test_non_member_is_full():
    assert insult_level(999, {123, 456}) == "full"
    assert insult_level(None, {123}) == "full"
