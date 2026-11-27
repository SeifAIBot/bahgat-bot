"""v1.1 fixes: bare-artist routing, pick-list dedupe, opinion stance,
YouTube download repair (removed yt-dlp flags, Android player client,
cookies fallback, error surfacing), voice retry, reply bank, voice check.

Live failures from Seif's v1.0 test (2026-11-26 18:05 EET) + his 18:24 EET
correction (BOTH download taps fail live)."""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import tg.handlers as h
import tools.youtube as yt
from brain.intent import (
    detect_intent,
    detect_prefix_mode,
    looks_like_opinion_ask,
)
from brain.prompt import PROMPT_VERSION, SYSTEM_BASE, _FALLBACK_EXAMPLES
from brain.reply_bank import load_bank, match_reply_bank, reload_bank
from brain.verify import voice_check
from core.config import Settings
from tg.handlers import _download_error_hint

OWNER_ID = 1415214630


# --- bare artist after "هات" (live fail #5) ----------------------------------


@pytest.fixture(autouse=True)
def _tmp_bank_db(monkeypatch, tmp_path):
    """Isolate the persisted bank-rotation window (v1.6 phase 2):
    _pick() records every served line in brain.memory's bot_state, so
    without this the window would leak between tests (and into the
    real data/bahgat.db)."""
    from brain import memory

    db = tmp_path / "bank-test.db"
    monkeypatch.setattr(memory, "DB_PATH", db)
    monkeypatch.setattr(memory, "_SCHEMA_DONE", False)
    memory.init_db()
    yield
    monkeypatch.setattr(memory, "_SCHEMA_DONE", False)
def test_bare_artist_prefix_is_youtube():
    assert detect_prefix_mode("هات مروان موسي") == ("youtube", "مروان موسي")
    assert detect_intent("هات مروان موسي") == "youtube"
    assert detect_prefix_mode("هاتلي مروان موسي") == ("youtube", "مروان موسي")
    assert detect_intent("هاتلي مروان موسي") == "youtube"
    assert detect_prefix_mode("هات لي مروان موسي") == ("youtube", "مروان موسي")
    assert detect_intent("هات لي مروان موسي") == "youtube"
    # Mid-message verb, not just the prefix layer.
    assert detect_intent("يا بهجت هاتلي مروان موسي") == "youtube"
    assert detect_intent("بهجت جبلي مروان موسي") == "youtube"


def test_bare_artist_guards_still_hold():
    # The "هات ملخص" guard stays: a summary is not a video.
    assert detect_prefix_mode("هات ملخص عن حادثة الوراق") is None
    assert detect_intent("هات ملخص عن حادثة الوراق") == "search"
    assert detect_intent("هاتلي ملخص") != "youtube"
    assert detect_intent("هاتلي فلوس") != "youtube"
    assert detect_intent("هات سعر الدولار") == "search"
    # A trailing ؟ does not change a request into a question: "هات
    # مروان موسي؟" still asks for his songs.
    assert detect_intent("هات مروان موسي؟") == "youtube"
    # Four words is not a bare artist name.
    assert detect_prefix_mode("هات مروان موسي اغنية الخلاصه") == (
        "youtube", "مروان موسي اغنيه الخلاصه")


def test_yt_query_for_bare_artist_is_clean():
    assert h._yt_query("مروان موسي") == "مروان موسي"


# --- pick-list dedupe (live note #6: EL 3NWAN twice) -------------------------

def test_search_query_dedupes_by_video_id(monkeypatch):
    payload = {
        "entries": [
            {"id": "aaa", "title": "EL 3NWAN", "duration": 200},
            {"id": "bbb", "title": "EL KHOLASA", "duration": 210},
            {"id": "aaa", "title": "EL 3NWAN", "duration": 200},
        ]
    }

    def fake_run(argv, **kwargs):
        import json
        return SimpleNamespace(stdout=json.dumps(payload), stderr="", returncode=0)

    monkeypatch.setattr(yt, "_run_yt_dlp", fake_run)
    results = yt.search_query("مروان موسي", 5)
    assert [r["video_id"] for r in results] == ["aaa", "bbb"]


