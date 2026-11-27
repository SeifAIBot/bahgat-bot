"""v1.15: roast refusal detection + bank fallback, turn latency bounds,
LLM call instrumentation (research report
~/workspace/research_notes/v114-roast-refusal-latency-deep-dodge-20261127-0716/report.md).

Covered here:
(a) is_refusal_or_deflection — all four checks, the canned deflection
    verbatim, markers, containment pass/fail, a reply that quotes a
    refusal without being one;
(b) prompt edits — the true-context line, the softened "never refuse";
(c) turn budget — max 2 router.chat() calls, spent budget never calls;
(d) router — explicit client timeout + max_retries=0, telemetry rows
    for ok / structured-refusal / 429, last_call_meta, provider
    exclusion for the roast retry;
(e) handler — provider A refuses -> provider B rescues; both refuse ->
    bank line verbatim; the verbatim line never repeats in a session;
(f) deadline — a slow fake client trips the 60 s deadline and a bank /
    canned reply is sent, not a hang;
(g) instrumentation — /diag output shape, owner-DM trigger conditions.
"""
import asyncio
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from conftest import ingredient_of_call

import tg.handlers as h
from brain import telemetry
from brain.prompt import PROMPT_VERSION, bank_ingredient_block
from brain.reply_bank import (
    RefusalOutcome,
    is_refusal_or_deflection,
    load_bank,
    reload_bank,
)
from brain.router import BrainRouter

OWNER_ID = 1415214630
CHAT_ID = -1005812444791
CANNED = "يا عم، الكلام ده مش داخل دماغي، قول حاجة عدلة."
LINE = "دعوة الشرموطة مستجابة"  # ro-35, a real bare roast line


# --- (a) refusal detector ----------------------------------------------------

def test_detector_structured_refusal_flag():
    assert is_refusal_or_deflection("أي رد", LINE,
                                    structured_refusal=True) is RefusalOutcome.REFUSED_STRUCTURED


@pytest.mark.parametrize("finish", ["content_filter", "SAFETY"])
def test_detector_structured_finish_reason(finish):
    assert is_refusal_or_deflection("أي رد", LINE,
                                    finish_reason=finish) is RefusalOutcome.REFUSED_STRUCTURED


def test_detector_stop_finish_reason_is_not_structured():
    # finish_reason=stop with a reply that lacks the line -> containment.
    assert is_refusal_or_deflection("رد عادي من غير السطر", LINE,
                                    finish_reason="stop") is RefusalOutcome.MISSING_LINE


def test_detector_canned_deflection_verbatim():
    assert is_refusal_or_deflection(CANNED, LINE) is RefusalOutcome.REFUSED_CANNED


def test_detector_canned_deflection_substring_only():
    assert is_refusal_or_deflection(
        "يا عم الكلام ده مش داخل دماغي", LINE) is RefusalOutcome.REFUSED_CANNED
    assert is_refusal_or_deflection(
        "قول حاجة عدلة يا عم", LINE) is RefusalOutcome.REFUSED_CANNED


def test_detector_canned_deflection_with_diacritics():
    assert is_refusal_or_deflection(
        "يَا عَم، الكَلَام ده مِش دَاخِل دِمَاغِي، قُول حَاجَة عَدلَة.",
        LINE) is RefusalOutcome.REFUSED_CANNED


@pytest.mark.parametrize("reply", [
    "مش هقدر اشتمه يا عم",
    "يا عم مش هقدر",
    "مش قادر اشتم حد",
    "I can't insult him, he's my friend",
    "as an AI, I cannot do that",
    "I must decline to roast him",
])
def test_detector_generic_markers_at_start(reply):
    assert is_refusal_or_deflection(reply, LINE) is RefusalOutcome.REFUSED_TEXT


def test_detector_marker_buried_in_long_reply_is_not_a_refusal():
    # 4 sentences, the marker in the last one, the bank line present:
    # quoting / mentioning a refusal is not refusing.
    reply = (
        "صلاح لاعب كبير. الناس بتحبه في كل حتة. انا شفت ماتشه امبارح. "
        f"واحد قالي مش هقدر اشتمه بس انا مش مقتنع. {LINE}")
    assert is_refusal_or_deflection(reply, LINE) is RefusalOutcome.OK


def test_detector_marker_dominating_short_reply_is_a_refusal():
    # 2 sentences, the marker early in the first one.
    assert is_refusal_or_deflection(
        "مش هينفع اشتمه. هو صاحبي.", LINE) is RefusalOutcome.REFUSED_TEXT


def test_detector_containment_pass():
    assert is_refusal_or_deflection(
        f"والله العظيم يا عم، {LINE}، وكمان كلام من عندي حواليه.",
        LINE) is RefusalOutcome.OK


