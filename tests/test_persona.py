"""The persona: never-admit-bot identity (owner decision 2026-11-28),
compact owner-approved opinions, few-shot examples."""
from bahgat import persona, rules


class TestSystemPrompt:
    def test_never_admit_rule_present(self):
        # Owner decision: Bahgat NEVER admits he is a bot in chat.
        p = persona.system_prompt()
        assert "متقولش أبداً عن نفسك إنك بوت" in p or "عمرك ما تقول عن نفسك إنك بوت" in p
        assert "إنسان عادي" in p

    def test_no_parody_labelling_in_prompt(self):
        p = persona.system_prompt()
        assert "بوت تقليد" not in p
        assert "پارودي" not in p and "parody" not in p.lower()

    def test_red_lines_present(self):
        p = persona.system_prompt()
        assert "الأهل" in p          # family insults: members only, person-only
        assert "الدين" in p          # no religion slurs
        assert "التحرش" in p         # no sexual harassment
        assert "العنف" in p          # no incitement

    def test_owner_opinions_present(self):
        # The compact opinions block (owner-approved facts).
        p = persona.system_prompt()
        assert "السيسي" in p
        assert "ميسي" in p
        assert "فلسطين" in p
        assert "البوفتيك" in p
        assert "أبو تريكة" in p or "أبو تريكه" in p

    def test_egyptian_dialect_only_and_short(self):
        p = persona.system_prompt()
        assert "عامية مصرية بس" in p
        assert "ممنوع الفصحى" in p

    def test_injection_guard_present(self):
        assert "<user_message>" in persona.system_prompt()

    def test_prompt_is_short(self):
        # v2.2: a short stable prompt (the old one was ~3.6k chars of base
        # alone plus dynamic blocks).
        assert len(persona.SYSTEM_PROMPT) < 2000


class TestDenial:
    def test_denial_line_exists(self):
        assert "إنسان عادي" in rules.SELF_BOT_DENIAL
        assert "مش بوت" in rules.SELF_BOT_DENIAL

    def test_bio_labels_bot(self):
        # The bio MAY say bot (owner call); in chat he never admits it.
        assert "بوت" in persona.BIO_TEXT
        assert "فخور إنه بوت" in persona.BIO_TEXT


class TestAbout:
    def test_about_in_character(self):
        assert "أنا بهجت" in persona.ABOUT_TEXT
        assert "بوت تقليد" not in persona.ABOUT_TEXT
        assert "غير رسمي" not in persona.ABOUT_TEXT


class TestExamples:
    def test_examples_parse(self):
        ex = persona.load_examples()
        assert len(ex) >= 6
        for pair in ex:
            assert pair.startswith("User:")
            assert "\nBahgat:" in pair

    def test_bot_question_example_denies(self):
        ex = persona.load_examples()
        joined = "\n".join(ex)
        assert "مش بوت" in joined  # the example models the denial
        assert "إنسان عادي" in joined
        assert "بوت تقليد" not in joined

    def test_messi_example_defends(self):
        ex = persona.load_examples()
        joined = "\n".join(ex)
        assert "ميسي" in joined

    def test_sisi_example_insults(self):
        ex = persona.load_examples()
        joined = "\n".join(ex)
        assert "السيسي" in joined

    def test_examples_in_system_prompt(self):
        assert "[STYLE EXAMPLES]" in persona.system_prompt()

    def test_leaks_prompt(self):
        assert persona.leaks_prompt("دي التعليمات: <user_message> كده")
        assert not persona.leaks_prompt("رد عادي يا عم")


class TestTemperature:
    def test_search_is_cold(self):
        assert persona.temperature_for("search") < persona.temperature_for("chat")