def test_search_query_dedupes_same_song_different_upload(monkeypatch):
    """v1.1 (video worker's correction): the live فرعون list had the
    SAME song twice under different uploads/titles, both 3:47 —
    video ids cannot catch that. A later entry drops when its title
    tokens are a subset of an earlier entry's (or vice versa) AND
    the durations are equal. Guards: different durations keep both,
    and a bare one-word title never collapses another song."""
    payload = {
        "entries": [
            {"id": "aaa", "title": "Marwan Moussa - Fr3on (Official Audio) مروان موسى - فرعون", "duration": 227},
            {"id": "bbb", "title": "MARWAN MOUSSA - FR3ON | مروان موسي - فرعون", "duration": 227},
            {"id": "ccc", "title": "مروان موسي - النظام", "duration": 220},
            {"id": "ddd", "title": "Marwan Moussa - EL 3NWAN (Official Audio)", "duration": 178},
            {"id": "eee", "title": "Marwan Moussa - EL 3NWAN (Live)", "duration": 250},
            {"id": "fff", "title": "فرعون", "duration": 182},
            {"id": "ggg", "title": "فرعون - مزه حلوه لبنانيز", "duration": 182},
        ]
    }

    def fake_run(argv, **kwargs):
        import json
        return SimpleNamespace(stdout=json.dumps(payload), stderr="", returncode=0)

    monkeypatch.setattr(yt, "_run_yt_dlp", fake_run)
    results = yt.search_query("مروان موسي فرعون", 7)
    # bbb is the Fr3on re-upload (subset tokens, same duration);
    # eee is a different-length version (kept); fff/ggg share a
    # duration but the one-word title is below the token floor (kept).
    assert [r["video_id"] for r in results] == [
        "aaa", "ccc", "ddd", "eee", "fff", "ggg"]


# --- opinion stance (hardening; the live reply was sharp, the prompt
# had no stance instruction, so the sharpness was luck) ----------------

def test_opinion_ask_detection():
    assert looks_like_opinion_ask("ايه رايك في نظريه المليار الذهبي")
    assert looks_like_opinion_ask("انت شايف ايه في الموضوع ده")
    assert looks_like_opinion_ask("شايف ايه في السيسي")
    assert not looks_like_opinion_ask("شغل اغنية ويجز")
    assert not looks_like_opinion_ask("دور علي نظريه المليار الذهبي")


def test_prompt_version_and_stance():
    assert PROMPT_VERSION == "7.2"  # v1.16: persona-fidelity behaviour lines
    # Behaviour-as-verbs + agenda + anti-softening (research method #3).
    assert "بيرد على الشتيمة بشتيمة أقوى" in SYSTEM_BASE
    assert "عندك رأي في كل حاجة" in SYSTEM_BASE
    assert "متعتذرش، متقولش كنت بهزر" in SYSTEM_BASE
    assert "لزماتك:" in SYSTEM_BASE
    # The opinion example is the 8th pair, in both sources of truth.
    assert len(_FALLBACK_EXAMPLES) == 8
    assert any("ايه رايك في نظريه المليار الذهبي" in e for e in _FALLBACK_EXAMPLES)
    assert any("نظرية فاضية" in e for e in _FALLBACK_EXAMPLES)


# --- YouTube download repair (live fail #8: BOTH taps fail) ------------------

def _fake_ok_run(seen, stdout=""):
    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)
    return fake_run


