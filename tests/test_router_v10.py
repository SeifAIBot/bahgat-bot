"""v1.0 router rework: fast path for trivial chat, status bubble only for
slow work, Arabic-normalised intent, YouTube query smoothing, and the
deterministic prefix layer ("دور" search / "هات" YouTube / "قول" voice).

Exact phrases from Seif's phone video (2026-11-26 07:32 EET) are covered
first; the prefix phrases are his own design, added to the v1.0 scope
2026-11-26 ~07:51 EET."""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import tg.handlers as h
from brain.intent import (
    _FAST_REPLIES,
    detect_fast_reply,
    detect_intent,
    detect_prefix_mode,
)
from core.config import Settings

OWNER_ID = 1415214630


# --- exact video phrases ----------------------------------------------------

def test_thanks_is_fast_path_not_llm():
    reply = detect_fast_reply("شكرا يا بهجت", mood=30)
    assert reply in _FAST_REPLIES["thanks"]
    # …and the intent layer itself must not route a thank-you anywhere slow.
    assert detect_intent("شكرا يا بهجت") == "just_chat"
    assert detect_prefix_mode("شكرا يا بهجت") is None


def test_song_request_is_youtube_not_search():
    assert detect_intent("دورلي علي اغنية مروان موسي الخلاصه @Bahgoti_bot") == "youtube"
    assert detect_intent("دورلي علي اغنية مروان موسي الخلاصه") == "youtube"


def test_waraq_search_still_works():
    assert detect_intent("بهجت سيرش علي حادثة الوراق") == "search"
    assert detect_intent("بهجت سيرش على النت على حادثة الوراق") == "search"


def test_circuit_question_is_plain_chat_no_bubble():
    assert detect_intent("طب ممكن تشرحلي الدايرة الكهربائية بشتغل ازاي يا بهجت") == "just_chat"
    assert detect_fast_reply("طب ممكن تشرحلي الدايرة الكهربائية بشتغل ازاي يا بهجت") is None


# --- Arabic normalisation ---------------------------------------------------

def test_normalised_keywords_match_both_spellings():
    # على/علي and ة/ه: the keyword lists are written normalised, and since
    # v1.0 _has() normalises the keywords too, so either spelling matches.
    assert detect_intent("دور على النت") == "search"
    assert detect_intent("دور علي النت") == "search"
    assert detect_intent("دورلي علي الاغنية") == "youtube"
    assert detect_intent("دورلي على الأغنية") == "youtube"


def test_media_verb_rule_disambiguates_dawwarli():
    # The bare verb "دورلي" cannot decide: a song is YouTube, an incident
    # is search. The media noun decides.
    assert detect_intent("دورلي علي اغنية مروان موسي الخلاصه") == "youtube"
    assert detect_intent("دورلي علي حادثة الوراق") == "search"
    assert detect_intent("هاتلي اغنية لعمرو دياب") == "youtube"
    assert detect_intent("هاتلي ملخص عن حادثة الوراق") == "search"


def test_bare_media_is_youtube_but_a_question_is_not():
    assert detect_intent("بهجت اغنية الخلاصه") == "youtube"
    assert detect_intent("بهجت تراك مروان موسي") == "youtube"
    assert detect_intent("ايه رايك في اغنية مروان موسي") == "just_chat"


def test_request_verbs_alone_do_not_force_youtube():
    # "نزل سعر الدولار" is a price question, not a download.
    assert detect_intent("نزل سعر الدولار") == "search"
    assert detect_intent("شغل مروان موسي") == "youtube"  # "شغل X" = play X


# --- deterministic prefix layer ("دور" / "هات" / "قول") ---------------------

def test_prefix_dawwar_is_search():
    assert detect_prefix_mode("دور حادثة الوراق") == ("search", "حادثه الوراق")
    assert detect_prefix_mode("بهجت دور حادثة الوراق") == ("search", "حادثه الوراق")
    assert detect_intent("دور حادثة الوراق") == "search"


def test_prefix_haat_is_youtube():
    assert detect_prefix_mode("هات اغنية مروان موسي الخلاصه") == (
        "youtube", "اغنيه مروان موسي الخلاصه")
    assert detect_intent("هات اغنية مروان موسي الخلاصه") == "youtube"


def test_prefix_qool_is_voice():
    assert detect_prefix_mode("قول نكتة") == ("voice", "نكته")
    assert detect_prefix_mode("قولي نكتة") == ("voice", "نكته")
    assert detect_intent("قول نكتة") == "voice"


