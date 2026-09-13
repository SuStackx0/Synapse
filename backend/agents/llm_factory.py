from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseLanguageModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from core.config import settings
from core.crypto import decrypt
from core.models import LLMProvider
import structlog

logger = structlog.get_logger()


class NoActiveProviderError(RuntimeError):
    """Raised when a chat/build request needs an LLM but no provider is configured.

    Synapse is bring-your-own-model: it never talks to a specific vendor or
    a developer's private inference endpoint by default. A provider must be
    added and activated via POST /settings/providers first.
    """


def _provider_api_key(provider: LLMProvider) -> str:
    """Decrypt the stored key at the point of use. The OpenAI SDK requires a
    non-empty string even when the user's own endpoint (e.g. a local vLLM/Ollama
    server) doesn't check it, so a keyless provider gets a neutral placeholder —
    never a vendor- or endpoint-specific value."""
    return decrypt(provider.api_key) or "not-needed"


async def get_active_llm(db: AsyncSession) -> BaseLanguageModel:
    result = await db.execute(select(LLMProvider).where(LLMProvider.is_active == True))
    provider = result.scalar_one_or_none()

    if not provider:
        # No provider configured in the DB. Only a local, gitignored dev override
        # (never committed source) can supply a fallback — see core/config.py.
        if settings.dev_llm_base_url and settings.dev_llm_model:
            logger.warning("llm_factory_using_dev_env_fallback", base_url=settings.dev_llm_base_url)
            return ChatOpenAI(
                base_url=settings.dev_llm_base_url,
                api_key=settings.dev_llm_api_key or "not-needed",
                model=settings.dev_llm_model,
                temperature=0.2,
                streaming=True,
            )
        raise NoActiveProviderError(
            "No active LLM provider configured. Add one in Settings — Synapse works "
            "with any OpenAI-compatible endpoint (OpenAI, Anthropic, vLLM, SGLang, Ollama)."
        )

    return ChatOpenAI(
        base_url=provider.base_url,
        api_key=_provider_api_key(provider),
        model=provider.model,
        temperature=0.2,
        streaming=True,
    )


def build_llm_from_provider(provider: LLMProvider) -> BaseLanguageModel:
    return ChatOpenAI(
        base_url=provider.base_url,
        api_key=_provider_api_key(provider),
        model=provider.model,
        temperature=0.2,
    )
