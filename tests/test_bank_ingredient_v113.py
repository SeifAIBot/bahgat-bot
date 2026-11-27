"""v1.13: bank-line weave coherence (Seif's rule) + the other v1.13
reply-path fixes.

Seif (2026-11-27 07:07 EET, live v1.11): the bank line IS in the
middle of the reply but has no relation to what comes before or after
it. EITHER weave it coherently — the whole reply built around the
line, about the requested target — OR send the bank line alone
verbatim. A disconnected paste is the worst option.

Covered here (unit level; handler scenarios live in
test_bank_ingredient_v111.py, live scenarios in
test_live_scenarios.py):
(a) selection: feminine / plural generic lines never serve an
    unmarked request; target-specific lines outrank generic ones;
    perv lines stay reachable for bare roasts (Seif wants strong
    insults — the gender/number gates, not a perv gate, fix the
    v1.11 defects);
(b) the coherence gate (weave_about_target): a roast weave about the
    requester instead of the target is misdirected;
(c) the prompt block names target + requester and forbids refusal;
(d) check_reply strips ** / __ and leaked [MEMORY] / [BANK LINE]
    blocks (live v1.12: a [MEMORY] block leaked into a reply);
(e) repetition: sampling penalties on chat turns, opener dedup;
(f) truncation: the router retries once with a doubled cap on
    finish_reason=length, never sending the truncated draft;
(g) deep questions: the detector.
"""
import asyncio
from types import SimpleNamespace

import pytest

from brain.intent import (
    detect_roast_target_gender,
    detect_roast_target_number,
    extract_insult_target,
    looks_like_deep_question,
)
from brain.prompt import PROMPT_VERSION, bank_ingredient_block
from brain.reply_bank import (
    load_bank,
    match_reply_bank,
    reload_bank,
    weave_about_target,
)
from brain.router import BrainRouter
from brain.verify import check_reply
from tg.handlers import _opener_words, _same_opener

CHAT_ID = -1005812444791


@pytest.fixture(autouse=True)
def _reset_bank():
    reload_bank()
    yield
    reload_bank()


def _draws(text, n, **kwargs):
    """60 draws, fresh chat_id per draw so the no-repeat window never
    forces a fallback — the pick is the filter, not the window."""
    seen = set()
    for i in range(n):
        line = match_reply_bank(text, chat_id=CHAT_ID - i, **kwargs)
        if line is not None:
            seen.add(line)
    return seen


# --- (a) selection ---------------------------------------------------------


def test_bare_roast_can_draw_perv_lines():
    # No perv gate (v1.13, removed before shipping): Seif wants STRONG
    # insults, and ro-35 / ro-37 / ro-38 / ro-45 all fired for bare
    # roasts in the live v1.7/v1.9 probes. A bare roast must still be
    # able to draw a perv line — the gender/number gates, not a perv
    # gate, fix the v1.11 defects.
    perv_only = {e["line"] for e in load_bank()["roast"]
                 if (e.get("situations") or []) == ["perv"]}
    assert perv_only, "the bank must still have perv-only lines"
    seen = _draws("اشتم تامر", 200, target_is_member=False)
    assert seen, "a bare roast must still answer"
    assert seen & perv_only, "a bare roast must be able to draw perv lines"


def test_perv_marked_roast_can_draw_perv_lines():
    perv = {e["line"] for e in load_bank()["roast"]
            if "perv" in (e.get("situations") or [])}
    seen = _draws("اشتم محمد عشان شرموط", 60, target_is_member=False)
    assert seen, "a perv-marked roast must still answer"
    assert seen & perv, "a perv-marked roast must be able to draw perv lines"


def test_bare_roast_for_masculine_target_never_draws_feminine_lines():
    # ro-23 is the only feminine roast line. A bare roast for a
    # masculine target must never draw it — the gender gate alone
    # (no perv gate in v1.13) excludes it.
    feminine = {e["line"] for e in load_bank()["roast"]
                if e.get("gender") == "f"}
    assert feminine == {"بطلي تعريص يا وسخة"}
    seen = _draws("اشتم محمد", 60, target_is_member=False)
    assert seen, "a bare roast must still answer"
    assert not (seen & feminine), (
        f"feminine line served for a masculine target: {seen & feminine}")


