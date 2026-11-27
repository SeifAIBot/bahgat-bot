"""v1.12 batch 3: tech tastes, temperament, mockery targets (third v1.12 commit).

Seif (2026-11-27 06:25 EET): loves Android, mocks iPhone and Mac;
slightly perverted, loves women; hates homosexuals; mocks feminists
and women's-rights movements; mocks the army and the police in every
country in the world; impulsive, reckless, stubborn, sometimes has a
little wisdom; adventurous, free-spirited, brave, says what's on his
mind; mocks Amr Diab and Tamer Hosny; loves Abo Treika.

Covered here (prompt + intent + handler level, ScriptedRouter — no
real LLM calls, so the assertions are on what the pipeline DOES):
- the batch-3 block is in SYSTEM_BASE and in every built prompt;
- guard: the prompt never praises iPhone/Mac, the army/police, or
  Amr Diab/Tamer Hosny;
- stance questions for every new topic reach the LLM with the
  matching persona line in the system prompt;
- temperament is a how, not just a what: the impulsive / stubborn /
  speaks-his-mind lines ride in the same system prompt as the
  standing "no hedging, no apology" rules, so they shape every reply;
- Abo Treika love and Salah contempt coexist in one turn without
  contradiction (Treika is his guy, Salah is not).
"""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import WeavingRouter, ingredient_of_call

import tg.handlers as h
from brain.intent import detect_intent
from brain.prompt import (
    PROMPT_VERSION,
    SYSTEM_BASE,
    build_system_prompt,
)
from brain.reply_bank import reload_bank

OWNER_ID = 1415214630
CHAT_ID = -100222


# --- prompt level -----------------------------------------------------------

def test_prompt_version_still_6_7():
    # Same version (v1.12), third commit — the version does not tick
    # for a persona expansion inside the same release.
    assert PROMPT_VERSION == "6.9"


TECH_LINES = (
    "بتحب الأندرويد وبتتريق على الآيفون والماك",
    "اللي شايل آيفون عندك مغفل دافع فلوس زيادة على نفس الحاجة",
)

FLIRT_LINES = (
    "منحرف بنسبة بسيطة وبتحب النسوان",
    "هزارك فيه غزل وانحراف خفيف على طول",
)

MOCKERY_LINES = (
    "بتكره الشواذ",
    "وبتتريق على النسويات وحركات حقوق المرأة",
    "بتتريق على الجيش والشرطة في كل بلاد العالم",
    "مفيش جيش ولا شرطة عندك محترمين، كلهم مادة للتريقة",
)

TEMPERAMENT_LINES = (
    "طبعك: مندفع ومتهور وعنيد",
    "بتقول اللي في قلبك على لسانك من غير تفكير ولا لف، ومبتحسبهاش",
    "وساعات بيطلع منك كلام فيه حكمة رغم التهور",
    "مغامر ومنطلق وشجاع",
)

SINGERS_LINES = (
    "بتتريق على عمرو دياب وتامر حسني",
    "وبتحب أبو تريكة جداً",
    "أبو تريكة ده الراجل بتاعك، مفيش كلام",
)

BATCH3_LINES = (TECH_LINES + FLIRT_LINES + MOCKERY_LINES
                + TEMPERAMENT_LINES + SINGERS_LINES)


def test_batch3_blocks_in_system_base():
    for line in BATCH3_LINES:
        assert line in SYSTEM_BASE, f"missing from SYSTEM_BASE: {line}"


def test_batch3_blocks_in_every_built_prompt():
    full = build_system_prompt(member={"first_name": "سيف"}, mood=30,
                               style_examples=[])
    for line in BATCH3_LINES:
        assert line in full, f"missing from built prompt: {line}"


def test_guard_never_praises_iphone_mac_army_police_diab_tamer():
    # The directives are explicit negatives — the prompt must carry
    # them, and must contain no praise phrasing for any of them.
    full = build_system_prompt(member={"first_name": "سيف"}, mood=30,
                               style_examples=[])
    assert "بتتريق على الآيفون والماك" in full
    assert "بتتريق على الجيش والشرطة في كل بلاد العالم" in full
    assert "بتتريق على عمرو دياب وتامر حسني" in full
    for praise in ("الآيفون أحسن", "الآيفون أعظم", "الماك أحسن",
                   "الماك أعظم", "الجيش محترم", "الجيش عظيم",
                   "الشرطة محترمة", "عمرو دياب أسطورة",
                   "عمرو دياب عظيم", "تامر حسني أسطورة",
                   "تامر حسني عظيم"):
        assert praise not in full


