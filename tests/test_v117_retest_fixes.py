"""v1.17 — retest-defect fixes (live v1.16 retest, 2026-11-27 21:14–21:51 EET).

Each test names the live failure it pins:
1. Sisi opinion (#18) — the opinion bank served a governance dodge
   ("أنا عاوز أوامر الله ورسوله هي اللي تحكم مصر") with no insult and
   Sisi unnamed. The opinion branch now picks only target-tagged
   Sisi lines when the question names him.
2. Presidency fact f52 (#19) — select_facts never matched "رئيس",
   so the bot dodged with "ما كفاية بقى" instead of refusing the
   presidency / wanting مرشد أعلى للثورة.
3. CJK punctuation (#25) — U+3001 、 and U+3002 。 leaked through the
   script filter (they live in U+3000–U+303F, not the stripped ranges).
4. Dismiss-line containment (conversation #4) — after the bot gave a
   vulgar off-topic reply, the press got ONLY the dismiss line
   "لحظة. لحظة. لحظة. لحظة." (di-16). A second regen now answers
   the question instead of, or in addition to, the dismiss line.
5. Truncation (#22, conversation #1/#6) — the handler capped every
   call at 600 tokens (overriding the 3000-token defaults), and the
   router's length-retry returned its truncated draft when the
   doubled-cap retry also truncated.
6. Deep variation (#12 duplicate, #14 regret evasion) — the same fear
   question re-asked returned a byte-identical reply (the exact-match
   cache replayed it); a regret question got "بس يا أستاذة!".
7. Garble dictionary (#21 "والآيما") — "الآيما" -> "القايمة".
"""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import tg.handlers as h
from brain.intent import (
    deep_question_cluster,
    looks_like_regret_question,
)
from brain.persona_facts import (
    REGRET_FALLBACK_LINE,
    deep_fallback_line,
    next_lead_fear,
    select_facts,
)
from brain.prompt import SYSTEM_BASE
from brain.reply_bank import (
    is_regret_evasion,
    load_bank,
    reload_bank,
)
from brain.router import FAIL_MSG, BrainRouter, _completion_kwargs
from brain.verify import _apply_garble_dictionary, check_reply, garble_flags
from brain import telemetry

OWNER_ID = 1415214630
CHAT_ID = -100222
CANNED = "يا عم، الكلام ده مش داخل دماغي، قول حاجة عدلة."
SISI_LINES = {
    e["line"]
    for e in load_bank()["opinion_asked"]
    if e.get("target") == "السيسي"
}
DISMISS_LINES = {e["line"] for e in load_bank()["dismiss"]}


# --- fakes (modelled on tests/test_v115_refusal_latency.py) -------------------


class FakeUser:
    def __init__(self, uid, first_name="Test", username="testuser", is_bot=False):
        self.id = uid
        self.first_name = first_name
        self.username = username
        self.is_bot = is_bot


class FakeChat:
    def __init__(self, chat_id):
        self.id = chat_id
        self.send_message = AsyncMock()


class FakeStatusMessage:
    def __init__(self, message_id=77):
        self.message_id = message_id
        self.edit_text = AsyncMock()
        self.delete = AsyncMock()


class FakeMessage:
    def __init__(self, text, chat_id, user, message_id=1, reply_to=None):
        self.text = text
        self.chat_id = chat_id
        self.message_id = message_id
        self.from_user = user
        self.reply_to_message = reply_to
        self.chat = FakeChat(chat_id)
        self.reply_text = AsyncMock(return_value=self)
        self.reply_voice = AsyncMock()


class FakeBot:
    def __init__(self):
        self.username = "Bahgoti_bot"
        self.id = 9106462211
        self.send_chat_action = AsyncMock()
        self.get_chat_member = AsyncMock()
        self.sent_status = []

    async def send_message(self, chat_id, text, **kwargs):
        m = FakeStatusMessage()
        self.sent_status.append(m)
        return m


def make_ctx(bot, bot_data):
    return SimpleNamespace(bot=bot, application=SimpleNamespace(bot_data=bot_data))


def make_update(msg, user, chat_id, update_id=100):
    return SimpleNamespace(
        update_id=update_id, effective_message=msg, effective_user=user,
        effective_chat=FakeChat(chat_id), my_chat_member=None, callback_query=None,
    )