def test_download_cmd_has_android_client_no_dead_flags(monkeypatch, tmp_path):
    target = tmp_path / "video.mp4"
    target.write_bytes(b"x" * 10)
    seen = {}
    monkeypatch.setattr(
        "tools.youtube.subprocess.run",
        _fake_ok_run(seen, str(target) + "\n"))
    monkeypatch.delenv("YT_COOKIES_FILE", raising=False)
    assert yt.download(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ", False,
        out_dir=str(tmp_path / "req")) == str(target)
    argv = seen["argv"]
    # The v1.1 root cause: --no-thumbnail / --no-subs were REMOVED in
    # newer yt-dlp, so download() died with "no such option" before ANY
    # network request — both taps, every video — while search worked.
    assert "--no-thumbnail" not in argv
    assert "--no-subs" not in argv
    # The bot-check defence: Android player client, no cookies needed.
    assert "--extractor-args" in argv
    assert "youtube:player_client=android" in argv
    assert "--cookies" not in argv
    assert argv[-2] == "--"
    # Video selector keeps the 480p cap with a /best fallback.
    fmt = argv[argv.index("-f") + 1]
    assert fmt == "best[height<=480][ext=mp4]/best[height<=480]/best"


def test_download_audio_selector_falls_back_to_best(monkeypatch, tmp_path):
    """The Android client serves NO audio-only format (only combined
    format 18), so the audio selector must fall back to `best` and let
    --extract-audio pull the track out — otherwise yt-dlp tries the web
    client and dies on the bot-check."""
    target = tmp_path / "audio.mp3"
    target.write_bytes(b"y" * 10)
    seen = {}
    monkeypatch.setattr(
        "tools.youtube.subprocess.run",
        _fake_ok_run(seen, str(target) + "\n"))
    monkeypatch.delenv("YT_COOKIES_FILE", raising=False)
    assert yt.download(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ", True,
        out_dir=str(tmp_path / "req")) == str(target)
    argv = seen["argv"]
    fmt = argv[argv.index("-f") + 1]
    assert fmt == "bestaudio[ext=m4a]/bestaudio/best"
    assert "--extract-audio" in argv and "--audio-format" in argv