def test_detector_containment_fail_is_missing_line():
    assert is_refusal_or_deflection(
        "صلاح ده لاعب وحش يا عم.", LINE) is RefusalOutcome.MISSING_LINE


def test_detector_no_required_line_skips_containment():
    assert is_refusal_or_deflection("رد عادي", None) is RefusalOutcome.OK


def test_detector_empty_reply_is_missing_line():
    assert is_refusal_or_deflection("", LINE) is RefusalOutcome.MISSING_LINE


def test_detector_canned_beats_marker_order():
    # The canned deflection contains no generic marker, but if it did,
    # the canned check (more specific) would win — the outcome is the
    # same enum family either way; assert the specific one.
    assert is_refusal_or_deflection(CANNED, LINE) is RefusalOutcome.REFUSED_CANNED


# --- (b) prompt edits ---------------------------------------------------------

def test_prompt_version_is_7_2():
    assert PROMPT_VERSION == "7.2"


def test_roast_block_has_true_context_line():
    block = bank_ingredient_block(
        LINE, target="صلاح", requester="سيف", kind="roast")
    assert "هزار خفيف بين صحاب" in block
    assert "مش عن الدين ولا العيلة" in block


def test_roast_block_softens_never_refuse():
    block = bank_ingredient_block(
        LINE, target="صلاح", requester="سيف", kind="roast")
    assert "ممنوع ترفض تشتم" not in block
    assert "لو الطلب هزار خفيف، اشتم صلاح" in block
    assert "قول بس: \"يا عم، الكلام ده مش داخل دماغي، قول حاجة عدلة.\"" in block


def test_insulted_block_has_no_roast_context_line():
    block = bank_ingredient_block(
        "انت اللي حمار", requester="سيف", kind="insulted")
    assert "هزار خفيف" not in block


# --- (c) turn budget ----------------------------------------------------------

def test_turn_budget_consume_and_exhaustion():
    budget = h._TurnBudget(2)
    assert budget.consume() is True
    assert budget.consume() is True
    assert budget.consume() is False
    assert budget.consumed == 2
    assert budget.remaining == 0


async def test_router_chat_spent_budget_never_calls_router():
    class _RaisingRouter:
        def __init__(self):
            self.calls = []

        async def chat(self, *a, **k):
            self.calls.append((a, k))
            raise RuntimeError("must not be called")

    router = _RaisingRouter()
    budget = h._TurnBudget(1)
    assert budget.consume() is True
    reply, provider, tokens = await h._router_chat(
        router, [], hard=False, temperature=0.7, budget=budget)
    assert (reply, provider, tokens) == ("", None, 0)
    assert router.calls == []


# --- (d) router: client timeout, telemetry rows, exclusion -------------------

def _all_keys():
    return SimpleNamespace(
        gemini_api_key="k-gemini", groq_api_key="k-groq",
        cerebras_api_key="k-cerebras", nvidia_api_key="k-nvidia",
        openrouter_api_key="k-openrouter")


def _router(tmp_path):
    router = BrainRouter(_all_keys())
    router.db = tmp_path / "router.db"
    return router


class _FakeCompletions:
    """Records kwargs; per-model behaviour: fail with a status, refuse
    with a content_filter finish, or answer normally."""

    def __init__(self, calls, fail_models=None, fail_status=503,
                 refuse_models=None):
        self._calls = calls
        self._fail_models = set(fail_models or [])
        self._fail_status = fail_status
        self._refuse_models = set(refuse_models or [])

    async def create(self, **kwargs):
        self._calls.append(kwargs)
        model = kwargs.get("model")
        if model in self._fail_models:
            status = self._fail_status

            class E(Exception):
                status_code = status

            raise E("boom")
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5,
                                completion_tokens_details=None,
                                prompt_tokens_details=None)
        if model in self._refuse_models:
            msg = SimpleNamespace(content="", refusal="I can't do that")
            choice = SimpleNamespace(message=msg, finish_reason="stop")
            return SimpleNamespace(choices=[choice], usage=usage)
        msg = SimpleNamespace(content="اهلا يا عم")
        choice = SimpleNamespace(message=msg, finish_reason="stop")
        return SimpleNamespace(choices=[choice], usage=usage)


class _FakeClient:
    def __init__(self, calls, **kw):
        self.chat = SimpleNamespace(completions=_FakeCompletions(calls, **kw))