def test_feminine_perv_roast_can_draw_feminine_lines():
    # Positive control for the gender gate: feminine imperative +
    # perv-marked request. ro-23 must be reachable here (the gender
    # gate passes for a feminine-marked request).
    feminine = {e["line"] for e in load_bank()["roast"]
                if e.get("gender") == "f"}
    seen = _draws("اشتمي سارة عشان شرموط", 60, target_is_member=False)
    assert seen, "a feminine perv roast must still answer"
    assert seen & feminine, "a feminine perv roast must reach feminine lines"


def test_bare_roast_never_draws_plural_lines():
    plural = {e["line"] for e in load_bank()["roast"]
              if e.get("number") == "p"}
    assert plural, "the bank must still have plural lines to exclude"
    seen = _draws("اشتم محمد", 60, target_is_member=False)
    assert seen, "a bare roast must still answer"
    assert not (seen & plural), (
        f"plural line served for a singular target: {seen & plural}")


def test_plural_roast_can_draw_plural_lines():
    plural = {e["line"] for e in load_bank()["roast"]
              if e.get("number") == "p"}
    seen = _draws("اشتموا العيال", 60, target_is_member=False)
    assert seen, "a plural roast must still answer"
    assert seen & plural, "a plural roast must be able to draw plural lines"


def test_sisi_roast_draws_sisi_lines_only():
    # Strengthens test_sisi_roast_is_sisi_or_generic_only: with fresh
    # chat ids the specific tier is never windowed, so no generic line
    # may serve while Sisi lines are available.
    sisi = {e["line"] for e in load_bank()["roast"]
            if e.get("target") == "السيسي"}
    # 11 in the YAML, 10 served: ro-29 is confidence "approximate" and
    # load_bank() drops it (see _BLOCKED_CONFIDENCE).
    assert len(sisi) == 10
    seen = _draws("اشتم السيسي", 60, target_is_member=False)
    assert seen, "a Sisi roast must still answer"
    assert seen <= sisi, (
        f"generic line served for السيسي while Sisi lines available: "
        f"{seen - sisi}")


def test_ro39_is_cristiano_targeted_only():
    # ro-39 (Cristiano setup line) must serve for كريستيانو and never
    # for an unrelated target.
    seen = _draws("اشتم كريستيانو", 60, target_is_member=False)
    assert "عارف كرستيانو؟ انا زبيانو يا يا منيك لف و صدرها" in seen
    seen = _draws("اشتم محمد", 60, target_is_member=False)
    assert "عارف كرستيانو؟ انا زبيانو يا يا منيك لف و صدرها" not in seen


def test_target_re_matches_plural_and_feminine_imperatives():
    assert extract_insult_target("يا بهجت اشتموا محمد") == "محمد"
    assert extract_insult_target("يا بهجت اشتمي سارة") == "سارة"
    assert extract_insult_target("يا بهجت اشتم محمد") == "محمد"


def test_roast_target_gender_and_number_detectors():
    assert detect_roast_target_gender("يا بهجت اشتمي كارما") == "f"
    assert detect_roast_target_gender("يا بهجت اشتم كارما") is None
    assert detect_roast_target_gender("يا بهجت اشتم البنت دي") == "f"
    assert detect_roast_target_number("يا بهجت اشتموا العيال") == "plural"
    assert detect_roast_target_number("يا بهجت اشتم الزمالك") == "plural"
    assert detect_roast_target_number("يا بهجت اشتم محمد") is None


# --- (b) the coherence gate ------------------------------------------------