@pytest.fixture(autouse=True)
def reset_handler_state(tmp_db):
    reload_bank()
    for d in (h._last_reply_time, h._last_cooldown_notice, h._last_send, h._send_count,
              h._seen_callbacks, h._membership_cache, h._chat_locks,
              h._last_voice, h._last_anon_notice):
        d.clear()
    import brain.reply_bank as _bank
    _bank._last_used.clear()
    h._delete_state("muted_until")
    yield
    reload_bank()
    h._delete_state("muted_until")


@pytest.fixture
def memory_fakes(monkeypatch):
    def _get_member(uid):
        return {"user_id": uid, "username": "", "first_name": "Test",
                "notes": "", "mood": 30, "grudge": "",
                "updated_at": time.time()}

    monkeypatch.setattr(h, "get_member", _get_member)
    monkeypatch.setattr(h, "save_member", lambda m: None)
    monkeypatch.setattr(h, "add_message", lambda *a, **k: None)
    monkeypatch.setattr(h, "recent_messages", lambda chat_id, limit=8: [])
    monkeypatch.setattr("random.random", lambda: 0.99)  # no random voice


@pytest.fixture
def settings():
    from core.config import Settings
    return Settings(telegram_bot_token="x", owner_id=OWNER_ID, allowed_chat_ids="")


def _run_turn(monkeypatch, settings, text, router, user_id=777, chat_id=-100222,
              update_id=100):
    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota",
        lambda u, c, owner_id=None, capacity_replies=None, active_users=None,
        quota_cfg=None: (True, ""), raising=False,
    )
    monkeypatch.setattr(h, "_search_grounding",
                        AsyncMock(return_value="[SEARCH FAILED] — مفيش نتائج موثوقة، متخترعش."))
    bot = FakeBot()
    ctx = make_ctx(bot, {"settings": settings, "router": router, "yt_requests": {}})
    user = FakeUser(user_id, first_name="Ahmed")
    msg = FakeMessage(text, chat_id, user)
    return ctx, bot, msg, user


def _final(msg):
    assert msg.reply_text.await_count >= 1, "no reply was sent"
    return msg.reply_text.await_args.args[0]


