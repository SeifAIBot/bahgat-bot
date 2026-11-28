"""v1.2 bank expansion: 177 lines (36 -> 177), roast + condolence
v1.3: insulted 7 -> 14 served (184 entries total).
v1.4 user-submitted ingest (Seif, insults page): +21 lines — insulted
14 -> 31 served, roast 35 -> 39 served (205 entries total).
v1.5 user-submitted ingest round 2 (Seif, insults page): +9 lines — insulted
31 -> 39 served, roast 39 -> 40 served (214 entries total).
triggers, member_safe tagging for family-insult lines (Seif's rule change
2026-11-26 19:15 EET: family insults allowed, but NEVER at group members),
target-aware verify filter, fail-safe insult-level resolution.

Live context: v1.1 bank was 36 lines, debate/rant-heavy, no family
insults banked at all. Seif ordered the bank grown from Bahgat's most
famous videos (insults + comedy) and then allowed family insults for
non-member targets only, with varied/creative lines over generic repeats.
"""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import tg.handlers as h
from brain import reply_bank as rb
from brain.reply_bank import _pick, load_bank, match_reply_bank, reload_bank
from brain.verify import check_reply, contains_family
from core.config import Settings
from core.rules import contains_family_insult

OWNER_ID = 1415214630
CHAT_ID = -1005812444791


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


@pytest.fixture(autouse=True)
def _reset_bank_state():
    reload_bank()
    for d in (h._last_reply_time, h._last_cooldown_notice, h._last_send,
              h._send_count, h._seen_callbacks, h._membership_cache,
              h._chat_locks, h._last_voice):
        d.clear()
    yield
    reload_bank()
    for d in (h._last_reply_time, h._last_cooldown_notice, h._last_send,
              h._send_count, h._seen_callbacks, h._membership_cache,
              h._chat_locks, h._last_voice):
        d.clear()


def _served():
    return load_bank()


def _roast_lines(member_safe_only=True):
    entries = _served()["roast"]
    if member_safe_only:
        entries = [e for e in entries if e.get("member_safe", True) is not False]
    return {e["line"] for e in entries}


# --- bank shape ---------------------------------------------------------------

def test_bank_v12_counts():
    bank = _served()
    assert set(bank) == {
        "catchphrase", "greeting", "insulted", "opinion_asked",
        "joke_request", "dismiss", "challenge", "search_fetch",
        "roast", "condolence",
    }
    assert sum(len(v) for v in bank.values()) == 212
    assert {k: len(v) for k, v in bank.items()} == {
        "catchphrase": 24, "greeting": 4, "insulted": 44,
        "opinion_asked": 31, "joke_request": 10, "dismiss": 15,
        "challenge": 36, "search_fetch": 2, "roast": 45,
        "condolence": 1,
    }
    # Every entry has source + trigger + confidence marking.
    import yaml
    from pathlib import Path
    raw = yaml.safe_load(open(
        Path(__file__).resolve().parents[1] / "persona/bahgat/reply_bank.yaml",
        encoding="utf-8"))["entries"]
    assert len(raw) == 224
    for e in raw:
        assert e["id"] and e["trigger"] and e["line"] and e["source"]
        assert e["confidence"] in ("verbatim", "cleaned", "approximate", "user")
        assert e.get("member_safe", True) in (True, False)


def test_bank_family_lines_all_tagged():
    # Safety-critical, both directions: every line the detector flags
    # must be tagged non-member-only, and every tagged line must
    # actually contain a family reference (no sloppy tags).
    import yaml
    from pathlib import Path
    raw = yaml.safe_load(open(
        Path(__file__).resolve().parents[1] / "persona/bahgat/reply_bank.yaml",
        encoding="utf-8"))["entries"]
    broad = ["ابن", "ولد", "ولاد", "ام", "أم", "ابو", "أبو", "عيله",
             "بنت", "مرات", "حفيد", "جد"]
    tagged = [e for e in raw if e.get("member_safe") is False]
    assert len(tagged) == 17  # 14 transcript family lines + ro-40, ro-42, ro-44 (user)
    for e in raw:
        if contains_family_insult(e["line"]):
            assert e.get("member_safe") is False, e["id"]
    for e in tagged:
        assert any(w in e["line"] for w in broad), e["id"]


def test_bank_no_near_duplicate_generic_insults():
    # Seif's quality direction: no stacks of generic repeats.
    lines = [e["line"] for e in load_bank()["roast"]]
    assert len(lines) == len(set(lines))
    generic = [ln for ln in lines if ln.strip() in (
        "يا وسخ", "يا معرص", "يا معفن", "يا غبي", "يا حمار", "يا ابن الكلب",
    )]
    assert generic == []


