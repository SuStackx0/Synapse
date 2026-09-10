from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import uuid

from core.crypto import encrypt
from core.database import get_db
from core.models import LLMProvider

router = APIRouter(prefix="/settings", tags=["settings"])

PROVIDER_PRESETS = {
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o"},
    "anthropic": {"base_url": "https://api.anthropic.com/v1", "model": "claude-sonnet-4-5"},
    "vllm": {"base_url": "http://localhost:8000/v1", "model": ""},
    "sglang": {"base_url": "http://localhost:30000/v1", "model": ""},
    "ollama": {"base_url": "http://localhost:11434/v1", "model": "llama3"},
    "gemma_local": {"base_url": "http://10.29.210.8:8711/v1", "model": "gemma4"},
}


class ProviderCreate(BaseModel):
    name: str
    provider_type: str
    base_url: str
    api_key: Optional[str] = ""
    model: str


@router.get("/providers/presets")
async def get_presets():
    return PROVIDER_PRESETS


@router.get("/providers")
async def list_providers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LLMProvider))
    # api_key is intentionally never returned (stored encrypted, write-only field).
    return [
        {"id": p.id, "name": p.name, "provider_type": p.provider_type,
         "base_url": p.base_url, "model": p.model, "is_active": p.is_active}
        for p in result.scalars()
    ]


@router.post("/providers")
async def create_provider(req: ProviderCreate, db: AsyncSession = Depends(get_db)):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name=req.name,
        provider_type=req.provider_type,
        base_url=req.base_url,
        # Encrypted at rest; decrypted only when constructing an LLM client.
        api_key=encrypt(req.api_key or ""),
        model=req.model,
        is_active=False,
    )
    db.add(provider)
    await db.commit()
    return {"id": provider.id, "name": provider.name}


@router.post("/providers/{provider_id}/activate")
async def activate_provider(provider_id: str, db: AsyncSession = Depends(get_db)):
    # Deactivate all
    result = await db.execute(select(LLMProvider))
    for p in result.scalars():
        p.is_active = p.id == provider_id
    await db.commit()
    return {"active": provider_id}


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404)
    await db.delete(p)
    await db.commit()
    return {"deleted": provider_id}