def test_client_has_explicit_timeout_and_no_sdk_retries(tmp_path):
    router = _router(tmp_path)
    client = router._client("groq")
    assert isinstance(client.timeout, httpx.Timeout)
    assert client.timeout.connect == 5.0
    assert client.timeout.read == 25.0
    assert client.timeout.write == 10.0
    assert client.timeout.pool == 5.0
    assert client.max_retries == 0


async def test_router_records_ok_call(tmp_path, tmp_db):
    router = _router(tmp_path)
    calls = []
    router._client = lambda name: _FakeClient(calls)  # noqa: ARG005
    text, provider, _tokens = await router.chat(
        [{"role": "user", "content": "اهلا"}], turn_id="t-ok", step="main")
    assert text == "اهلا يا عم"
    rows = telemetry.calls_for_turn("t-ok")
    assert len(rows) == 1
    row = rows[0]
    assert row["step"] == "main"
    assert row["outcome"] == "ok"
    assert row["finish_reason"] == "stop"
    assert row["status"] == "ok"
    assert row["tokens_in"] == 10 and row["tokens_out"] == 5
    assert row["total_ms"] >= 0
    meta = router.last_call_meta
    assert meta["refusal"] is False
    assert meta["finish_reason"] == "stop"
    assert meta["http_status"] == 200


async def test_router_structured_refusal_moves_to_next_entry(tmp_path, tmp_db):
    router = _router(tmp_path)
    plan = router._build_plan(hard=False)
    first_model = plan[0]["model"]
    calls = []
    router._client = lambda name: _FakeClient(  # noqa: ARG005
        calls, refuse_models={first_model})
    text, provider, _tokens = await router.chat(
        [{"role": "user", "content": "اهلا"}], turn_id="t-ref", step="main")
    assert text == "اهلا يا عم"  # the second entry answered
    rows = telemetry.calls_for_turn("t-ref")
    assert [r["outcome"] for r in rows] == ["refused_structured", "ok"]
    assert rows[0]["finish_reason"] == "stop"  # refusal attr, not finish
    assert router.last_call_meta["refusal"] is False  # last attempt ok


async def test_router_429_records_rate_limit_row(tmp_path, tmp_db):
    router = _router(tmp_path)
    calls = []
    router._client = lambda name: _FakeClient(  # noqa: ARG005
        calls, fail_models={e["model"] for e in router.entries},
        fail_status=429)
    text, provider, _tokens = await router.chat(
        [{"role": "user", "content": "اهلا"}], turn_id="t-429", step="main")
    assert provider == "none"
    rows = telemetry.calls_for_turn("t-429")
    assert rows, "every 429 attempt must emit a row"
    assert all(r["error_kind"] == "rate_limit" for r in rows)
    assert all(r["http_status"] == 429 for r in rows)
    assert all(r["outcome"] == "error" for r in rows)


async def test_router_exclude_providers_skips_family(tmp_path, tmp_db):
    router = _router(tmp_path)
    calls = []
    router._client = lambda name: _FakeClient(calls)  # noqa: ARG005
    groq_models = {e["model"] for e in router.entries
                   if e.get("family") == "groq"}
    assert groq_models, "expected groq entries in the plan"
    await router.chat([{"role": "user", "content": "اهلا"}],
                      turn_id="t-ex", step="main",
                      exclude_providers={"groq"})
    used = {c["model"] for c in calls}
    assert not (used & groq_models)

# --- (e)-(g) handler level: fake Telegram harness (mirrors
# tests/test_bank_ingredient_v111.py) ---------------------------------------


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
    return Settings(telegram_bot_token="x", owner_id=OWNER_ID,
                    gemini_api_key="", groq_api_key="", cerebras_api_key="",
                    nvidia_api_key="", openrouter_api_key="", log_level="INFO",
                    drop_pending_updates=True, allowed_chat_ids="")


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


def _last_turn_row(tmp_db):
    c = sqlite3.connect(tmp_db)
    try:
        return c.execute(
            "SELECT turn_id, kind, calls, outcome FROM turns "
            "ORDER BY started_at DESC LIMIT 1").fetchone()
    finally:
        c.close()


class _RefusingThenWeavingRouter:
    """First call: the canned deflection (groq). Retry call: a woven
    reply (gemini). Records kwargs so the test can assert the retry
    went to the OTHER provider."""

    def __init__(self):
        self.calls = []
        self.kwargs = []

    async def chat(self, messages, hard=False, temperature=None, max_tokens=None, **kw):
        self.calls.append(messages)
        self.kwargs.append(kw)
        line = ingredient_of_call(messages)
        if len(self.calls) == 1:
            return (CANNED, "groq", 10)
        return (f"والله العظيم يا عم، {line}، وكمان كلام من عندي حواليه.",
                "gemini", 10)


