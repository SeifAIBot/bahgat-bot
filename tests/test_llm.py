"""LLM client: provider config, key resolution, overrides (mocked API)."""
import asyncio

import pytest

from bahgat import llm
from conftest import ApiStatusError, llm_settings

GROQ = "https://api.groq.com/openai/v1"
NVIDIA = "https://integrate.api.nvidia.com/v1"
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/"

ALL_KEYS = dict(groq_api_key="k-groq", nvidia_api_key="k-nvidia",
                gemini_api_key="k-gemini")


@pytest.fixture(autouse=True)
def _no_env_keys(clear_llm_keys):
    return clear_llm_keys


class TestProviderConfig:
    def test_yaml_chain_in_file_order(self):
        # v2.2 chain (expert §1 + owner rule: no Cerebras, no OpenRouter).
        providers = llm.load_providers()
        assert [p.name for p in providers] == [
            "groq-20b", "groq-120b", "groq-qwen", "gemini-3.5-flash-lite",
            "nvidia-nemotron"]
        assert len(providers) == 5
        assert {p.family for p in providers} == {"groq", "gemini", "nvidia"}
        assert all(p.model and p.base_url and p.env_key for p in providers)
        assert all(p.timeout_seconds > 0 for p in providers)

    def test_removed_providers_are_gone(self):
        names = {p.name for p in llm.load_providers()}
        for gone in ("cerebras-120b", "gemma-4-31b-it", "gemini-3.1-flash-lite",
                     "gemini-3-flash-preview"):
            assert gone not in names
        assert not any("openrouter" in p.name or p.family == "openrouter"
                       for p in llm.load_providers())

    def test_timeouts_match_expert_budget(self):
        # Per-attempt 15 s (NVIDIA 20 s); total turn budget ~30 s.
        by_name = {p.name: p for p in llm.load_providers()}
        assert by_name["groq-20b"].timeout_seconds == 15
        assert by_name["gemini-3.5-flash-lite"].timeout_seconds == 15
        assert by_name["nvidia-nemotron"].timeout_seconds == 20

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(llm.LLMError):
            llm.load_providers(tmp_path / "nope.yaml")

    def test_bad_yaml_raises(self, tmp_path):
        p = tmp_path / "providers.yaml"
        p.write_text("providers: [\n", encoding="utf-8")
        with pytest.raises(llm.LLMError):
            llm.load_providers(p)

    def test_incomplete_entry_skipped(self, tmp_path):
        p = tmp_path / "providers.yaml"
        p.write_text(
            "providers:\n"
            "  - name: good\n    family: groq\n    model: m\n"
            "    base_url: https://a.example/v1\n    env_key: GROQ_API_KEY\n"
            "  - name: no-model\n    family: groq\n"
            "    base_url: https://a.example/v1\n    env_key: GROQ_API_KEY\n",
            encoding="utf-8")
        assert [x.name for x in llm.load_providers(p)] == ["good"]

    def test_routing_order_overrides_file_order(self, tmp_path):
        p = tmp_path / "providers.yaml"
        p.write_text(
            "providers:\n"
            "  - name: a\n    family: groq\n    model: ma\n"
            "    base_url: https://a.example/v1\n    env_key: GROQ_API_KEY\n"
            "  - name: b\n    family: groq\n    model: mb\n"
            "    base_url: https://b.example/v1\n    env_key: GROQ_API_KEY\n"
            "routing:\n  order: [b, a]\n",
            encoding="utf-8")
        assert [x.name for x in llm.load_providers(p)] == ["b", "a"]


class TestKeyResolution:
    def test_no_keys_raises_and_names_the_env_var(self, fake_openai):
        with pytest.raises(llm.LLMError) as exc:
            llm.LLMClient(llm_settings())
        assert "GROQ_API_KEY" in str(exc.value)

    def test_providers_without_keys_are_skipped(self, fake_openai,
                                                clear_llm_keys):
        clear_llm_keys.setenv("GROQ_API_KEY", "env-groq")
        client = llm.LLMClient(llm_settings())
        assert [p.name for p in client.chain] == [
            "groq-20b", "groq-120b", "groq-qwen"]
        assert "GEMINI_API_KEY" in client.missing

    def test_key_from_process_env(self, fake_openai, clear_llm_keys):
        clear_llm_keys.setenv("GROQ_API_KEY", "env-groq")
        client = llm.LLMClient(llm_settings())
        assert client._client(client.chain[0]).api_key == "env-groq"

    def test_key_from_settings_beats_env(self, fake_openai, clear_llm_keys):
        clear_llm_keys.setenv("GROQ_API_KEY", "env-groq")
        client = llm.LLMClient(llm_settings(groq_api_key="dotenv-groq"))
        assert client._client(client.chain[0]).api_key == "dotenv-groq"

    def test_blank_key_is_not_a_key(self, fake_openai, clear_llm_keys):
        clear_llm_keys.setenv("GROQ_API_KEY", "   ")
        with pytest.raises(llm.LLMError):
            llm.LLMClient(llm_settings())

    def test_api_key_override_pins_first_entry_only(self, fake_openai):
        client = llm.LLMClient(llm_settings(llm_api_key="override-key",
                                            **ALL_KEYS))
        assert client._client(client.chain[0]).api_key == "override-key"
        assert client._client(client.chain[3]).api_key == "k-gemini"