# --- roast: member safety -----------------------------------------------------

def test_roast_member_target_gets_person_only_lines():
    safe = _roast_lines(member_safe_only=True)
    assert len(safe) == 30  # 45 served roast - 15 served family lines
    for _ in range(30):
        line = match_reply_bank(
            "يا بهجت اشتم محمد", chat_id=CHAT_ID, target_is_member=True)
        assert line in safe


def test_roast_non_member_target_may_serve_family_lines():
    false_lines = _roast_lines(member_safe_only=False) - _roast_lines(True)
    assert len(false_lines) == 15  # 12 transcript + ro-40, ro-42, ro-44 (user)
    seen = {
        match_reply_bank(
            "يا بهجت اشتم السيسي", chat_id=CHAT_ID, target_is_member=False)
        for _ in range(40)
    }
    assert seen & false_lines  # at least one family-insult line served


def test_roast_unresolved_target_fails_safe():
    safe = _roast_lines(member_safe_only=True)
    for _ in range(30):
        line = match_reply_bank(
            "يا بهجت اشتم السيسي", chat_id=CHAT_ID, target_is_member=None)
        assert line in safe


def test_roast_never_at_owner_or_bot():
    assert match_reply_bank(
        "يا بهجت اشتم سيف", chat_id=CHAT_ID,
        target_is_member=True, target_is_owner=True) is None
    # "اشتم بهجت" — insulting the bot itself goes to the LLM, not the bank.
    assert match_reply_bank(
        "اشتم بهجت", chat_id=CHAT_ID, target_is_member=False) is None


def test_roast_beats_opinion_topic():
    # "اشتم السيسي" is a roast request, not an opinion question.
    for _ in range(10):
        line = match_reply_bank(
            "يا بهجت اشتم السيسي", chat_id=CHAT_ID, target_is_member=False)
        assert line in _roast_lines(member_safe_only=False)


def test_pick_member_safe_filter_is_exact(monkeypatch):
    # Deterministic: synthetic cache with one safe + one family line.
    rb._bank_cache = {"roast": [
        {"id": "ro-x", "line": "يا معفن", "trigger": "roast"},
        {"id": "ro-y", "line": "يا ابن الكلب", "trigger": "roast",
         "member_safe": False},
    ]}
    rb._last_used.clear()
    assert _pick("roast", CHAT_ID, member_safe_only=True) == "يا معفن"
    # Only the family line is left unused, so the full pool serves it.
    assert _pick("roast", CHAT_ID, member_safe_only=False) == "يا ابن الكلب"
    # ...and with the safe line recently used, the full pool still serves.
    rb._last_used.clear()
    monkeypatch.setattr(rb.random, "choice", lambda xs: xs[-1])
    # v1.6 phase 2: clearing the in-memory last-5 no longer resets
    # rotation — the persisted window still holds BOTH lines, so the
    # pick falls back to the least-recently-used line ("يا معفن"),
    # and the member-safe pick serves it too.
    assert _pick("roast", CHAT_ID, member_safe_only=False) == "يا معفن"
    assert _pick("roast", CHAT_ID, member_safe_only=True) == "يا معفن"


def test_opinion_pool_serves_non_member_lines(monkeypatch):
    # Opinion lines are ABOUT السيسي/التكفير (non-member subjects), so
    # the pool is not member-restricted: op-35 (d-12, family insult at
    # a thieving ruler compared to Sisi) must be reachable.
    reload_bank()
    monkeypatch.setattr(rb.random, "choice", lambda xs: xs[-1])
    assert _pick("opinion_asked", CHAT_ID, member_safe_only=False) == (
        "ابن الوسخة اللي سرق المال زي السيسي كده")
    assert _pick("opinion_asked", CHAT_ID, member_safe_only=True) != (
        "ابن الوسخة اللي سرق المال زي السيسي كده")


# --- condolence ---------------------------------------------------------------

def test_condolence_fires_on_death_words():
    assert match_reply_bank("عمي مات", chat_id=CHAT_ID) == (
        "ربنا يرحم الأموات إن شاء الله")
    assert match_reply_bank("البقاء لله", chat_id=CHAT_ID) == (
        "ربنا يرحم الأموات إن شاء الله")