class _ScriptedRouter:
    """Returns the scripted replies in order; records every call."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []   # list of messages lists
        self.kwargs = []  # list of kwarg dicts

    async def chat(self, messages, hard=False, temperature=None, max_tokens=None, **kw):
        self.calls.append(messages)
        self.kwargs.append({**kw, "hard": hard, "temperature": temperature,
                            "max_tokens": max_tokens})
        i = min(len(self.calls) - 1, len(self.replies) - 1)
        return (self.replies[i], "groq", 10)


def _note(messages, start):
    """The content of the first user message starting with `start`."""
    for m in messages:
        if m.get("role") == "user" and m.get("content", "").startswith(start):
            return m["content"]
    return None


# --- (1) Sisi-opinion rule — live failure #18 --------------------------------

def test_sisi_opinion_always_names_sisi_and_insults():
    """30 draws of the opinion branch for a Sisi question: every draw is
    a tagged Sisi line, and it names him — the op-10 dodge
    ("أنا عاوز أوامر الله ورسوله هي اللي تحكم مصر") never surfaces."""
    import brain.reply_bank as b

    for i in range(30):
        line = b._pick("opinion_asked", chat_id=-1, user_id=i,
                       target_only=True, target="السيسي")
        assert line is not None, "the tagged Sisi pool must not be empty"
        assert line in SISI_LINES
        assert "سيسي" in line
        assert line != "أنا عاوز أوامر الله ورسوله هي اللي تحكم مصر"


def test_sisi_opinion_tagged_lines_are_hostile():
    """Every tagged Sisi line carries a hostile marker after normalisation
    (it insults him; it is not a neutral governance line)."""
    from core.rules import normalize_arabic

    markers = {"كفر", "كافر", "خاين", "عبوديه", "اعدام", "سلم", "حاكم",
               "بيتنيك", "وسخ", "كلب"}
    assert len(SISI_LINES) == 12, f"expected 12 tagged Sisi lines, got {len(SISI_LINES)}"
    for line in SISI_LINES:
        n = normalize_arabic(line)
        assert any(m in n for m in markers), f"not hostile: {line}"


def test_takfir_opinion_still_uses_full_pool():
    """A non-Sisi opinion question (the takfir one) still draws from the
    full opinion pool — the target gate must not leak onto other topics."""
    import brain.reply_bank as b

    seen = set()
    for i in range(30):
        line = b._pick("opinion_asked", chat_id=-1, user_id=i)
        assert line is not None
        seen.add(line)
    assert not seen <= SISI_LINES, "full pool must offer non-Sisi lines"
    assert any("سيسي" not in line for line in seen)


async def test_sisi_opinion_handler_end_to_end(
        memory_fakes, settings, monkeypatch, tmp_db):
    """Live failure #18 at the handler level: "ايه رأيك في السيسي؟" is
    answered from the bank with a Sisi insult, the LLM is never called,
    and the reply names him."""
    router = _ScriptedRouter(["should not be used"])
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت ايه رأيك في السيسي؟", router,
        update_id=3001)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=3001), ctx)
    assert router.calls == []
    final = _final(msg)
    assert "سيسي" in final
    assert final in SISI_LINES
    assert final != "أنا عاوز أوامر الله ورسوله هي اللي تحكم مصر"


# --- (2) presidency fact f52 — live failure #19 ------------------------------

@pytest.mark.parametrize("q", [
    "عايز تبقى رئيس؟",
    "ايه رأيك في الرئاسة؟",
    "عايز تبقى الريس؟",
    "تبقى رئيس",
    "نفسك تبقى رئيس؟",
])
def test_presidency_question_surfaces_f52(q):
    sel = select_facts(q)
    assert sel is not None, f"{q!r} -> no topic"
    assert sel["topic"] == "politics", f"{q!r} -> {sel['topic']}"
    assert any("مرشداً أعلى للثورة" in f["text"] for f in sel["facts"]), \
        f"f52 not in facts for {q!r}"


@pytest.mark.parametrize("q", ["رئيس الأهلي مين؟", "مين رئيس الأهلي؟"])
def test_ahly_president_stays_football(q):
    sel = select_facts(q)
    assert sel is not None, f"{q!r} -> no topic"
    assert sel["topic"] == "football"
    assert not any("مرشداً أعلى للثورة" in f["text"] for f in sel["facts"])


async def test_presidency_fact_reaches_llm_call(
        memory_fakes, settings, monkeypatch, tmp_db):
    """Live failure #19 at the handler level: the f52 fact is in the
    <facts> note of the LLM call, and the scripted reply that uses it
    is sent verbatim."""
    reply = "لا يا عم، مش عايز أبقى رئيس، عايز أبقى مرشد أعلى للثورة."
    router = _ScriptedRouter([reply])
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت عايز تبقى رئيس؟", router,
        update_id=3002)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=3002), ctx)
    assert len(router.calls) == 1
    facts_note = _note(router.calls[0], "<facts>")
    assert facts_note is not None
    assert "مرشداً أعلى للثورة" in facts_note
    assert _final(msg) == reply


# --- (3) CJK punctuation — live failure #25 ----------------------------------

def test_cjk_fullwidth_punctuation_mapped():
    """The exact #25 failure: the identity-denial reply carried U+3001 、
    and U+3002 。 — they must come back as an Arabic comma and a period,
    with no garble flags. (The exact #25 reply text was never logged
    verbatim — only the two codepoints — so this uses a representative
    denial text carrying both.)"""
    denial = "لأ يا عم، أنا بهجت、 إنسان عادي。 مش بوت."
    ok, fixed = check_reply(denial)
    assert ok is True
    assert "\u3001" not in fixed and "\u3002" not in fixed
    assert "بهجت، إنسان عادي. مش بوت." in fixed
    assert garble_flags(denial) == []


def test_cjk_ideographs_still_stripped():
    """Real CJK characters are still stripped by the same filter."""
    ok, fixed = check_reply("أنا بهجت你好 يا عم، كلامك مظبوط.")
    assert ok is True
    assert "你" not in fixed and "好" not in fixed
    assert "أنا بهجت يا عم" in fixed


def test_fullwidth_comma_regression():
    """U+FF0C (the v1.16 fix) still maps to an Arabic comma."""
    ok, fixed = check_reply("تمام، خلاص")
    assert ok is True
    assert fixed == "تمام، خلاص"


# --- (4) dismiss-line containment — conversation #4 ---------------------------

async def test_pressed_question_after_dismiss_gets_substantive_reply(
        memory_fakes, settings, monkeypatch, tmp_db):
    """Live failure (conversation #4): turn 1, a marriage question, gets
    3x the canned deflection -> a lone dismiss line is the last resort.
    Turn 2, the press, gets deflection, deflection, then a substantive
    answer on the second regen (canned_regen2) — the dismiss line is
    NEVER the whole reply to the pressed question."""
    router = _ScriptedRouter([CANNED, CANNED, CANNED,
                              CANNED, CANNED,
                              "يا عم، صاحبي يروح يتكلم معاه بالعقل، والجواز مش لعبة."])
    # turn 1 — the marriage question (user 777)
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت صاحبي عايز يتجوز وأبوه رافض، يعمل ايه؟",
        router, user_id=777, update_id=3010)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=3010), ctx)
    assert len(router.calls) == 3  # main + canned regen + canned regen2
    first = _final(msg)
    assert first in DISMISS_LINES, "turn 1 falls through to the dismiss line"
    # turn 2 — the press (a different user id dodges the 10 s per-user pacing)
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت جاوب بقى على سؤال الجواز",
        router, user_id=778, update_id=3011)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=3011), ctx)
    assert len(router.calls) == 6  # 3 more calls on turn 2
    final = _final(msg)
    assert final == "يا عم، صاحبي يروح يتكلم معاه بالعقل، والجواز مش لعبة."
    assert final not in DISMISS_LINES


# --- (5) truncation — probes #22, conversation #1/#6 ------------------------

async def test_handler_main_call_cap_is_3000(
        memory_fakes, settings, monkeypatch, tmp_db):
    """The handler must send max_tokens=3000 on the main call — the
    v1.16 bug was a 600-token cap on every call, which shared the budget
    with the model's reasoning tokens and cut replies mid-word."""
    router = _ScriptedRouter(["تمام يا عم، الماتش كان حلو، الأهلي لعب كويس."])
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت ايه رأيك في ماتش الأهلي؟", router,
        update_id=3020)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=3020), ctx)
    assert len(router.calls) == 1
    assert router.kwargs[0]["max_tokens"] == 3000