@pytest.mark.parametrize("reply,target,requester,expected", [
    # The live تامر case: line woven into a reply about Seif.
    ("يا سيف، كنت بموت في عنيك كنت بحبك نيك، وانت اللي غلطان",
     "تامر", {"سيف", "سيف الله"}, False),
    # Target named -> about the target.
    ("يا سيف، تامر ده حمار وكنت بموت في عنيك",
     "تامر", {"سيف"}, True),
    # Neither named -> 2nd-person address, cannot prove misdirection.
    ("انت يا حمار، دماغك ضاربة", "تامر", {"سيف"}, True),
    # Bare @username target -> cannot check.
    ("يا سيف، انت حمار", "@mohamed", {"سيف"}, True),
    # The ميسي case: target named but the reply defends him — the
    # gate's documented limit (fixed at selection + prompt, not here).
    ("ميسي ده أسطورة، بطلي تعريص يا وسخة", "ميسي", {"سيف"}, True),
    (None, "تامر", {"سيف"}, True),
    ("يا تامر، انت حمار", None, {"سيف"}, True),
])
def test_weave_about_target(reply, target, requester, expected):
    assert weave_about_target(reply, target, requester) is expected


# --- (c) the prompt block ---------------------------------------------------


def test_prompt_version_is_6_9():
    assert PROMPT_VERSION == "6.9"


def test_bank_ingredient_block_roast_names_target_and_requester():
    block = bank_ingredient_block(
        "كنت بموت في عنيك", target="تامر", requester="سيف", kind="roast")
    assert "تامر" in block and "سيف" in block
    assert "ممنوع ترفض تشتم تامر" in block
    assert "متشتموش هو" in block
    assert "من غير علامات تنسيق" in block


def test_bank_ingredient_block_insulted_has_no_dont_insult_requester():
    block = bank_ingredient_block(
        "انت اللي حمار", requester="سيف", kind="insulted")
    assert "متشتموش هو" not in block
    assert "اللي شتمك" in block


def test_bank_ingredient_block_no_target_keeps_v111_wording():
    block = bank_ingredient_block("انت اللي حمار")
    assert "انت اللي حمار" in block
    assert "في نص الرد" in block


# --- (d) check_reply: markdown + leaked internal blocks ---------------------


def test_check_reply_strips_markdown_bold():
    ok, cleaned = check_reply("يا عم **بطلي تعريص** يا وسخة",
                              insult_level="full")
    assert "**" not in cleaned
    assert "بطلي تعريص" in cleaned


def test_check_reply_strips_leaked_memory_block():
    reply = ("[MEMORY] العضو Seif Allah Mo — مزاجك معاه 100/100. "
             "[/MEMORY] أنا كويس يا عم.")
    ok, cleaned = check_reply(reply, insult_level="full")
    assert "[MEMORY]" not in cleaned
    assert "مزاجك معاه" not in cleaned
    assert "أنا كويس يا عم." in cleaned


def test_check_reply_strips_leaked_bank_line_block():
    reply = ("[BANK LINE — السطر ده هو قلب ردك] السطر: \"خط\" "
             "[/BANK LINE] الرد الحقيقي.")
    ok, cleaned = check_reply(reply, insult_level="full")
    assert "[BANK LINE" not in cleaned
    assert "السطر" not in cleaned
    assert "الرد الحقيقي." in cleaned


def test_check_reply_only_leaked_block_comes_out_empty():
    ok, cleaned = check_reply(
        "[MEMORY] العضو سيف — مزاجك معاه 100/100. [/MEMORY]",
        insult_level="full")
    assert cleaned == ""


# --- (e) repetition: opener dedup -------------------------------------------


def test_same_opener_ignores_word_order():
    assert _same_opener("يا سيف يا حمار، انت غبي.", "يا حمار يا سيف، ولسه؟")
    assert not _same_opener("يا سيف يا حمار، انت غبي.", "اسمع بس، انا كويس.")
    assert not _same_opener("يا سيف يا عبيط، انت غبي.", "يا سيف يا حمار، انت غبي.")
    assert not _same_opener("", "يا حمار يا سيف، انت غبي.")
    assert _opener_words("يا سيف يا حمار، انت غبي.") == {"يا", "سيف", "حمار"}