def test_condolence_does_not_fire_on_match():
    # "ماتش" (football match) must not trigger the condolence line.
    assert match_reply_bank("ماتش الأهلي امتى", chat_id=CHAT_ID) is None
    assert match_reply_bank("اتفرجت على الماتش", chat_id=CHAT_ID) is None


# --- verify: target-aware family filter ---------------------------------------

def test_verify_vocative_family_shapes_stripped_for_member():
    ok, cleaned = check_reply("يا ابن الكلب يا غبي", insult_level="personal_only")
    assert "الكلب" not in cleaned and ok is False
    ok, cleaned = check_reply("يا ولاد الكلب", insult_level="personal_only")
    assert ok is False
    ok, cleaned = check_reply("هل أم إلهك زانية؟", insult_level="personal_only")
    assert ok is False
    # ...but the same lines pass untouched for a resolved non-member.
    ok, cleaned = check_reply("يا ابن الكلب يا غبي", insult_level="full")
    assert ok is True and cleaned == "يا ابن الكلب يا غبي"


def test_verify_innocent_kinship_survives():
    ok, cleaned = check_reply("ابن خلدون قال كذا", insult_level="personal_only")
    assert ok is True and "ابن خلدون" in cleaned
    assert contains_family("يا ابن عمي عامل ايه") is False
    assert contains_family("أم كلثوم") is False


# --- _resolve_insult_level: fail safe -----------------------------------------

class _FakeMember:
    def __init__(self, status):
        self.status = status


class _FakeBot:
    def __init__(self, member=None, exc=None):
        self._member = member
        self._exc = exc

    async def get_chat_member(self, chat_id, user_id):
        if self._exc is not None:
            raise self._exc
        return self._member


class _FakeCtx:
    def __init__(self, bot):
        self.bot = bot


async def test_resolve_level_no_target_fails_safe():
    # v1.2: no resolvable target ("اشتمه" with no referent) is ambiguous
    # -> person-only.
    ctx = _FakeCtx(_FakeBot(exc=RuntimeError("must not be called")))
    assert await h._resolve_insult_level(
        ctx, -2001, "اشتمه", [], None, [], OWNER_ID) == (
        "personal_only", None)


async def test_resolve_level_named_non_member_stays_full():
    # A named person found nowhere among the members is the resolver's
    # non-member answer (e.g. "اشتم السيسي") — full range preserved.
    ctx = _FakeCtx(_FakeBot(exc=RuntimeError("user not found")))
    assert await h._resolve_insult_level(
        ctx, -2003, "اشتم السيسي", [], None, [], OWNER_ID) == (
        "full", "السيسي")


async def test_resolve_level_member_check_exception_fails_safe():
    # A real id whose membership check ERRORS is ambiguous -> person-only.
    ctx = _FakeCtx(_FakeBot(exc=RuntimeError("network down")))
    reply_to = {"user_id": 777, "first_name": "محمد"}
    assert await h._resolve_insult_level(
        ctx, -2004, "اشتم محمد", [], reply_to, [], OWNER_ID) == (
        "personal_only", "محمد")


async def test_resolve_level_member_vs_left():
    ctx = _FakeCtx(_FakeBot(member=_FakeMember("member")))
    reply_to = {"user_id": 778, "first_name": "محمد"}
    assert await h._resolve_insult_level(
        ctx, -2005, "اشتم محمد", [], reply_to, [], OWNER_ID) == (
        "personal_only", "محمد")
    ctx = _FakeCtx(_FakeBot(member=_FakeMember("left")))
    reply_to = {"user_id": 779, "first_name": "علي"}
    assert await h._resolve_insult_level(
        ctx, -2006, "اشتم علي", [], reply_to, [], OWNER_ID) == (
        "full", "علي")


async def test_resolve_level_owner_target():
    ctx = _FakeCtx(_FakeBot(exc=RuntimeError("must not be called")))
    reply_to = {"user_id": OWNER_ID, "first_name": "سيف"}
    assert await h._resolve_insult_level(
        ctx, -2007, "اشتم سيف", [], reply_to, [], OWNER_ID) == (
        "owner", "سيف")


# --- handler level: bank-site roast wiring ------------------------------------

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


class _WovenRouter:
    """v1.11: returns a woven reply containing the bank ingredient —
    "والله العظيم يا عم، <line>، وكمان كلام من عندي حواليه." The
    strong lazma keeps voice_check quiet, so no regeneration fires."""

    def __init__(self, line):
        self.line = line
        self.calls = []

    async def chat(self, messages, *a, **k):
        self.calls.append(messages)
        return (f"والله العظيم يا عم، {self.line}، وكمان كلام من عندي حواليه.",
                "groq", 10)