class TestOverrides:
    def test_primary_model_and_base_url(self, fake_openai):
        client = llm.LLMClient(llm_settings(llm_model="other-model",
                                            llm_base_url="https://x.example/v1",
                                            **ALL_KEYS))
        assert client.model == "other-model"
        assert client.chain[0].base_url == "https://x.example/v1"
        assert len(client.chain) == 5  # rest of the chain intact

    def test_llm_provider_moves_family_to_front(self, fake_openai):
        client = llm.LLMClient(llm_settings(llm_provider="gemini", **ALL_KEYS))
        assert client.chain[0].family == "gemini"
        assert len(client.chain) == 5
        assert client.chain[0].name == "gemini-3.5-flash-lite"

    def test_unknown_llm_provider_keeps_full_chain(self, fake_openai):
        client = llm.LLMClient(llm_settings(llm_provider="nope", **ALL_KEYS))
        assert client.chain[0].name == "groq-20b"
        assert len(client.chain) == 5

    def test_llm_chain_sets_exact_order(self, fake_openai):
        client = llm.LLMClient(llm_settings(
            llm_chain="gemini-3.5-flash-lite, groq-20b", **ALL_KEYS))
        assert [p.name for p in client.chain] == [
            "gemini-3.5-flash-lite", "groq-20b"]

    def test_llm_chain_accepts_family_names(self, fake_openai):
        client = llm.LLMClient(llm_settings(llm_chain="nvidia", **ALL_KEYS))
        assert [p.name for p in client.chain] == ["nvidia-nemotron"]

    def test_unknown_chain_name_ignored(self, fake_openai):
        client = llm.LLMClient(llm_settings(
            llm_chain="nope,groq-20b", **ALL_KEYS))
        assert [p.name for p in client.chain] == ["groq-20b"]


class TestClientSetup:
    def test_per_provider_timeout_and_single_attempt(self, fake_openai):
        client = llm.LLMClient(llm_settings(**ALL_KEYS))
        groq = client._client(client.chain[0])
        nvidia = client._client(next(p for p in client.chain
                                     if p.name == "nvidia-nemotron"))
        assert groq.timeout == 15
        assert nvidia.timeout == 20
        assert groq.max_retries == 0  # SDK does not retry; _attempt retries once
        assert groq.base_url == GROQ
        assert nvidia.base_url == NVIDIA

    def test_clients_cached_per_entry(self, fake_openai):
        client = llm.LLMClient(llm_settings(**ALL_KEYS))
        a = client._client(client.chain[0])
        b = client._client(client.chain[0])
        assert a is b

    def test_groq_browser_user_agent(self, fake_openai):
        # Groq is fronted by Cloudflare: a browser User-Agent avoids 403.
        client = llm.LLMClient(llm_settings(**ALL_KEYS))
        groq = client._client(client.chain[0])
        assert "Mozilla" in groq.default_headers["User-Agent"]
        # No OpenRouter entry exists to carry referer headers any more.
        assert all(p.family != "openrouter" for p in client.chain)

    def test_gemini_endpoint(self, fake_openai):
        client = llm.LLMClient(llm_settings(**ALL_KEYS))
        gem = client._client(next(p for p in client.chain
                                  if p.family == "gemini"))
        assert gem.base_url == GEMINI

    async def test_chat_passes_model_and_sampling(self, fake_openai):
        client = llm.LLMClient(llm_settings(**ALL_KEYS))
        out = await client.chat([{"role": "user", "content": "اهلا"}],
                                temperature=0.25, max_tokens=321)
        assert out == "رد تجريبي"
        call = fake_openai.client_for(GROQ).calls[0]
        assert call["model"] == "openai/gpt-oss-20b"
        assert call["temperature"] == 0.25
        assert call["max_tokens"] == 321
        assert client.last_provider == "groq-20b"

    async def test_close_closes_every_client(self, fake_openai):
        client = llm.LLMClient(llm_settings(**ALL_KEYS))
        await client.chat([{"role": "user", "content": "اهلا"}])
        await client.close()
        assert fake_openai.instances
        assert all(c.closed for c in fake_openai.instances)


class TestStatusHelper:
    def test_status_from_attribute(self):
        assert llm._status_of(ApiStatusError(429)) == 429

    def test_status_from_response(self):
        exc = RuntimeError("x")
        exc.response = type("R", (), {"status_code": 503})()
        assert llm._status_of(exc) == 503

    def test_no_status(self):
        assert llm._status_of(RuntimeError("x")) is None

    def test_timeout_error_is_not_a_status(self):
        assert llm._status_of(asyncio.TimeoutError()) is None
