from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import uuid
from datetime import datetime

from core.database import get_db
from core.models import ChatSession, ChatMessage

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    repo_id: str
    title: Optional[str] = None


def _session_out(s: ChatSession) -> dict:
    return {
        "id": s.id, "repo_id": s.repo_id, "title": s.title,
        "created_at": s.created_at.isoformat(), "updated_at": s.updated_at.isoformat(),
    }


def _message_out(m: ChatMessage) -> dict:
    return {
        "id": m.id, "session_id": m.session_id, "role": m.role,
        "content": m.content, "meta": m.meta or {}, "created_at": m.created_at.isoformat(),
    }


@router.get("/")
async def list_sessions(repo_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ChatSession).where(ChatSession.repo_id == repo_id).order_by(ChatSession.updated_at.desc())
    )
    return [_session_out(s) for s in result.scalars()]


@router.post("/")
async def create_session(req: CreateSessionRequest, db: AsyncSession = Depends(get_db)):
    session = ChatSession(id=str(uuid.uuid4()), repo_id=req.repo_id, title=req.title or "")
    db.add(session)
    await db.commit()
    return _session_out(session)


@router.get("/{session_id}/messages")
async def get_session_messages(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
    )
    return [_message_out(m) for m in result.scalars()]


@router.delete("/{session_id}")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404)
    msgs = await db.execute(select(ChatMessage).where(ChatMessage.session_id == session_id))
    for m in msgs.scalars():
        await db.delete(m)
    await db.delete(session)
    await db.commit()
    return {"deleted": session_id}
