from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseLanguageModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from core.models import LLMProvider
import structlog

logger = structlog.get_logger()

DEFAULT_VLLM_URL = "http://10.29.210.8:8711/v1"
DEFAULT_VLLM_MODEL = "gemma4"


async def get_active_llm(db: AsyncSession) -> BaseLanguageModel:
    result = await db.execute(select(LLMProvider).where(LLMProvider.is_active == True))
    provider = result.scalar_one_or_none()

    if not provider:
        # Default: local Qwen via vLLM
        return ChatOpenAI(
            base_url=DEFAULT_VLLM_URL,
            api_key="dummy",
            model=DEFAULT_VLLM_MODEL,
            temperature=0.2,
            streaming=True,
        )

    return ChatOpenAI(
        base_url=provider.base_url,
        api_key=provider.api_key or "dummy",
        model=provider.model,
        temperature=0.2,
        streaming=True,
    )


def build_llm_from_provider(provider: LLMProvider) -> BaseLanguageModel:
    return ChatOpenAI(
        base_url=provider.base_url,
        api_key=provider.api_key or "dummy",
        model=provider.model,
        temperature=0.2,
    )