def test_resolve_query_cmd_has_android_client(monkeypatch):
    canned = '{"id": "abc123", "title": "t", "duration": 10}'
    seen = {}
    monkeypatch.setattr(
        "tools.youtube.subprocess.run", _fake_ok_run(seen, canned))
    monkeypatch.delenv("YT_COOKIES_FILE", raising=False)
    yt.resolve_query("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert "youtube:player_client=android" in seen["argv"]
    assert "--no-thumbnail" not in seen["argv"]


def test_cookies_args_empty_unless_env_set(monkeypatch, tmp_path):
    monkeypatch.delenv("YT_COOKIES_FILE", raising=False)
    assert yt._cookies_args() == []
    # Set but missing file: warn and proceed without cookies.
    monkeypatch.setenv("YT_COOKIES_FILE", str(tmp_path / "nope.txt"))
    assert yt._cookies_args() == []
    # Real file: passed to yt-dlp.
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\n")
    monkeypatch.setenv("YT_COOKIES_FILE", str(cookies))
    assert yt._cookies_args() == ["--cookies", str(cookies)]


def test_pick_error_detail_prefers_error_line():
    detail = (
        "WARNING: [youtube] x: SSL blah\n"
        "WARNING: [youtube] x: Retrying (1/3)...\n"
        "ERROR: [youtube] x: Sign in to confirm you're not a bot."
    )
    assert yt._pick_error_detail(detail) == (
        "ERROR: [youtube] x: Sign in to confirm you're not a bot.")
    # No ERROR line: fall back to the head of the output.
    assert yt._pick_error_detail("WARNING: something broke") == "WARNING: something broke"
    assert yt._pick_error_detail("") == ""


def test_download_error_hint_classification():
    assert _download_error_hint(
        RuntimeError("yt-dlp failed: ERROR: Sign in to confirm you're not a bot")
    ) == "يوتيوب رافض الطلب من السيرفر"
    assert _download_error_hint(
        RuntimeError("yt-dlp failed: File is larger than max-filesize, 50M")
    ) == "الملف أكبر من 50 ميجا"
    assert _download_error_hint(
        RuntimeError("yt-dlp failed: ERROR: Requested format is not available")
    ) == "مفيش صيغة مناسبة للفيديو ده"
    assert _download_error_hint(
        RuntimeError("yt-dlp failed: ERROR: Private video")
    ) == "الفيديو مش متاح"
    assert _download_error_hint(RuntimeError("yt-dlp failed: something odd")) == ""


# --- voice check (research method #4) ----------------------------------------

def test_voice_check_flags_the_live_failure():
    # The restatement shape the voice check guards against (the
    # brief's misread quote — the live opinion reply was actually
    # sharp; this is the failure mode the check exists to catch).
    flags = voice_check(
        "بحس يا سيدي، دي نظريه بتقول ان فيه ناس عايزه تقلل عدد البشر", 30)
    assert "polite_restatement" in flags
    # A real stance passes.
    assert voice_check("نظرية فاضية يا عم، مفيش مليار ولا حاجة", 30) == []
    # An angry turn that came out polite.
    assert "angry_turn_came_out_polite" in voice_check("تمام، فهمت قصدك", 80)
    # Same words at low mood are fine.
    assert voice_check("تمام، فهمت قصدك", 20) == []
    # Angry + insult or strong lazma passes.
    assert voice_check("تمام يا عم، انت حمار", 80) == []
    assert voice_check("والله العظيم انت مش فاهم حاجة", 80) == []
    # Apology / softening / Fusha.
    assert "fusha_or_apology" in voice_check("اسف يا عم، مش قصدي", 30)
    assert "soft_ending" in voice_check("اسف يا عم، مش قصدي", 30)
    assert "fusha_or_apology" in voice_check("سوف أقوم بذلك", 30)
    assert "ai_phrase" in voice_check("عذراً، كذكاء اصطناعي لا أستطيع", 30)


# --- reply bank (research method #1) ------------------------------------------

def test_bank_loads_and_excludes_risky_lines():
    bank = load_bank()
    assert set(bank) == {
        "catchphrase", "greeting", "insulted", "opinion_asked",
        "joke_request", "dismiss", "challenge", "search_fetch",
        "roast", "condolence",
    }
    # v1.6 phase 1: 224 entries in the file minus 10 approximate (never served)
    # minus the 2 blocked hedges (op-05, op-30) = 212 served.
    # v1.16: 241 entries (+17 study lines) = 229 served.
    assert sum(len(v) for v in bank.values()) == 229  # v1.16: +17 served
    assert len(bank["insulted"]) == 45  # v1.16: in-46 added
    assert len(bank["roast"]) == 46  # v1.16: ro-47 added
    assert len(bank["joke_request"]) == 10
    assert len(bank["opinion_asked"]) == 45  # v1.16: op-36..op-49 added
    assert len(bank["challenge"]) == 36
    assert len(bank["condolence"]) == 1
    assert len(bank["greeting"]) == 4
    # v1.2 rule (Seif 2026-11-26): family-insult lines ARE banked, but
    # every one must be tagged member_safe: false — and every line the
    # detector flags must carry the tag (checked here on the raw file,
    # including approximate lines that are never served).
    import yaml as _yaml
    from core.rules import contains_family_insult as _is_family
    from pathlib import Path as _Path
    _bank_path = _Path(__file__).resolve().parents[1] / "persona/bahgat/reply_bank.yaml"
    with open(_bank_path, encoding="utf-8") as f:
        raw = _yaml.safe_load(f)["entries"]
    assert len(raw) == 241  # v1.16: +17 study lines
    _broad = ["ابن", "يبن", "ولد", "ولاد", "ام", "أم", "ابو", "أبو",
              "عيله", "بنت", "مرات", "المرة", "حفيد", "جد"]
    for e in raw:
        line = e["line"]
        if _is_family(line):
            assert e.get("member_safe") is False, e["id"]
        if e.get("member_safe") is False:
            assert any(w in line for w in _broad), e["id"]


def test_bank_insult_comeback_and_owner_gate():
    line = match_reply_bank("يا بهجت انت حمار", chat_id=-1001, is_owner=False)
    assert line in {e["line"] for e in load_bank()["insulted"]}
    # The owner is never insulted — no bank comeback for him.
    assert match_reply_bank(
        "يا بهجت انت حمار", chat_id=-1001, is_owner=True) is None
    # An insult at someone else (no بهجت, not a reply) is not the bot
    # being insulted.
    assert match_reply_bank(
        "انت حمار", chat_id=-1001, is_owner=False) is None
    # ...unless it IS a reply to the bot.
    assert match_reply_bank(
        "انت حمار", chat_id=-1001, is_owner=False,
        is_reply_to_bot=True) is not None


def test_bank_joke_and_opinion_topic_gate():
    assert match_reply_bank(
        "قول نكته", chat_id=-1001) in {
            e["line"] for e in load_bank()["joke_request"]}
    # Opinion lines are Bahgat's Sisi/takfir stance — only on that topic.
    assert match_reply_bank(
        "ايه رايك في السيسي", chat_id=-1001) in {
            e["line"] for e in load_bank()["opinion_asked"]}
    assert match_reply_bank(
        "ايه رايك في نظريه المليار الذهبي", chat_id=-1001) is None
    assert match_reply_bank(
        "ايه رايك في التكفير", chat_id=-1001) is not None


def test_bank_greeting_and_challenge():
    assert match_reply_bank(
        "اهلا يا بهجت", chat_id=-1001) in {
            e["line"] for e in load_bank()["greeting"]}
    assert match_reply_bank(
        "انت غلط يا بهجت", chat_id=-1001) is not None
    # Priority: insult beats greeting in one message.
    assert match_reply_bank(
        "اهلا يا بهجت انت حمار", chat_id=-1001) in {
            e["line"] for e in load_bank()["insulted"]}
    # Ordinary chat gets no bank line.
    assert match_reply_bank("اشرحلي الدايرة الكهربائية", chat_id=-1001) is None


def test_bank_rotation_never_repeats_consecutively():
    # Rotation guarantee: a pick never repeats any of the previous 5
    # picks from the same category. v1.6 phase 2: the window is 25
    # (persisted per chat), not 5 — and "يا بهجت انت حمار" is a
    # called-dumb insult, so the first picks come from the 4-line
    # called-dumb pool, then the generic fallback, then the rest of the
    # pool as the window slides. The invariant holds strictly. Coverage
    # needs 1200 draws, not 400: the preference tiers mean the 29
    # non-preferred, non-generic lines only get ~10 of every 25 picks,
    # so 400 draws left one of them unpicked ~1 run in 10 (observed
    # flake) — at 1200 draws each such line is picked ~16 times.
    reload_bank()
    picks = [
        match_reply_bank("يا بهجت انت حمار", chat_id=-1001, is_owner=False)
        for _ in range(1200)
    ]
    for i, p in enumerate(picks):
        assert p not in picks[max(0, i - 5):i]
    # And the full insult pool (42 reachable lines) is covered, not
    # just 2-3 favourites. v1.13: 44 served minus in-09/in-38, the two
    # generic feminine lines, which go dormant for insulted comebacks
    # under the gender gate (they carry no gender signal to match).
    # 400 draws: a given line is picked with p≈1/39 per draw (44 - 5 window),
    # so missing one entirely is ~1e-5 — effectively deterministic.
    assert len(set(picks)) == 42
    # Small pools (greeting, 4 served lines) reset after exhaustion, so
    # each 4-block is a full distinct cycle — the v1.1 pattern (v1.6
    # phase 2: the reset is a deterministic least-recently-used cycle).
    reload_bank()
    g1 = [match_reply_bank("اهلا يا بهجت", chat_id=-1001) for _ in range(4)]
    assert len(set(g1)) == 4
    g2 = [match_reply_bank("اهلا يا بهجت", chat_id=-1001) for _ in range(4)]
    assert len(set(g2)) == 4
    reload_bank()


# --- handler level: bank fast path + voice retry + opinion note ---------------

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
        raise RuntimeError("llm must not be called on this path")


class _CaptureRouter:
    def __init__(self, replies):
        self.replies = list(replies)
        self.seen_messages = []
        self.calls = 0

    async def chat(self, messages, **k):
        self.seen_messages.append(messages)
        self.calls += 1
        return self.replies.pop(0), "fake", 0


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


def _stub_quota_ok(monkeypatch):
    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota",
        lambda u, c, owner_id=None, capacity_replies=None, active_users=None,
        quota_cfg=None: (True, ""), raising=False,
    )