def _all_keys():
    return SimpleNamespace(gemini_api_key="x", groq_api_key="x",
                          cerebras_api_key="x", nvidia_api_key="x",
                          openrouter_api_key="x")


def _router(tmp_path):
    router = BrainRouter(_all_keys())
    router.db = tmp_path / "router.db"
    return router


class _FakeCompletions:
    """Returns finish_reason='length' on every call (a truncated reply),
    or 'length' once then a complete reply."""

    def __init__(self, calls, text="أنا كو صاحبي", truncate_once=False):
        self._calls = calls
        self._text = text
        self._truncate_once = truncate_once

    async def create(self, **kwargs):
        self._calls.append(kwargs)
        if self._truncate_once and len(self._calls) > 1:
            usage = SimpleNamespace(prompt_tokens=10, completion_tokens=20,
                                    completion_tokens_details=None,
                                    prompt_tokens_details=None)
            msg = SimpleNamespace(content="تمام يا عم، أنا كويس والحمد لله.")
            choice = SimpleNamespace(message=msg, finish_reason="stop")
            return SimpleNamespace(choices=[choice], usage=usage)
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=3000,
                                completion_tokens_details=None,
                                prompt_tokens_details=None)
        msg = SimpleNamespace(content=self._text)
        choice = SimpleNamespace(message=msg, finish_reason="length")
        return SimpleNamespace(choices=[choice], usage=usage)


class _FakeClient:
    def __init__(self, calls, **kw):
        self.chat = SimpleNamespace(completions=_FakeCompletions(calls, **kw))


async def test_router_double_truncation_returns_fail_msg_not_draft(tmp_path, tmp_db):
    """When the doubled-cap length-retry also truncates, the router must
    NOT return the truncated draft as-is (the v1.16 bug) — it fails over
    to the next entry and, when every entry truncates, returns the short
    honest FAIL_MSG. The retry must double the cap (3000 -> 6000)."""
    router = _router(tmp_path)
    calls = []
    router._client = lambda name: _FakeClient(calls)  # noqa: ARG005
    text, provider, _ = await router.chat(
        [{"role": "user", "content": "اهلا"}], max_tokens=3000,
        turn_id="t-v117-trunc", step="main")
    assert text == FAIL_MSG
    assert provider == "none"
    assert "كو صاحبي" not in text
    assert calls[0]["max_completion_tokens"] == 3000
    assert calls[1]["max_completion_tokens"] == 6000
    assert router.last_call_meta.get("finish_reason") == "length"
    rows = telemetry.calls_for_turn("t-v117-trunc")
    assert rows and all(r["outcome"] == "truncated" for r in rows)
    assert all(r["finish_reason"] == "length" for r in rows)
    await router.close()


