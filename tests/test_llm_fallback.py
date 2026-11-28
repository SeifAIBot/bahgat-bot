"""LLM fallback chain: order, per-provider failure handling (mocked API)."""
import asyncio

import pytest

from bahgat import llm
from conftest import ApiStatusError, llm_settings

GROQ = "https://api.groq.com/openai/v1"
NVIDIA = "https://integrate.api.nvidia.com/v1"
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/"

ALL_KEYS = dict(groq_api_key="k-groq", nvidia_api_key="k-nvidia",
                gemini_api_key="k-gemini")

MSGS = [{"role": "user", "content": "اهلا يا بهجت"}]


@pytest.fixture(autouse=True)
def _no_env_keys(clear_llm_keys):
    return clear_llm_keys


@pytest.fixture
def client(fake_openai):
    return llm.LLMClient(llm_settings(**ALL_KEYS))


class TestFallback:
    async def test_first_provider_failure_falls_to_next(self, client, fake_openai):
        fake_openai.set(GROQ, "openai/gpt-oss-20b", RuntimeError("boom"))
        fake_openai.set(GROQ, "openai/gpt-oss-120b", "رد من الموديل التاني")
        out = await client.chat(MSGS)
        assert out == "رد من الموديل التاني"
        assert client.last_provider == "groq-120b"

    async def test_timeout_falls_to_next(self, client, fake_openai):
        fake_openai.set(GROQ, "openai/gpt-oss-20b", asyncio.TimeoutError())
        fake_openai.set(GROQ, "openai/gpt-oss-120b", "رد تاني")
        assert await client.chat(MSGS) == "رد تاني"

    async def test_rate_limit_falls_to_next(self, client, fake_openai):
        fake_openai.set(GROQ, "openai/gpt-oss-20b", ApiStatusError(429))
        fake_openai.set(GROQ, "openai/gpt-oss-120b", "رد بعد الـ429")
        assert await client.chat(MSGS) == "رد بعد الـ429"

    async def test_empty_completion_falls_to_next(self, client, fake_openai):
        fake_openai.set(GROQ, "openai/gpt-oss-20b", "")
        fake_openai.set(GROQ, "openai/gpt-oss-120b", "رد مش فاضي")
        assert await client.chat(MSGS) == "رد مش فاضي"

    async def test_whitespace_completion_falls_to_next(self, client, fake_openai):
        fake_openai.set(GROQ, "openai/gpt-oss-20b", "   \n ")
        fake_openai.set(GROQ, "openai/gpt-oss-120b", "رد مش فاضي")
        assert await client.chat(MSGS) == "رد مش فاضي"

    async def test_refusal_falls_to_next(self, client, fake_openai):
        fake_openai.set(GROQ, "openai/gpt-oss-20b",
                        {"content": "", "finish_reason": "content_filter"})
        fake_openai.set(GROQ, "openai/gpt-oss-120b", "رد عادي")
        assert await client.chat(MSGS) == "رد عادي"

    async def test_gemini_safety_finish_reason_falls_to_next(self, client, fake_openai):
        # Gemini is the 4th entry: Groq down, Gemini SAFETY-filtered,
        # NVIDIA answers.
        for model in ("openai/gpt-oss-20b", "openai/gpt-oss-120b",
                      "qwen/qwen3.8-27b"):
            fake_openai.set(GROQ, model, RuntimeError("down"))
        fake_openai.set(GEMINI, "gemini-3.5-flash-lite",
                        {"content": "", "finish_reason": "SAFETY"})
        fake_openai.set(NVIDIA, "nvidia/nemotron-3.5-super-vl-120b-a12b",
                        "رد من NVIDIA")
        out = await client.chat(MSGS)
        assert out == "رد من NVIDIA"
        assert client.last_provider == "nvidia-nemotron"

    async def test_cross_provider_fallback(self, client, fake_openai):
        """All three Groq models down -> Gemini answers."""
        for model in ("openai/gpt-oss-20b", "openai/gpt-oss-120b",
                      "qwen/qwen3.8-27b"):
            fake_openai.set(GROQ, model, ApiStatusError(429))
        fake_openai.set(GEMINI, "gemini-3.5-flash-lite", "رد من جيميناي")
        out = await client.chat(MSGS)
        assert out == "رد من جيميناي"
        assert client.last_provider == "gemini-3.5-flash-lite"

    async def test_retry_after_429_then_success(self, client, fake_openai):
        """One retry on 429 before falling over: groq-20b is called twice,
        then the chain moves on."""
        fake_openai.set(GROQ, "openai/gpt-oss-20b", ApiStatusError(429))
        fake_openai.set(GROQ, "openai/gpt-oss-120b", "رد تاني")
        assert await client.chat(MSGS) == "رد تاني"
        calls = [c for c in fake_openai.client_for(GROQ).calls
                 if c["model"] == "openai/gpt-oss-20b"]
        assert len(calls) == 2  # first attempt + exactly one retry

    async def test_401_never_retried(self, client, fake_openai):
        """401/403/404 are dead, not retryable: one call, then failover."""
        fake_openai.set(GROQ, "openai/gpt-oss-20b", ApiStatusError(401))
        fake_openai.set(GROQ, "openai/gpt-oss-120b", "رد تاني")
        assert await client.chat(MSGS) == "رد تاني"
        calls = [c for c in fake_openai.client_for(GROQ).calls
                 if c["model"] == "openai/gpt-oss-20b"]
        assert len(calls) == 1

    async def test_text_is_stripped(self, client, fake_openai):
        fake_openai.set(GROQ, "openai/gpt-oss-20b", "  رد نضيف  ")
        assert await client.chat(MSGS) == "رد نضيف"