async def test_bank_insult_llm_down_sends_error_not_line(
        _settings, _memory_fakes, monkeypatch, tmp_db):
    """v1.11: an insult at the bot weaves a bank comeback into the LLM
    reply — so with the LLM dead, the turn sends the plain error line
    and NEVER the verbatim bank line alone (the ingredient must not
    leak as a standalone reply)."""
    _stub_quota_ok(monkeypatch)
    bot = _FakeStatusBot()
    bot.send_chat_action = AsyncMock()
    bot.get_chat_member = AsyncMock()
    ctx = _make_ctx(bot, _RaisingRouter(), _settings)
    user = _FakeUser(999, first_name="Test")
    msg = _FakeMessage("يا بهجت انت حمار", -1005812444791, user)
    await h.on_group_message(_make_update(msg, user), ctx)
    assert bot.sent == []  # no status bubble
    msg.reply_text.assert_called_once()
    sent = msg.reply_text.await_args.args[0]
    assert sent == h._TURN_ERROR
    assert sent not in {e["line"] for e in load_bank()["insulted"]}
    msg.reply_voice.assert_not_called()


async def test_bank_voice_failure_is_visible_no_cooldown(
        _settings, _memory_fakes, monkeypatch, tmp_db):
    """v1.1 item 9: "قول نكته" with a dead voice path must NOT go
    silent — the text fallback says the voice didn't come out, and a
    failed attempt must NOT consume the 5-minute voice cooldown."""
    _stub_quota_ok(monkeypatch)
    import sys
    import tools
    stub = SimpleNamespace(
        synthesize=AsyncMock(side_effect=RuntimeError("tts down")))
    monkeypatch.setitem(sys.modules, "tools.voice", stub)
    monkeypatch.setattr(tools, "voice", stub, raising=False)
    bot = _FakeStatusBot()
    bot.send_chat_action = AsyncMock()
    bot.get_chat_member = AsyncMock()
    ctx = _make_ctx(bot, _RaisingRouter(), _settings)
    user = _FakeUser(999, first_name="Test")
    msg = _FakeMessage("بهجت قول نكته", -1005812444791, user)
    await h.on_group_message(_make_update(msg, user), ctx)
    # Synthesis was retried once (2 attempts) and still failed.
    assert stub.synthesize.await_count == 2
    msg.reply_voice.assert_not_called()
    msg.reply_text.assert_called_once()
    sent = msg.reply_text.await_args.args[0]
    # v1.9: the voice-failure note is a random pick from the pool.
    assert any(sent.endswith("\n" + line)
               for line in h._VOICE_FAILURE_LINES)
    core = sent
    for line in h._VOICE_FAILURE_LINES:
        suffix = "\n" + line
        if core.endswith(suffix):
            core = core[: -len(suffix)]
            break
    assert core in {e["line"] for e in load_bank()["joke_request"]}
    assert h._last_voice == {}  # failed voice does not eat the cooldown