def test_prefix_ambiguity_guards():
    # "دور مين؟" is "whose turn?", not a search.
    assert detect_prefix_mode("دور مين؟") is None
    assert detect_intent("دور مين؟") == "just_chat"
    # "دور" alone has nothing to search.
    assert detect_prefix_mode("دور") is None
    # "الدور" (the round) is not the "دور" prefix.
    assert detect_prefix_mode("الدور عليك") is None
    assert detect_intent("الدور عليك") == "just_chat"
    # A media noun after "دور" is a song request, not a web search.
    assert detect_prefix_mode("دور اغنية مروان موسي الخلاصه") is None
    assert detect_intent("دور اغنية مروان موسي الخلاصه") == "youtube"
    # A non-media request after "هات" is not a video.
    assert detect_prefix_mode("هات ملخص عن حادثة الوراق") is None
    assert detect_intent("هات ملخص عن حادثة الوراق") == "search"


# --- fast path: variants and guards ------------------------------------------

def test_fast_reply_variants():
    assert detect_fast_reply("بهجت عامل ايه", mood=30) in _FAST_REPLIES["greeting"]
    assert detect_fast_reply("تمام يا بهجت", mood=30) in _FAST_REPLIES["ack"]
    assert detect_fast_reply("ماشي يا بهجت", mood=30) in _FAST_REPLIES["ack"]
    assert detect_fast_reply("ههههه", mood=30) in _FAST_REPLIES["laugh"]
    assert detect_fast_reply("بهجت", mood=30) in _FAST_REPLIES["bare"]


def test_fast_reply_ya_vocative():
    # v1.7: the fast path skips a leading "يا" too — "يا بهجت شكرا"
    # is the same thank-you as "شكرا يا بهجت" and must not cost an
    # LLM turn. Bare "يا بهجت" behaves like bare "بهجت".
    assert detect_fast_reply("يا بهجت شكرا", mood=30) in _FAST_REPLIES["thanks"]
    assert detect_fast_reply("يا بهجت عامل ايه", mood=30) in _FAST_REPLIES["greeting"]
    assert detect_fast_reply("يا بهجت تمام", mood=30) in _FAST_REPLIES["ack"]
    assert detect_fast_reply("يا بهجت", mood=30) in _FAST_REPLIES["bare"]


def test_fast_reply_guards():
    # Apologies are real turns (forgiveness), never templates.
    assert detect_fast_reply("خلاص انا اسف", mood=30) is None
    # Insults never get a canned reply.
    assert detect_fast_reply("يا بهجت انت حمار", mood=30) is None
    # An angry Bahgat does not sweetly say "العفو".
    assert detect_fast_reply("شكرا يا بهجت", mood=80) is None
    # Questions, even short ones, need the LLM.
    assert detect_fast_reply("شكرا؟", mood=30) is None
    # Long messages are real turns.
    assert detect_fast_reply("شكرا يا بهجت علي كل حاجه عملتها", mood=30) is None


# --- YouTube query smoothing -------------------------------------------------

def test_yt_query_strips_request_words():
    assert h._yt_query("دورلي علي اغنية مروان موسي الخلاصه @Bahgoti_bot") == "مروان موسي الخلاصه"
    assert h._yt_query("عايز اغنية مروان بابلو الحلال") == "مروان بابلو الحلال"
    assert h._yt_query("هات اغنية مروان موسي الخلاصه") == "مروان موسي الخلاصه"
    assert h._yt_query("بهجت اغنية الخلاصه") == "الخلاصه"


def test_yt_query_keeps_names_and_mid_query_ali():
    # "علي الحجار" is a name — the leading "علي" must survive.
    assert h._yt_query("اغنية علي الحجار") == "علي الحجار"
    # A bare request with no title leaves nothing to search.
    assert h._yt_query("دورلي علي الاغنية") == ""


def test_yt_query_retry_variant():
    assert h._yt_query_retry("مروان موسي الخلاصه") == "مروان موسي الخلاصه اغنية"
    assert h._yt_query_retry("مروان موسي الخلاصه اغنيه") == ""
    assert h._yt_query_retry("") == ""


# --- status bubble gating (unit) ----------------------------------------------

async def test_status_ensure_started_is_lazy_and_idempotent():
    bot = _FakeStatusBot()
    status = h._StatusMessage(bot, -100)
    assert not status.live
    await status.ensure_started()
    assert status.live
    assert len(bot.sent) == 1
    # Second call is a no-op — still one message, no duplicate bubble.
    await status.ensure_started()
    assert len(bot.sent) == 1


# --- handler level: fast path + "قول" voice-only ------------------------------

class _FakeStatusBot:
    username = "Bahgoti_bot"
    id = 9106462211

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        m = SimpleNamespace(edit_text=AsyncMock(), delete=AsyncMock())
        self.sent.append((chat_id, text, m))
        return m


class _FakeUser:
    def __init__(self, uid, first_name="Test", username="testuser"):
        self.id = uid
        self.first_name = first_name
        self.username = username
        self.is_bot = False


class _FakeChat:
    def __init__(self, chat_id):
        self.id = chat_id
        self.send_message = AsyncMock()