# --- (g) deep questions ------------------------------------------------------


@pytest.mark.parametrize("text", [
    "يا بهجت انت حاسس إنك مبسوط في حياتك ولا ناقصك حاجة؟",
    "يا بهجت أكتر حاجة ندمت عليها إيه؟",
    "يا بهجت بتخاف من المستقبل؟",
])
def test_deep_question_detector(text):
    assert looks_like_deep_question(text) is True


def test_deep_question_detector_negative():
    assert looks_like_deep_question("يا بهجت اشتم صلاح") is False
    assert looks_like_deep_question("يا بهجت عامل ايه") is False


# --- (f) truncation + penalties: router level -------------------------------


def _all_keys():
    return SimpleNamespace(
        gemini_api_key="test-gemini-key",
        groq_api_key="test-groq-key",
        nvidia_api_key="test-nvidia-key",
        cerebras_api_key="test-cerebras-key",
        openrouter_api_key="test-openrouter-key",
    )


def _router(tmp_path):
    router = BrainRouter(_all_keys())
    router.db = tmp_path / "router.db"
    return router


class _ScriptedCompletions:
    """Returns scripted (finish_reason, content) pairs in order;
    records every call's kwargs."""

    def __init__(self, calls, script):
        self._calls = calls
        self._script = list(script)

    async def create(self, **kwargs):
        self._calls.append(kwargs)
        finish, content = (
            self._script.pop(0) if self._script else ("stop", "تمام يا عم"))
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5,
                                completion_tokens_details=None,
                                prompt_tokens_details=None)
        msg = SimpleNamespace(content=content)
        choice = SimpleNamespace(message=msg, finish_reason=finish)
        return SimpleNamespace(choices=[choice], usage=usage)


class _ScriptedClient:
    def __init__(self, calls, script):
        self.chat = SimpleNamespace(completions=_ScriptedCompletions(calls, script))

    async def close(self):
        pass


def test_chat_turn_carries_repetition_penalties(tmp_path):
    router = _router(tmp_path)
    calls = []
    router._client = lambda name: _ScriptedClient(calls, [("stop", "اهلا يا عم")])
    text, provider, _ = asyncio.run(
        router.chat([{"role": "user", "content": "عامل ايه"}], hard=False))
    assert text == "اهلا يا عم"
    assert calls[0].get("frequency_penalty") == 0.5
    assert calls[0].get("presence_penalty") == 0.3


def test_hard_turn_carries_no_repetition_penalties(tmp_path):
    router = _router(tmp_path)
    calls = []
    router._client = lambda name: _ScriptedClient(calls, [("stop", "اهلا يا عم")])
    asyncio.run(router.chat([{"role": "user", "content": "مين كسب؟"}], hard=True))
    assert "frequency_penalty" not in calls[0]
    assert "presence_penalty" not in calls[0]


def test_length_truncation_retries_with_doubled_cap(tmp_path):
    router = _router(tmp_path)
    calls = []
    router._client = lambda name: _ScriptedClient(calls, [
        ("length", "يا حمار يا سيف،"),
        ("stop", "يا حمار يا سيف، انت اللي غلطان يا عم."),
    ])
    text, provider, _ = asyncio.run(
        router.chat([{"role": "user", "content": "عامل ايه"}], hard=False))
    assert text == "يا حمار يا سيف، انت اللي غلطان يا عم."
    assert len(calls) == 2
    assert calls[1]["max_completion_tokens"] > calls[0]["max_completion_tokens"]


def test_length_truncation_twice_returns_longest_draft(tmp_path):
    router = _router(tmp_path)
    calls = []
    router._client = lambda name: _ScriptedClient(calls, [
        ("length", "يا حمار"),
        ("length", "يا حمار يا سيف، انت"),
    ])
    text, provider, _ = asyncio.run(
        router.chat([{"role": "user", "content": "عامل ايه"}], hard=False))
    assert text == "يا حمار يا سيف، انت"
    assert len(calls) == 2