async def test_bank_voice_retry_succeeds_on_second_attempt(
        _settings, _memory_fakes, monkeypatch, tmp_db, tmp_path):
    """A single synthesis flake is retried and the voice still goes out."""
    _stub_quota_ok(monkeypatch)
    import sys
    import tools
    ogg = tmp_path / "note.ogg"
    ogg.write_bytes(b"fake-ogg")
    stub = SimpleNamespace(synthesize=AsyncMock(
        side_effect=[RuntimeError("flake"), str(ogg)]))
    monkeypatch.setitem(sys.modules, "tools.voice", stub)
    monkeypatch.setattr(tools, "voice", stub, raising=False)
    bot = _FakeStatusBot()
    bot.send_chat_action = AsyncMock()
    bot.get_chat_member = AsyncMock()
    ctx = _make_ctx(bot, _RaisingRouter(), _settings)
    user = _FakeUser(999, first_name="Test")
    msg = _FakeMessage("بهجت قول نكته", -1005812444791, user)
    await h.on_group_message(_make_update(msg, user), ctx)
    assert stub.synthesize.await_count == 2
    msg.reply_voice.assert_called_once()
    msg.reply_text.assert_not_called()
    assert not ogg.exists()
    # A successful voice DOES record the cooldown.
    assert (-1005812444791, 999) in h._last_voice


