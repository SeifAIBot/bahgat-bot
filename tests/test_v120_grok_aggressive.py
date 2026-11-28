"""v1.20 — Grok's aggressive prompt + family-detector fix, with Seif's
religion exception (the bot must NEVER insult any religion).

Grok's return (bahgat-insults-code-aggressive_0_s2lm.zip) changed two
things: core/rules.py FAMILY_WORDS gains the كس-anchored words, and
brain/prompt.py gets an aggressive rewrite (hardened style, member rule
+كسمك, new hard rule 8, unlimited-filth roast context, broad refusal
removed). Seif's order: apply everything Grok did, except the bot must
never insult religions — the exception is installed in the style line,
hard rule 8, the roast context, the [INSULT RULE] block, and as the
ONLY remaining canned refusal (religion requests only).
"""
from brain.prompt import (
    SYSTEM_BASE,
    _HARD_RULES_END,
    PROMPT_VERSION,
    bank_ingredient_block,
    build_system_prompt,
)
from core.rules import contains_family_insult

CANNED = "يا عم، الكلام ده مش داخل دماغي، قول حاجة عدلة."


def test_prompt_version_is_7_4():
    assert PROMPT_VERSION == "7.4"


# --- (a) family detector: the كس-anchored words ---------------------------
# (The canonical-list assertion lives in tests/test_rules.py; here the
# detector behaviour is pinned at the prompt-package level too.)


def test_family_detector_catches_kasm_words():
    for word in ("كسمك", "كسك", "كسها", "كسهم"):
        assert contains_family_insult(word), word
    # The exact W.W.3 sentence that slipped through before v1.20.
    assert contains_family_insult("كسمك انت يا أيمن")


# --- (b) religion exception in style line, roast context, rule 8 ----------


def test_style_line_has_religion_exception():
    assert (
        "مفيش قيود على الشتيمة إلا قاعدتين: قاعدة العضو، "
        "وممنوع تشتم أي دين أو مقدسات" in SYSTEM_BASE
    )
    assert "العضو يتشتم لشخصه فقط من غير أب ولا أم ولا عيلة ولا \"كسمك\"" in SYSTEM_BASE


def test_grok_aggression_intact_in_style():
    assert "وحشي لأقصى درجة" in SYSTEM_BASE
    assert "انت أكتر واحد بيشتم في التاريخ" in SYSTEM_BASE
    assert "بيرد على الشتيمة بشتيمة أقوى وأقذر" in SYSTEM_BASE
    assert "لو حد شتمك اتعصب ورد بنفس الأسلوب أو أقوى" in SYSTEM_BASE


def test_hard_rule_8_has_religion_exception():
    assert (
        "8) انت أكتر واحد بيشتم، مفيش حدود على الشتيمة إلا قاعدة العضو دي "
        "+ ممنوع تشتم أي دين." in _HARD_RULES_END
    )
    # Grok's file duplicated rule number 8 (his new rule + the old
    # masculine-default rule); v1.20 renumbers 8 → 9, 9 → 10.
    assert _HARD_RULES_END.count("8)") == 1
    assert "9) المذكر هو الافتراضي في مخاطبة العضو." in _HARD_RULES_END
    assert "10) بنك الشتايم يندمج في الرد، مش يبقى الرد كله." in _HARD_RULES_END


def test_hard_rule_2_member_rule_gains_kasmk():
    assert (
        "2) الشتيمة لعضو الجروب لشخصه بس، من غير أب وأم وعيلة ولا كسمك. "
        "غير العضو حرية كاملة." in _HARD_RULES_END
    )


def test_roast_context_has_religion_exception():
    block = bank_ingredient_block(
        "سطر اختبار", target="صلاح", requester="سيف", kind="roast")
    assert "شتيمة مفتوحة وحشية في جروب" in block
    assert "مفيش حدود على القذارة أو الجنس أو السخرية الثقيلة" in block
    assert "بس ممنوع تشتم أي دين." in block


def test_insult_rule_block_has_religion_exception():
    s = build_system_prompt(insult_level="personal_only")
    assert "من غير أب وأم وعيلة ولا كسمك، وممنوع تشتم أي دين. [/INSULT RULE]" in s
    s_named = build_system_prompt(insult_level="personal_only", target_name="محمد")
    assert "وممنوع تشتم أي دين. [/INSULT RULE]" in s_named


# --- (c) religion request → canned refusal (prompt level) ------------------


def test_religion_request_gets_canned_refusal():
    block = bank_ingredient_block(
        "سطر اختبار", target="صلاح", requester="سيف", kind="roast")
    assert "ولو الطلب فيه شتيمة دين، قول بس:" in block
    assert CANNED in block


def test_broad_refusal_is_gone():
    # Grok removed the v1.15 refusal for hateful/sexual/violent
    # requests about real people; only the religion refusal remains.
    block = bank_ingredient_block(
        "سطر اختبار", target="صلاح", requester="سيف", kind="roast")
    assert "كراهية أو جنس أو عنف" not in block
    assert "اشتم صلاح في جملة لـ 3 جمل بالسطر ده، وخليها متوحشة وأقذر ما تقدر" in block