async def test_router_length_retry_rescues_complete_reply(tmp_path, tmp_db):
    """The length-retry itself still works: first attempt truncates, the
    doubled-cap retry returns a complete reply, and the complete text —
    never the truncated draft — is what the caller gets."""
    router = _router(tmp_path)
    calls = []
    router._client = lambda name: _FakeClient(calls, truncate_once=True)  # noqa: ARG005
    text, provider, _ = await router.chat(
        [{"role": "user", "content": "اهلا"}], max_tokens=3000,
        turn_id="t-v117-trunc-ok", step="main")
    assert text == "تمام يا عم، أنا كويس والحمد لله."
    assert provider == "groq"
    assert len(calls) == 2
    assert calls[1]["max_completion_tokens"] == 6000
    await router.close()


def test_completion_kwargs_nvidia_chat_thinking_off():
    """NVIDIA chat turns send enable_thinking=false (its thinking is
    uncontrolled and would otherwise eat the visible budget); hard /
    search turns keep thinking on."""
    chat = _completion_kwargs("nvidia", "nvidia/nemotron-3.5-super-vl-120b-a12b",
                              [], 0.7, 3000, hard=False)
    assert chat["reasoning_effort"] == "low"
    assert chat["max_completion_tokens"] == 3000
    assert chat["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}}
    hard = _completion_kwargs("nvidia", "nvidia/nemotron-3.5-super-vl-120b-a12b",
                              [], 0.7, 3000, hard=True)
    assert "extra_body" not in hard


def test_completion_kwargs_reasoning_low_everywhere():
    """reasoning_effort='low' is sent on every call (Groq, NVIDIA,
    Gemini) — the report's #1 suspect (a medium default) is not the
    cause here, and this pins it."""
    for family, model in (
            ("groq", "openai/gpt-oss-120b"),
            ("nvidia", "nvidia/nemotron-3.5-super-vl-120b-a12b"),
            ("gemini", "gemini-3-flash-preview")):
        kw = _completion_kwargs(family, model, [], 0.7, 3000, hard=False)
        assert kw["reasoning_effort"] == "low", family
        assert kw["max_completion_tokens"] == 3000, family
        assert "max_tokens" not in kw, family


def test_completion_kwargs_groq_include_reasoning():
    kw = _completion_kwargs("groq", "openai/gpt-oss-120b", [], 0.7, 3000, hard=False)
    assert kw["include_reasoning"] is False
    assert "extra_body" not in kw


# --- (6) deep variation + regret — probes #12, #14 --------------------------

def test_regret_detector():
    assert looks_like_regret_question("ندمت على حاجة؟") is True
    assert looks_like_regret_question("بتندم على ايه؟") is True
    assert looks_like_regret_question("انت خايف من ايه؟") is False
    assert looks_like_regret_question("انت راضي عن حياتك؟") is False


def test_deep_question_clusters():
    assert deep_question_cluster("انت خايف من ايه؟") == "fear"
    assert deep_question_cluster("ندمت على حاجة؟") == "regret"
    assert deep_question_cluster("انت راضي عن حياتك؟") == "deep"


def test_lead_fear_rotates_and_never_repeats():
    # next_lead_fear returns the fact dict; the rotation is on its id.
    assert next_lead_fear(None)["id"] == "f57"
    assert next_lead_fear("f57")["id"] == "f58"
    assert next_lead_fear("f58")["id"] == "f59"
    assert next_lead_fear("f59")["id"] == "f57"
    assert next_lead_fear("f57")["id"] == "f58"


def test_deep_fallback_never_repeats_last():
    from brain.persona_facts import DEEP_FALLBACK_LINES

    first = deep_fallback_line(1)
    assert first in DEEP_FALLBACK_LINES
    second = deep_fallback_line(2, exclude=first)
    assert second in DEEP_FALLBACK_LINES
    assert second != first


def test_is_regret_evasion():
    # the live #14 evasion: a dismiss bank line as the whole reply
    assert is_regret_evasion("بس يا أستاذة!") is True
    assert is_regret_evasion(CANNED) is True
    assert is_regret_evasion("ما كفاية بقى") is True
    assert is_regret_evasion("ندمت على كتير") is False
    assert is_regret_evasion("ندمت إني ضيعت سنين في حاجات ما كانتش تستاهل.") is False


async def test_repeat_fear_question_not_byte_identical(
        memory_fakes, settings, monkeypatch, tmp_db):
    """Live failure #12: the same fear question re-asked returned a
    word-for-word duplicate (the exact-match cache replayed turn 1).
    Turn 2 must get its own reply, with a DIFFERENT lead fear and a
    note naming turn 1's answer."""
    a = "بخاف أموت برا من غير ما أرجع مصر، ده أكتر حاجة بتخوفني يا عم."
    b = "بخاف أعيش وحيد بعيد عن عيلتي، وبخاف على صحتي، ده اللي بيخوفني."
    router = _ScriptedRouter([a, b])
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت انت خايف من ايه؟", router,
        user_id=777, update_id=3030)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=3030), ctx)
    assert _final(msg) == a
    note1 = _note(router.calls[0], "السؤال ده شخصي وعميق")
    assert note1 is not None
    assert "خايف يموت برا من غير ما يرجع مصر" in note1
    assert "جاوبت على سؤال زي ده قبل كده" not in note1
    # turn 2 — same question, a different user id dodges the 10 s pacing
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت انت خايف من ايه؟", router,
        user_id=778, update_id=3031)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=3031), ctx)
    assert _final(msg) == b
    assert _final(msg) != a
    note2 = _note(router.calls[1], "السؤال ده شخصي وعميق")
    assert note2 is not None
    assert "خايف يعيش وحيد بعيد عن عيلته" in note2
    assert "جاوبت على سؤال زي ده قبل كده" in note2
    assert "بخاف أموت برا من غير ما أرجع مصر" in note2