async def test_opinion_note_reaches_the_router(
        _settings, _memory_fakes, monkeypatch, tmp_db):
    """Opinion stance hardening: the router must see the stance note
    so the reply takes a position instead of restating the theory
    (the live reply happened to be sharp; the prompt had no stance
    instruction, so that was luck, not a guarantee)."""
    _stub_quota_ok(monkeypatch)
    bot = _FakeStatusBot()
    bot.send_chat_action = AsyncMock()
    bot.get_chat_member = AsyncMock()
    router = _CaptureRouter(["نظرية فاضية يا عم، مفيش مليار ولا حاجة"])
    ctx = _make_ctx(bot, router, _settings)
    user = _FakeUser(999, first_name="Test")
    msg = _FakeMessage("ايه رايك في نظريه المليار الذهبي", -1005812444791, user)
    # The live challenge was a REPLY to the bot's search answer.
    msg.reply_to_message = SimpleNamespace(
        from_user=_FakeUser(9106462211, username="Bahgoti_bot"))
    await h.on_group_message(_make_update(msg, user), ctx)
    assert router.calls == 1
    user_texts = [
        m["content"] for m in router.seen_messages[0] if m["role"] == "user"]
    assert any("خد موقف" in t for t in user_texts)
    msg.reply_text.assert_called_once()
    assert "نظرية فاضية" in msg.reply_text.await_args.args[0]


async def test_voice_check_regenerates_once(
        _settings, _memory_fakes, monkeypatch, tmp_db):
    """A polite restatement gets one regeneration with the blunt
    reinforcement; the second reply is what gets sent."""
    _stub_quota_ok(monkeypatch)
    bot = _FakeStatusBot()
    bot.send_chat_action = AsyncMock()
    bot.get_chat_member = AsyncMock()
    router = _CaptureRouter([
        "بحس يا سيدي، دي نظريه بتقول ان فيه ناس عايزه تقلل عدد البشر",
        "نظرية فاضية يا عم، مفيش مليار ولا حاجة",
    ])
    ctx = _make_ctx(bot, router, _settings)
    user = _FakeUser(999, first_name="Test")
    msg = _FakeMessage("ايه رايك في نظريه المليار الذهبي", -1005812444791, user)
    msg.reply_to_message = SimpleNamespace(
        from_user=_FakeUser(9106462211, username="Bahgoti_bot"))
    await h.on_group_message(_make_update(msg, user), ctx)
    assert router.calls == 2
    regen_texts = [
        m["content"] for m in router.seen_messages[1] if m["role"] == "user"]
    assert any("مش بأسلوب بهجت" in t for t in regen_texts)
    msg.reply_text.assert_called_once()
    assert "نظرية فاضية" in msg.reply_text.await_args.args[0]