class _FakeMessage:
    def __init__(self, text, chat_id, user, message_id=1):
        self.text = text
        self.chat_id = chat_id
        self.message_id = message_id
        self.from_user = user
        self.reply_to_message = None
        self.chat = _FakeChat(chat_id)
        self.reply_text = AsyncMock(return_value=self)
        self.reply_voice = AsyncMock(return_value=self)


class _RaisingRouter:
    async def chat(self, *a, **k):
        raise RuntimeError("llm must not be called on the fast path")


class _JokeRouter:
    async def chat(self, *a, **k):
        return "مرة واحد محشش راح يشتري باكو لبان", "fake", 0


@pytest.fixture(autouse=True)
def _reset_handler_state():
    for d in (h._last_reply_time, h._last_cooldown_notice, h._last_send, h._send_count,
              h._seen_callbacks, h._membership_cache, h._chat_locks,
              h._last_voice, h._last_anon_notice):
        d.clear()
    h._delete_state("muted_until")
    yield
    h._delete_state("muted_until")


@pytest.fixture
def _memory_fakes(monkeypatch):
    def _get_member(uid):
        return {"user_id": uid, "username": "", "first_name": "Test",
                "notes": "", "mood": 30, "grudge": "", "updated_at": time.time()}

    monkeypatch.setattr(h, "get_member", _get_member)
    monkeypatch.setattr(h, "save_member", lambda m: None)
    monkeypatch.setattr(h, "add_message", lambda *a, **k: None)
    monkeypatch.setattr(h, "recent_messages", lambda chat_id, limit=8: [])
    monkeypatch.setattr("random.random", lambda: 0.99)  # no random voice


@pytest.fixture
def _settings():
    return Settings(telegram_bot_token="x", owner_id=OWNER_ID, allowed_chat_ids="")


def _make_ctx(bot, router, settings):
    return SimpleNamespace(
        bot=bot,
        application=SimpleNamespace(
            bot_data={"settings": settings, "router": router, "yt_requests": {}}))


def _make_update(msg, user):
    return SimpleNamespace(
        update_id=100, effective_message=msg, effective_user=user,
        effective_chat=_FakeChat(-1005812444791), my_chat_member=None,
        callback_query=None)


async def test_thanks_gets_instant_reply_no_llm_no_bubble(
        _settings, _memory_fakes, monkeypatch, tmp_db):
    """The video bug: "شكرا يا بهجت" showed a thinking bubble + LLM call.
    Now: instant canned reply, the router is never called, no bubble."""
    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota",
        lambda u, c, owner_id=None, capacity_replies=None, active_users=None,
        quota_cfg=None: (True, ""), raising=False,
    )
    bot = _FakeStatusBot()
    bot.send_chat_action = AsyncMock()
    bot.get_chat_member = AsyncMock()
    ctx = _make_ctx(bot, _RaisingRouter(), _settings)
    user = _FakeUser(999, first_name="Test")
    msg = _FakeMessage("شكرا يا بهجت", -1005812444791, user)
    await h.on_group_message(_make_update(msg, user), ctx)
    assert bot.sent == []  # no status bubble at all
    msg.reply_text.assert_called_once()
    sent = msg.reply_text.await_args.args[0]
    assert sent in _FAST_REPLIES["thanks"]
    msg.reply_voice.assert_not_called()


async def test_qool_prefix_sends_voice_instead_of_text(
        _settings, _memory_fakes, monkeypatch, tmp_db, tmp_path):
    """Seif's prefix: "قول نكتة" -> the reply goes out as a voice note,
    not as text. The voice is the current Edge TTS voice (RVC not wired)."""
    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota",
        lambda u, c, owner_id=None, capacity_replies=None, active_users=None,
        quota_cfg=None: (True, ""), raising=False,
    )
    ogg = tmp_path / "note.ogg"
    ogg.write_bytes(b"fake-ogg")
    # tools.voice imports edge_tts at module level, which is not
    # installed in this VM (voice is unverified here since v0.5) — stub
    # the module so the handler's `from tools.voice import synthesize`
    # resolves to the fake. Production (Docker) has the real package.
    import sys
    import tools
    stub = SimpleNamespace(synthesize=AsyncMock(return_value=str(ogg)))
    monkeypatch.setitem(sys.modules, "tools.voice", stub)
    monkeypatch.setattr(tools, "voice", stub, raising=False)
    bot = _FakeStatusBot()
    bot.send_chat_action = AsyncMock()
    bot.get_chat_member = AsyncMock()
    ctx = _make_ctx(bot, _JokeRouter(), _settings)
    user = _FakeUser(999, first_name="Test")
    msg = _FakeMessage("بهجت قول نكتة", -1005812444791, user)
    await h.on_group_message(_make_update(msg, user), ctx)
    msg.reply_voice.assert_called_once()  # the joke went out as voice…
    msg.reply_text.assert_not_called()  # …and NOT as text
    assert not ogg.exists()  # temp file cleaned up