class TestDisabling:
    @pytest.mark.parametrize("status", [401, 403, 404])
    async def test_dead_key_disables_entry_for_the_run(self, client, fake_openai,
                                                       status):
        fake_openai.set(GROQ, "openai/gpt-oss-20b", ApiStatusError(status))
        fake_openai.set(GROQ, "openai/gpt-oss-120b", "رد تاني")
        assert await client.chat(MSGS) == "رد تاني"
        assert "groq-20b" in client._disabled

        groq_client = fake_openai.client_for(GROQ)
        calls_before = len(groq_client.calls)
        await client.chat(MSGS)
        models_after = [c["model"] for c in groq_client.calls[calls_before:]]
        assert "openai/gpt-oss-20b" not in models_after

    async def test_429_does_not_disable(self, client, fake_openai):
        fake_openai.set(GROQ, "openai/gpt-oss-20b", ApiStatusError(429))
        fake_openai.set(GROQ, "openai/gpt-oss-120b", "رد تاني")
        await client.chat(MSGS)
        assert "groq-20b" not in client._disabled

    async def test_all_entries_disabled_raises(self, client, fake_openai):
        for provider in client.chain:
            fake_openai.set(provider.base_url, provider.model,
                            ApiStatusError(401))
        with pytest.raises(llm.LLMError):
            await client.chat(MSGS)
        # every entry is now known dead, so the next call fails without a
        # single network attempt
        before = sum(len(c.calls) for c in fake_openai.instances)
        with pytest.raises(llm.LLMError):
            await client.chat(MSGS)
        assert sum(len(c.calls) for c in fake_openai.instances) == before


class TestTotalFailure:
    async def test_all_fail_raises_naming_providers(self, client, fake_openai):
        for provider in client.chain:
            fake_openai.set(provider.base_url, provider.model,
                            RuntimeError("down"))
        with pytest.raises(llm.LLMError) as exc:
            await client.chat(MSGS)
        message = str(exc.value)
        assert "groq-20b" in message
        assert "nvidia-nemotron" in message

    async def test_all_refuse_raises(self, client, fake_openai):
        for provider in client.chain:
            fake_openai.set(provider.base_url, provider.model,
                            {"content": "", "finish_reason": "content_filter"})
        with pytest.raises(llm.LLMError):
            await client.chat(MSGS)

    async def test_error_text_never_carries_a_key(self, client, fake_openai):
        secret = "sk-very-secret-key-value"
        client = llm.LLMClient(llm_settings(
            groq_api_key=secret, nvidia_api_key=secret,
            gemini_api_key=secret))
        for provider in client.chain:
            fake_openai.set(provider.base_url, provider.model,
                            RuntimeError(f"auth failed for {secret}"))
        with pytest.raises(llm.LLMError) as exc:
            await client.chat(MSGS)
        assert secret not in str(exc.value)

    async def test_one_provider_only(self, fake_openai, clear_llm_keys):
        clear_llm_keys.setenv("GROQ_API_KEY", "env-groq")
        client = llm.LLMClient(llm_settings())
        fake_openai.set(GROQ, "openai/gpt-oss-20b", RuntimeError("boom"))
        fake_openai.set(GROQ, "openai/gpt-oss-120b", "رد تاني")
        assert await client.chat(MSGS) == "رد تاني"


class TestChainOrder:
    async def test_chain_order_is_respected(self, client, fake_openai):
        for provider in client.chain:
            fake_openai.set(provider.base_url, provider.model,
                            RuntimeError("down"))
        fake_openai.set(NVIDIA, "nvidia/nemotron-3.5-super-vl-120b-a12b",
                        "رد من NVIDIA")
        await client.chat(MSGS)
        order = [(c.base_url) for c in fake_openai.instances]
        # groq clients first, then gemini, then nvidia last
        assert order[0] == GROQ
        assert order.index(GEMINI) < order.index(NVIDIA)

    async def test_llm_chain_override_limits_the_walk(self, fake_openai):
        client = llm.LLMClient(llm_settings(llm_chain="gemini,nvidia",
                                            **ALL_KEYS))
        fake_openai.set(GEMINI, "gemini-3.5-flash-lite", RuntimeError("down"))
        fake_openai.set(NVIDIA, "nvidia/nemotron-3.5-super-vl-120b-a12b",
                        "رد من NVIDIA")
        assert await client.chat(MSGS) == "رد من NVIDIA"
        assert len(fake_openai.instances) == 2


class TestCooldown:
    async def test_provider_cooled_down_after_two_failures(self, client, fake_openai):
        """Two consecutive failed turns cool the provider down for 10 min:
        the next turn skips it without a network attempt."""
        from bahgat import stats

        for _ in range(2):
            fake_openai.set(GROQ, "openai/gpt-oss-20b", RuntimeError("down"))
            fake_openai.set(GROQ, "openai/gpt-oss-120b", "رد تاني")
            await client.chat(MSGS)
        assert stats.is_dead("groq-20b")
        calls_before = len(fake_openai.client_for(GROQ).calls)
        fake_openai.set(GROQ, "openai/gpt-oss-120b", "رد تاني")
        await client.chat(MSGS)
        after = [c for c in fake_openai.client_for(GROQ).calls[calls_before:]
                 if c["model"] == "openai/gpt-oss-20b"]
        assert after == []