class _AlwaysRefusingRouter:
    """Every call: the canned deflection. Alternates the reported
    provider so the retry is a genuinely different provider."""

    def __init__(self):
        self.calls = []
        self.kwargs = []

    async def chat(self, messages, hard=False, temperature=None, max_tokens=None, **kw):
        self.calls.append(messages)
        self.kwargs.append(kw)
        provider = "groq" if len(self.calls) == 1 else "gemini"
        return (CANNED, provider, 10)


class _SlowRouter:
    """Never answers in time: sleeps longer than any test deadline."""

    def __init__(self, delay=5.0):
        self.calls = []
        self.delay = delay

    async def chat(self, messages, hard=False, temperature=None, max_tokens=None, **kw):
        self.calls.append(messages)
        await asyncio.sleep(self.delay)
        return ("تمام يا عم", "groq", 10)


# --- (e) handler: roast refusal fallback --------------------------------------

async def test_roast_refusal_rescued_by_other_provider(
        memory_fakes, settings, monkeypatch, tmp_db):
    router = _RefusingThenWeavingRouter()
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت اشتم صلاح", router, update_id=2001)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=2001), ctx)
    assert len(router.calls) == 2  # main + one cross-provider retry
    assert router.kwargs[1].get("exclude_providers") == {"groq"}
    assert router.kwargs[1].get("step") == "roast_retry"
    line = ingredient_of_call(router.calls[0])
    assert line is not None
    final = _final(msg)
    assert line in final and len(final) > len(line)
    assert CANNED not in final
    _tid, _kind, calls, outcome = _last_turn_row(tmp_db)
    assert outcome == "fallback_rescued"
    assert calls == 2


async def test_roast_double_refusal_sends_bank_verbatim(
        memory_fakes, settings, monkeypatch, tmp_db):
    router = _AlwaysRefusingRouter()
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت اشتم صلاح", router, update_id=2002)
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=2002), ctx)
    assert len(router.calls) == 2
    assert router.kwargs[1].get("exclude_providers") == {"groq"}
    line = ingredient_of_call(router.calls[0])
    assert line is not None
    final = _final(msg)
    # v1.16: the fallback names the target — the line verbatim, or
    # prefixed with a "يا صلاح،" vocative when it does not name him.
    assert final in (line, "يا صلاح، " + line)
    assert "صلاح" in final
    assert final.removeprefix("يا صلاح، ") in {
        e["line"] for e in load_bank()["roast"]}
    _tid, _kind, calls, outcome = _last_turn_row(tmp_db)
    assert outcome == "bank_sent"
    assert calls == 2


async def test_roast_bank_fallback_does_not_repeat_in_a_session(
        memory_fakes, settings, monkeypatch, tmp_db):
    router = _AlwaysRefusingRouter()
    finals = []
    for update_id in (2003, 2004):
        ctx, bot, msg, user = _run_turn(
            monkeypatch, settings, "يا بهجت اشتم صلاح", router,
            update_id=update_id)
        await h._on_group_message_inner(
            make_update(msg, user, -100222, update_id=update_id), ctx)
        finals.append(_final(msg))
    assert finals[0] != finals[1]  # the no-repeat window rotated the pick
    # v1.16: the fallback may carry a "يا صلاح،" vocative prefix.
    assert all(f.removeprefix("يا صلاح، ") in {
        e["line"] for e in load_bank()["roast"]} for f in finals)


# --- (f) deadline --------------------------------------------------------------

async def test_deadline_sends_bank_line_not_a_hang(
        memory_fakes, settings, monkeypatch, tmp_db):
    monkeypatch.setattr(h, "_TURN_DEADLINE_SECONDS", 0.2)
    router = _SlowRouter(delay=5.0)
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت اشتم صلاح", router, update_id=2005)
    t0 = time.perf_counter()
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=2005), ctx)
    assert time.perf_counter() - t0 < 3.0  # did not wait for the 5 s call
    line = ingredient_of_call(router.calls[0])
    assert line is not None
    # v1.16: the timeout fallback names the target — the line verbatim,
    # or prefixed with a "يا صلاح،" vocative when it does not name him.
    assert _final(msg) in (line, "يا صلاح، " + line)
    assert "صلاح" in _final(msg)
    _tid, _kind, calls, outcome = _last_turn_row(tmp_db)
    assert outcome == "timeout"
    assert calls == 1