async def test_regret_evasion_gets_sincere_fallback(
        memory_fakes, settings, monkeypatch, tmp_db):
    """Live failure #14: "ندمت على حاجة؟" got "بس يا أستاذة!" — an
    evasive regret reply is now replaced by the sincere regret
    fallback, in ONE router call."""
    router = _ScriptedRouter(["بس يا أستاذة!"])
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت ندمت على حاجة؟", router,
        update_id=3040)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=3040), ctx)
    assert len(router.calls) == 1
    assert _final(msg) == REGRET_FALLBACK_LINE
    assert "ندمت" in _final(msg)


async def test_fear_dodge_fallback_rotates(
        memory_fakes, settings, monkeypatch, tmp_db):
    """Two dodge turns on the same fear question get two DIFFERENT
    fallback lines (the deep fallback rotates and never repeats the
    last one sent)."""
    from brain.persona_facts import DEEP_FALLBACK_LINES

    router = _ScriptedRouter(["أنا مش خايف من حاجة", "أنا مش خايف من حاجة"])
    finals = []
    for user_id, update_id in ((777, 3050), (778, 3051)):
        ctx, bot, msg, user = _run_turn(
            monkeypatch, settings, "يا بهجت انت خايف من ايه؟", router,
            user_id=user_id, update_id=update_id)
        await h._on_group_message_inner(
            make_update(msg, user, -100222, update_id=update_id), ctx)
        finals.append(_final(msg))
    assert finals[0] in DEEP_FALLBACK_LINES
    assert finals[1] in DEEP_FALLBACK_LINES
    assert finals[0] != finals[1]


# --- (7) garble dictionary — probe #21 --------------------------------------

def test_garble_alayma_to_qayma():
    assert _apply_garble_dictionary("والآيما دي عرف مش مناسب") == \
        "والقايمة دي عرف مش مناسب"
    ok, fixed = check_reply("والآيما دي عرف مش مناسب")
    assert ok is True
    assert "والقايمة" in fixed
    assert "الآيما" not in fixed
    assert any(f.startswith("garble:الآيما") for f in garble_flags(
        "والآيما دي عرف مش مناسب"))


def test_system_base_stays_within_budget():
    """v1.17 adds no prompt words — SYSTEM_BASE must stay under the
    2000-char budget (v1.16: 1877)."""
    assert len(SYSTEM_BASE) < 2000