def test_voice_prefix_survives_voice_word_in_remainder():
    """v1.1 item 9: "قول اهلا في فويس نوت" contains "فويس", so the
    old voice-words guard returned None and the handler lost
    voice_only (text first + trailing voice, live 6:10 PM). The
    guard is for "دور"/"هات" only — the "قول" prefix itself is
    voice, whatever the remainder says."""
    assert detect_prefix_mode("بهجت قول اهلا في فويس نوت") == (
        "voice", "اهلا في فويس نوت")
    assert detect_prefix_mode("قول نكته") == ("voice", "نكته")
    # The guard still holds for the other prefixes: "هات فيديو
    # بصوتك" is a voice request, not a YouTube search.
    assert detect_prefix_mode("هات فيديو بصوتك") is None
    assert detect_intent("هات فيديو بصوتك") == "voice"


async def test_voice_turn_never_searches_on_unknown_reply(
        _settings, _memory_fakes, monkeypatch, tmp_db, tmp_path):
    """v1.1 item 9 (video frames): "قول اهلا في فويس نوت" (6:10 PM)
    came back as _SEARCH_EMPTY text — the unknown-retry ran a web
    search for "اهلا في فويس نوت". A voice turn is not an information
    request: an unknown-looking first reply must be spoken as-is,
    never searched."""
    _stub_quota_ok(monkeypatch)
    import sys
    import tools
    ogg = tmp_path / "note.ogg"
    ogg.write_bytes(b"fake-ogg")
    stub = SimpleNamespace(synthesize=AsyncMock(return_value=str(ogg)))
    monkeypatch.setitem(sys.modules, "tools.voice", stub)
    monkeypatch.setattr(tools, "voice", stub, raising=False)
    monkeypatch.setattr(
        h, "_search_grounding",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("voice turn must not search")),
    )
    bot = _FakeStatusBot()
    bot.send_chat_action = AsyncMock()
    bot.get_chat_member = AsyncMock()
    router = _CaptureRouter(["مش عارف يا عم، اسأل حد تاني"])
    ctx = _make_ctx(bot, router, _settings)
    user = _FakeUser(555, first_name="Test")
    msg = _FakeMessage("بهجت قول اهلا في فويس نوت", -1005812444791, user)
    await h.on_group_message(_make_update(msg, user), ctx)
    assert router.calls == 1  # no search retry, no regeneration
    msg.reply_voice.assert_called_once()  # the reply went out as voice
    msg.reply_text.assert_not_called()


async def test_voice_cooldown_downgrade_is_visible(
        _settings, _memory_fakes, monkeypatch, tmp_db):
    """An explicit "قول" that arrives <5 min after a voice note went
    out is text by design — but it must say so, not silently pretend
    the user got a voice note."""
    _stub_quota_ok(monkeypatch)
    import sys
    import tools
    stub = SimpleNamespace(synthesize=AsyncMock())
    monkeypatch.setitem(sys.modules, "tools.voice", stub)
    monkeypatch.setattr(tools, "voice", stub, raising=False)
    h._last_voice[(-1005812444791, 555)] = time.time()  # voice just sent
    bot = _FakeStatusBot()
    bot.send_chat_action = AsyncMock()
    bot.get_chat_member = AsyncMock()
    router = _CaptureRouter(["اهلا يا عم، انت عامل ايه"])
    ctx = _make_ctx(bot, router, _settings)
    user = _FakeUser(555, first_name="Test")
    msg = _FakeMessage("بهجت قول اهلا في فويس نوت", -1005812444791, user)
    await h.on_group_message(_make_update(msg, user), ctx)
    stub.synthesize.assert_not_called()  # cooldown: no voice attempted
    msg.reply_voice.assert_not_called()
    msg.reply_text.assert_called_once()
    assert msg.reply_text.await_args.args[0].endswith(
        h._VOICE_COOLDOWN_NOTE)
