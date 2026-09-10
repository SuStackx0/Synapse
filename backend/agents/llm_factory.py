from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseLanguageModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from core.crypto import decrypt
from core.models import LLMProvider
import structlog

logger = structlog.get_logger()

# DEV-ONLY FALLBACK: a private-network vLLM endpoint with a placeholder key, used
# only when no provider row is marked active so `docker compose up` works out of
# the box on the local dev network. This is a hardcoded constant, not a stored
# user credential, so it is not encrypted.
# WARNING: it will silently activate in any deploy that has no active provider
# configured. A production deploy MUST configure an active provider via
# POST /settings/providers instead of relying on this.
DEFAULT_VLLM_URL = "http://10.29.210.8:8711/v1"
DEFAULT_VLLM_MODEL = "gemma4"
DEFAULT_VLLM_API_KEY = "dummy"  # vLLM ignores the key; placeholder to satisfy the client


def _provider_api_key(provider: LLMProvider) -> str:
    """Decrypt the stored key at the point of use. Local endpoints need no real key."""
    return decrypt(provider.api_key) or DEFAULT_VLLM_API_KEY


async def get_active_llm(db: AsyncSession) -> BaseLanguageModel:
    result = await db.execute(select(LLMProvider).where(LLMProvider.is_active == True))
    provider = result.scalar_one_or_none()

    if not provider:
        # Dev-only default: local Gemma via vLLM (see DEFAULT_VLLM_* above).
        logger.warning("llm_factory_using_dev_fallback", base_url=DEFAULT_VLLM_URL)
        return ChatOpenAI(
            base_url=DEFAULT_VLLM_URL,
            api_key=DEFAULT_VLLM_API_KEY,
            model=DEFAULT_VLLM_MODEL,
            temperature=0.2,
            streaming=True,
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
