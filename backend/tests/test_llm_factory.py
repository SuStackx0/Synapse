"""Unit tests for agents/llm_factory.py.

Regression: Synapse is bring-your-own-model and must never ship with a
hardcoded default pointing at a specific vendor or a developer's private
inference endpoint. The only fallback path is a local, gitignored dev
override supplying generic env vars (DEV_LLM_BASE_URL/DEV_LLM_MODEL) - and
even that must be explicitly opted into, never implicit.
"""
import pytest

from agents.llm_factory import get_active_llm, NoActiveProviderError, _provider_api_key
from core.config import settings
from core.models import LLMProvider


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDB:
    """Stands in for an AsyncSession - only .execute(...) is ever called."""
    def __init__(self, provider=None):
        self._provider = provider

    async def execute(self, _query):
        return _FakeResult(self._provider)


@pytest.fixture(autouse=True)
def _clear_dev_env(monkeypatch):
    # Every test starts with the dev fallback fully unset, regardless of
    # whatever a local docker-compose.override.yml has configured.
    monkeypatch.setattr(settings, "dev_llm_base_url", "")
    monkeypatch.setattr(settings, "dev_llm_model", "")
    monkeypatch.setattr(settings, "dev_llm_api_key", "")


@pytest.mark.asyncio
async def test_no_provider_and_no_dev_env_raises():
    with pytest.raises(NoActiveProviderError):
        await get_active_llm(_FakeDB(provider=None))


@pytest.mark.asyncio
async def test_no_provider_falls_back_to_dev_env_when_set(monkeypatch):
    # Never a real vendor URL in source - this is a fake value set only for
    # the duration of this test to prove the fallback path activates.
    monkeypatch.setattr(settings, "dev_llm_base_url", "http://fake-dev-endpoint.invalid/v1")
    monkeypatch.setattr(settings, "dev_llm_model", "fake-model")
    llm = await get_active_llm(_FakeDB(provider=None))
    assert llm.openai_api_base == "http://fake-dev-endpoint.invalid/v1"
    assert llm.model_name == "fake-model"


@pytest.mark.asyncio
async def test_no_provider_partial_dev_env_still_raises(monkeypatch):
    # Both base_url AND model must be set - a half-configured override
    # shouldn't silently activate.
    monkeypatch.setattr(settings, "dev_llm_base_url", "http://fake-dev-endpoint.invalid/v1")
    with pytest.raises(NoActiveProviderError):
        await get_active_llm(_FakeDB(provider=None))


@pytest.mark.asyncio
async def test_active_provider_is_used_over_dev_env(monkeypatch):
    monkeypatch.setattr(settings, "dev_llm_base_url", "http://fake-dev-endpoint.invalid/v1")
    monkeypatch.setattr(settings, "dev_llm_model", "fake-model")
    provider = LLMProvider(
        id="p1", name="Real", provider_type="openai", base_url="https://api.openai.com/v1",
        api_key="", model="gpt-4o", is_active=True,
    )
    llm = await get_active_llm(_FakeDB(provider=provider))
    assert llm.openai_api_base == "https://api.openai.com/v1"
    assert llm.model_name == "gpt-4o"


def test_provider_api_key_falls_back_to_placeholder_when_empty():
    provider = LLMProvider(
        id="p1", name="Local", provider_type="vllm", base_url="http://localhost:8000/v1",
        api_key="", model="llama3", is_active=True,
    )
    assert _provider_api_key(provider) == "not-needed"