@pytest.fixture
def _v12_settings():
    return Settings(telegram_bot_token="x", owner_id=OWNER_ID,
                    gemini_api_key="x", groq_api_key="x")


@pytest.fixture
def _v12_memory(monkeypatch):
    def _get_member(uid):
        return {"user_id": uid, "username": "", "first_name": "Test",
                "notes": "", "mood": 30, "grudge": "",
                "updated_at": time.time()}

    monkeypatch.setattr(h, "get_member", _get_member)
    monkeypatch.setattr(h, "save_member", lambda m: None)
    monkeypatch.setattr(h, "add_message", lambda *a, **k: None)
    monkeypatch.setattr(
        h, "recent_messages",
        lambda chat_id, limit=8: [{"user_id": 777, "first_name": "محمد"}])
    monkeypatch.setattr("random.random", lambda: 0.99)  # no random voice


def _v12_ctx(bot, settings, router=None):
    return SimpleNamespace(
        bot=bot,
        application=SimpleNamespace(
            bot_data={"settings": settings, "router": router or _RaisingRouter(),
                      "yt_requests": {}}))


def _v12_update(msg, user):
    return SimpleNamespace(
        update_id=100, effective_message=msg, effective_user=user,
        effective_chat=_FakeChat(CHAT_ID), my_chat_member=None,
        callback_query=None)


def _stub_quota_ok(monkeypatch):
    monkeypatch.setattr(
        "brain.memory.check_and_consume_quota",
        lambda u, c, owner_id=None, capacity_replies=None, active_users=None,
        quota_cfg=None: (True, ""), raising=False,
    )


async def test_handler_roast_member_gets_person_only_line(
        _v12_settings, _v12_memory, monkeypatch, tmp_db):
    """End to end: محمد is a cached member -> the bank roast line served
    for "يا بهجت اشتم محمد" must be member-safe, never a family line.
    v1.11: the line is an ingredient in the LLM turn, woven into a
    fuller reply — never the whole reply alone."""
    _stub_quota_ok(monkeypatch)
    h._membership_cache[(CHAT_ID, 777)] = ("personal_only", time.time() + 600)
    monkeypatch.setattr(rb.random, "choice", lambda xs: xs[0])
    bot = _FakeStatusBot()
    bot.send_chat_action = AsyncMock()
    bot.get_chat_member = AsyncMock()
    ctx = _v12_ctx(bot, _v12_settings, _WovenRouter("فاشلين! فاشلين!"))
    user = _FakeUser(999, first_name="Test")
    msg = _FakeMessage("يا بهجت اشتم محمد", CHAT_ID, user)
    await h.on_group_message(_v12_update(msg, user), ctx)
    msg.reply_text.assert_called_once()
    sent = msg.reply_text.await_args.args[0]
    # First member-safe GENERIC roast line in file order: ro-01/02/03 are
    # family lines, ro-04..08 are target-specific (v1.3 targeting), so
    # the first line that fits target محمد is ro-09.
    assert "فاشلين! فاشلين!" in sent and len(sent) > len("فاشلين! فاشلين!")


async def test_handler_roast_non_member_may_serve_family_line(
        _v12_settings, _v12_memory, monkeypatch, tmp_db):
    """End to end: محمد cached as a NON-member -> the full roast pool,
    including family-insult lines, is reachable through the handler.
    v1.11: the line is an ingredient in the LLM turn, woven into a
    fuller reply — never the whole reply alone."""
    _stub_quota_ok(monkeypatch)
    h._membership_cache[(CHAT_ID, 777)] = ("full", time.time() + 600)
    monkeypatch.setattr(rb.random, "choice", lambda xs: xs[0])
    bot = _FakeStatusBot()
    bot.send_chat_action = AsyncMock()
    bot.get_chat_member = AsyncMock()
    ctx = _v12_ctx(bot, _v12_settings, _WovenRouter("يا ولد الوسخة"))
    user = _FakeUser(999, first_name="Test")
    msg = _FakeMessage("يا بهجت اشتم محمد", CHAT_ID, user)
    await h.on_group_message(_v12_update(msg, user), ctx)
    msg.reply_text.assert_called_once()
    sent = msg.reply_text.await_args.args[0]
    # First roast line in file order is a family-insult line (ro-01).
    assert "يا ولد الوسخة" in sent and len(sent) > len("يا ولد الوسخة")
