"""Shared fixtures: throwaway data dir, fake Telegram objects, fake LLM."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402


@pytest.fixture
def tmp_data(monkeypatch, tmp_path):
    """Point all runtime state at a throwaway dir and init the DB."""
    d = tmp_path / "data"
    monkeypatch.setenv("BAHGAT_DATA_DIR", str(d))
    from bahgat import db, reply_bank

    db.init_db()
    reply_bank.reload_bank()
    yield d
    reply_bank.reload_bank()


@pytest.fixture
def no_seen(monkeypatch):
    """Reset the duplicate-message guard between tests."""
    from bahgat.handlers import chat

    monkeypatch.setattr(chat, "_SEEN_MESSAGES", set())
    yield


class FakeLLM:
    """Records calls; returns queued replies (last one repeats)."""

    def __init__(self, replies=None):
        self.replies = list(replies or ["تمام يا عم، كلامك وصل."])
        self.calls = []

    async def chat(self, messages, temperature=0.7, max_tokens=400):
        self.calls.append({"messages": messages, "temperature": temperature})
        if len(self.replies) > 1:
            return self.replies.pop(0)
        return self.replies[0]

    async def close(self):
        pass


class FakeOpenAIClient:
    """Stand-in for AsyncOpenAI: one object per provider entry."""

    def __init__(self, api_key=None, base_url=None, timeout=None,
                 max_retries=None, default_headers=None):
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.default_headers = default_headers
        self.calls = []
        self.closed = False
        self.registry = {}  # (base_url, model) -> behaviour, from the module
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, model=None, messages=None, temperature=None,
                      max_tokens=None):
        self.calls.append(dict(model=model, messages=messages,
                               temperature=temperature, max_tokens=max_tokens))
        action = self.registry.get((self.base_url, model))
        if callable(action):
            action = action(self)
        if isinstance(action, Exception):
            raise action
        if isinstance(action, dict):
            content = action.get("content", "")
            finish = action.get("finish_reason", "stop")
        elif action is None:
            content, finish = "رد تجريبي", "stop"
        else:
            content, finish = str(action), "stop"
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content), finish_reason=finish)])

    async def close(self):
        self.closed = True


class FakeOpenAIModule:
    """Fake `openai` package. Behaviour is keyed by (base_url, model) so a
    test can make one provider fail and the next one answer."""

    def __init__(self):
        self.instances = []
        self.behavior = {}

    def AsyncOpenAI(self, **kwargs):
        client = FakeOpenAIClient(**kwargs)
        client.registry = self.behavior
        self.instances.append(client)
        return client

    def client_for(self, base_url):
        for client in self.instances:
            if client.base_url == base_url:
                return client
        return None

    def set(self, base_url, model, action):
        self.behavior[(base_url, model)] = action


class ApiStatusError(Exception):
    """An SDK error carrying an HTTP status, like openai's APIStatusError."""

    def __init__(self, status_code, message="boom"):
        super().__init__(message)
        self.status_code = status_code


class FakeMessage:
    def __init__(self, text, chat_id=-1001, message_id=1, from_user=None,
                 reply_to_message=None):
        self.text = text
        self.chat_id = chat_id
        self.chat = SimpleNamespace(id=chat_id)
        self.message_id = message_id
        self.from_user = from_user
        self.reply_to_message = reply_to_message
        self.sent = []  # ("text"|"audio"|"video"|"voice", payload, kwargs)

    async def reply_text(self, text, **kwargs):
        self.sent.append(("text", text, kwargs))
        return SimpleNamespace(message_id=9000 + len(self.sent))

    async def reply_audio(self, fh, **kwargs):
        self.sent.append(("audio", getattr(fh, "name", fh), kwargs))

    async def reply_video(self, fh, **kwargs):
        self.sent.append(("video", getattr(fh, "name", fh), kwargs))

    async def reply_voice(self, fh, **kwargs):
        self.sent.append(("voice", getattr(fh, "name", fh), kwargs))


def make_user(user_id=42, first_name="كريم", is_bot=False, username="kareem"):
    return SimpleNamespace(id=user_id, first_name=first_name, is_bot=is_bot,
                           username=username)


def make_update(text, user=None, chat_id=-1001, message_id=1,
                reply_to_message=None):
    user = user or make_user()
    msg = FakeMessage(text, chat_id=chat_id, message_id=message_id,
                      from_user=user, reply_to_message=reply_to_message)
    return SimpleNamespace(effective_message=msg, effective_user=user)


def make_context(llm_client=None, owner_id=111, bot_username="Bahgoti_bot",
                 allowed_chat_ids="", member_status="member"):
    settings = SimpleNamespace(
        owner_id=owner_id,
        rvc_url="",
        ytdlp_proxy_url="",
        allowed_chat_ids_set=lambda: {
            int(x) for x in allowed_chat_ids.split(",") if x.strip()
        },
    )
    bot_data = {"settings": settings, "llm": llm_client}

    async def get_chat_member(chat_id, user_id):
        # Fake getChatMember: the member_status param drives the answer.
        return SimpleNamespace(status=member_status, user=SimpleNamespace(id=user_id))

    return SimpleNamespace(
        application=SimpleNamespace(bot_data=bot_data),
        bot=SimpleNamespace(username=bot_username,
                            get_chat_member=get_chat_member),
    )


@pytest.fixture
def fake_openai(monkeypatch):
    """Install the fake openai module and return it (behaviour registry)."""
    fake = FakeOpenAIModule()
    monkeypatch.setitem(sys.modules, "openai",
                        SimpleNamespace(AsyncOpenAI=fake.AsyncOpenAI))
    return fake


@pytest.fixture(autouse=True)
def _reset_global_state():
    """stats cooldowns and the target username cache are module-level
    globals — reset them between tests so a cooled-down provider in one
    test never leaks into the next."""
    from bahgat import stats, targets

    stats.reset()
    targets.reset_caches()
    yield
    stats.reset()
    targets.reset_caches()


@pytest.fixture
def clear_llm_keys(monkeypatch):
    """No provider key in the environment unless a test sets one."""
    for var in ("GROQ_API_KEY", "NVIDIA_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def llm_settings(**kw):
    """Settings-shaped object for bahgat.llm.LLMClient."""
    base = dict(llm_chain="", llm_provider="", llm_model="", llm_base_url="",
                llm_api_key="", groq_api_key="", nvidia_api_key="",
                gemini_api_key="")
    base.update(kw)
    return SimpleNamespace(**base)