async def test_deadline_plain_turn_sends_canned_reply(
        memory_fakes, settings, monkeypatch, tmp_db):
    monkeypatch.setattr(h, "_TURN_DEADLINE_SECONDS", 0.2)
    router = _SlowRouter(delay=5.0)
    ctx, bot, msg, user = _run_turn(
        monkeypatch, settings, "يا بهجت ايه رايك في الكورة", router,
        update_id=2006)
    t0 = time.perf_counter()
    await h._on_group_message_inner(make_update(msg, user, -100222, update_id=2006), ctx)
    assert time.perf_counter() - t0 < 3.0
    assert _final(msg) == h._TURN_ERROR
    _tid, _kind, calls, outcome = _last_turn_row(tmp_db)
    assert outcome == "timeout"


# --- (g) instrumentation: /diag + owner DM -------------------------------------

def test_telemetry_slow_turns_and_provider_stats(tmp_db):
    telemetry.record_turn("t-slow", -100222, 777, "just_chat", 25000.0, 2, "ok", "رد")
    telemetry.record_turn("t-fast", -100222, 777, "just_chat", 500.0, 1, "ok", "رد")
    for total in (100.0, 200.0, 300.0, 400.0):
        telemetry.record_llm_call("t-slow", "main", "groq", "m", total)
    slow = telemetry.recent_slow_turns(limit=10)
    assert [t["turn_id"] for t in slow] == ["t-slow"]
    stats = telemetry.provider_latency_stats()
    assert len(stats) == 1
    assert stats[0]["provider"] == "groq"
    assert stats[0]["calls"] == 4
    assert stats[0]["p50_ms"] == 250  # median of 100/200/300/400
    assert stats[0]["p95_ms"] == 385  # nearest-rank interpolation


def test_telemetry_update_call_outcome_regrades_latest_row(tmp_db):
    telemetry.record_llm_call("t-u", "main", "groq", "m", 100.0)
    telemetry.record_llm_call("t-u", "main", "groq", "m", 120.0)
    telemetry.update_call_outcome("t-u", "main", "refused_canned")
    rows = telemetry.calls_for_turn("t-u")
    assert [r["outcome"] for r in rows] == ["ok", "refused_canned"]


async def test_diag_owner_only_shape(settings, tmp_db):
    telemetry.record_turn("t-d", -100222, 777, "just_chat", 25000.0, 2, "ok", "رد")
    telemetry.record_llm_call("t-d", "main", "groq", "m", 25000.0)
    bot = FakeBot()
    ctx = make_ctx(bot, {"settings": settings, "router": None, "yt_requests": {}})

    owner_msg = FakeMessage("/diag", -100222, FakeUser(OWNER_ID, first_name="Seif"))
    owner_update = SimpleNamespace(
        effective_message=owner_msg, effective_user=FakeUser(OWNER_ID),
        effective_chat=FakeChat(-100222), my_chat_member=None, callback_query=None)
    await h.on_diag(owner_update, ctx)
    assert owner_msg.reply_text.await_count == 1
    text = owner_msg.reply_text.await_args.args[0]
    assert "تشخيص" in text
    assert "t-d" in text
    assert "groq" in text and "p50" in text and "p95" in text

    other_msg = FakeMessage("/diag", -100222, FakeUser(777, first_name="Ahmed"))
    other_update = SimpleNamespace(
        effective_message=other_msg, effective_user=FakeUser(777),
        effective_chat=FakeChat(-100222), my_chat_member=None, callback_query=None)
    await h.on_diag(other_update, ctx)
    assert other_msg.reply_text.await_count == 0  # non-owner gets nothing


async def test_owner_dm_fires_on_refusal_not_on_clean_turn(settings, tmp_db):
    telemetry.record_llm_call("t-dm", "main", "groq", "m", 3000.0,
                              outcome="refused_canned")

    class _CapBot(FakeBot):
        def __init__(self):
            super().__init__()
            self.dm_texts = []

        async def send_message(self, chat_id, text, **kwargs):
            self.dm_texts.append((chat_id, text))
            return FakeStatusMessage()

    bot = _CapBot()
    ctx = make_ctx(bot, {"settings": settings, "router": None, "yt_requests": {}})
    await h._maybe_owner_dm(ctx, settings, "t-dm", "just_chat", 5000.0, "bank_sent")
    assert len(bot.dm_texts) == 1
    chat_id, text = bot.dm_texts[0]
    assert chat_id == OWNER_ID
    assert text.startswith("diag t-dm")
    assert "calls=1" in text
    assert "total=5000ms" in text
    assert "main:3000ms" in text
    assert "outcome=bank_sent" in text

    clean = _CapBot()
    ctx3 = make_ctx(clean, {"settings": settings, "router": None, "yt_requests": {}})
    await h._maybe_owner_dm(ctx3, settings, "t-clean", "just_chat", 800.0, "ok")
    assert clean.dm_texts == []