def test_batch3_does_not_clash_with_standing_rules():
    # v1.8 identity + v1.9 golden rule + v1.12 football/religion/
    # cause/tastes blocks are still in the same prompt as the new
    # block, and the temperament lines reinforce (never contradict)
    # the standing "no hedging, no apology" rules.
    assert "انت بهجت صابر، إنسان عادي" in SYSTEM_BASE
    assert "ممنوع الفصحى" in SYSTEM_BASE
    assert "أهلاوي جداً" in SYSTEM_BASE
    assert "مسلم وبتغير على دينك" in SYSTEM_BASE
    assert "ميسي أحسن لاعب في التاريخ" in SYSTEM_BASE
    assert "بياخد موقف وبيقوله من غير لف ولا شرح" in SYSTEM_BASE
    assert "متعتذرش، متقولش كنت بهزر" in SYSTEM_BASE
    full = build_system_prompt(member={"first_name": "سيف"}, mood=30,
                               style_examples=[])
    assert "مفيش رد ينفع يتقال لأي حد" in full


# --- intent level -----------------------------------------------------------

@pytest.mark.parametrize("text", [
    "ايه رأيك في الايفون",
    "ايه رأيك في الماك",
    "ايه رأيك في الاندرويد",
    "ايه رأيك في النسويات",
    "ايه رأيك في حقوق المرأة",
    "ايه رأيك في الجيش",
    "ايه رأيك في الشرطة",
    "ايه رأيك في الشواذ",
    "ايه رأيك في عمرو دياب",
    "ايه رأيك في تامر حسني",
    "يا بهجت اشتم عمرو دياب",
    "يا بهجت اشتم تامر حسني",
    "ايه رأيك في أبو تريكة",
    "يا بهجت انت مندفع؟",
    "يا بهجت انت متهور؟",
])
def test_batch3_questions_stay_just_chat(text):
    # Opinion / roast / temperament questions are answered by the LLM
    # from the persona in the prompt — they must NOT trigger a search
    # or a YouTube fetch.
    assert detect_intent(text) == "just_chat"


# --- handler level (real pipeline, fake sends, ScriptedRouter) --------------

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


class ScriptedRouter:
    """Replies in order; records every call."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def chat(self, messages, hard=False, temperature=None,
                   max_tokens=None, **kw):
        self.calls.append(messages)
        reply = self.replies.pop(0) if self.replies else "تمام يا عم"
        return (reply, "groq", 10)


def make_ctx(bot, bot_data):
    return SimpleNamespace(bot=bot,
                           application=SimpleNamespace(bot_data=bot_data))


def make_update(msg, user, chat_id, update_id=100):
    return SimpleNamespace(
        update_id=update_id, effective_message=msg, effective_user=user,
        effective_chat=FakeChat(chat_id), my_chat_member=None,
        callback_query=None,
    )


@pytest.fixture(autouse=True)
def reset_handler_state(tmp_db):
    """tmp_db (conftest): points BOTH handlers' dedup DB (h.DB_PATH)
    and brain.memory at a throwaway DB — without it, _is_duplicate
    writes the test update_ids into the real data/bahgat.db and later
    runs silently drop the turns as duplicates."""
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


async def _run_turn(monkeypatch, settings, text, router, *,
                    user_id=777, update_id=100, grounding_text=None):
    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota",
        lambda u, c, owner_id=None, capacity_replies=None, active_users=None,
        quota_cfg=None: (True, ""), raising=False,
    )
    grounding_calls = []

    async def _g(query):
        grounding_calls.append(query)
        if grounding_text is None:
            return "[SEARCH FAILED] — مفيش نتائج موثوقة، متخترعش."
        return grounding_text

    monkeypatch.setattr(h, "_search_grounding", _g)
    bot = FakeBot()
    ctx = make_ctx(bot, {"settings": settings, "router": router,
                         "yt_requests": {}})
    user = FakeUser(user_id, first_name="Ahmed")
    msg = FakeMessage(text, CHAT_ID, user)
    await h._on_group_message_inner(
        make_update(msg, user, CHAT_ID, update_id=update_id), ctx)
    return ctx, bot, msg, user, grounding_calls


def _system_prompt(router):
    assert len(router.calls) >= 1, "router was never called"
    first = router.calls[0]
    assert first[0]["role"] == "system"
    return first[0]["content"]


def _final(msg):
    assert msg.reply_text.await_count >= 1, "no reply was sent"
    return msg.reply_text.await_args.args[0]


@pytest.mark.parametrize("text,phrase", [
    ("يا بهجت ايه رأيك في الايفون", "بتتريق على الآيفون والماك"),
    ("يا بهجت ايه رأيك في الاندرويد", "بتحب الأندرويد"),
    ("يا بهجت ايه رأيك في النسويات", "بتتريق على النسويات"),
    ("يا بهجت ايه رأيك في حقوق المرأة", "بتتريق على النسويات وحركات حقوق المرأة"),
    ("يا بهجت ايه رأيك في الجيش", "بتتريق على الجيش والشرطة في كل بلاد العالم"),
    ("يا بهجت ايه رأيك في الشرطة", "بتتريق على الجيش والشرطة في كل بلاد العالم"),
    ("يا بهجت ايه رأيك في الشواذ", "بتكره الشواذ"),
    ("يا بهجت ايه رأيك في عمرو دياب", "بتتريق على عمرو دياب وتامر حسني"),
    ("يا بهجت ايه رأيك في تامر حسني", "بتتريق على عمرو دياب وتامر حسني"),
    ("يا بهجت ايه رأيك في أبو تريكة", "بتحب أبو تريكة جداً"),
    ("يا بهجت انت مندفع؟", "طبعك: مندفع ومتهور وعنيد"),
    ("يا بهجت انت متهور؟", "مغامر ومنطلق وشجاع"),
])
async def test_batch3_stance_reaches_llm_with_persona(
        memory_fakes, settings, monkeypatch, text, phrase):
    router = ScriptedRouter(["تمام يا عم، كلامك وصل."])
    ctx, bot, msg, user, _ = await _run_turn(
        monkeypatch, settings, text, router,
        update_id=1302 + hash(text) % 100)
    system = _system_prompt(router)
    assert phrase in system, f"stance missing for {text!r}: {phrase!r}"
    assert msg.reply_text.await_count >= 1


async def test_treika_love_and_salah_contempt_coexist(
        memory_fakes, settings, monkeypatch):
    # v1.12 decision (c): Treika love and Salah contempt live in the
    # same system prompt in one turn — Treika is his guy, Salah is
    # not — with no contradiction between them.
    router = ScriptedRouter(["تمام يا عم، كلامك وصل."])
    ctx, bot, msg, user, _ = await _run_turn(
        monkeypatch, settings, "يا بهجت ايه رأيك في أبو تريكة وصلاح",
        router, update_id=1310)
    system = _system_prompt(router)
    assert "بتحب أبو تريكة جداً" in system
    assert "بتحتقر محمد صلاح" in system
    assert msg.reply_text.await_count >= 1


async def test_diab_roast_weaves_line_and_mockery_together(
        memory_fakes, settings, monkeypatch):
    # Diab (like Tamer) is a mockery target AND roastable — the roast
    # picks a bank ingredient AND carries the persona mockery line in
    # the same turn.
    router = WeavingRouter()
    ctx, bot, msg, user, _ = await _run_turn(
        monkeypatch, settings, "يا بهجت اشتم عمرو دياب", router,
        update_id=1311)
    assert len(router.calls) == 1
    line = ingredient_of_call(router.calls[0])
    assert line is not None
    final = _final(msg)
    assert line in final and len(final) > len(line)
    system = _system_prompt(router)
    assert "[BANK LINE" in system
    assert "بتتريق على عمرو دياب وتامر حسني" in system
