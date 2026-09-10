from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Literal, Optional
import json, time, asyncio, uuid

from core.database import get_db, SessionLocal
from core.models import Repository, ChatSession, ChatMessage
from agents.graph import build_agent_graph, initial_state, invalidate_repo_map
from agents.llm_factory import get_active_llm
from langchain_core.messages import HumanMessage, AIMessage
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/agents", tags=["agents"])


class ChatRequest(BaseModel):
    repo_id: str
    message: str
    session_id: Optional[str] = None
    agent_type: Optional[Literal["qa", "debug", "review"]] = None


async def _reindex_after_write(repo_id: str, repo_root: str):
    """Background reindex so the next query answers from the updated graph."""
    from ingestion.ast_parser import walk_repo
    from ingestion.graph_builder import graph_builder
    from ingestion.embedder import embedder
    try:
        parsed = await asyncio.get_event_loop().run_in_executor(None, walk_repo, repo_root)
        await graph_builder.build_graph(repo_id, parsed)
        await embedder.index_symbols(repo_id, parsed)
        logger.info("reindexed_after_write", repo_id=repo_id, files=len(parsed))
    except Exception as e:
        logger.error("reindex_after_write_failed", repo_id=repo_id, error=str(e))


async def _persist_message(session_id: str, role: str, content: str, meta: dict):
    """Own DB session — called both inline and from the streaming generator."""
    async with SessionLocal() as db:
        db.add(ChatMessage(id=str(uuid.uuid4()), session_id=session_id, role=role,
                            content=content, meta=meta))
        result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
        session = result.scalar_one_or_none()
        if session:
            from datetime import datetime
            session.updated_at = datetime.utcnow()
        await db.commit()


@router.post("/chat")
async def chat(req: ChatRequest, bg: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Repository).where(Repository.id == req.repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(404, "Repo not found")

    # Resolve or create the session, then load its prior turns so follow-up
    # questions ("what about the other file", "now add tests for that") have
    # the conversation to work from — not just the latest message in isolation.
    session_id = req.session_id
    is_new_session = False
    if session_id:
        sresult = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
        session = sresult.scalar_one_or_none()
        if not session:
            session_id = None
    if not session_id:
        session = ChatSession(id=str(uuid.uuid4()), repo_id=req.repo_id, title=req.message[:60])
        db.add(session)
        await db.commit()
        session_id = session.id
        is_new_session = True

    history_messages = []
    if not is_new_session:
        mresult = await db.execute(
            select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
        )
        for m in mresult.scalars():
            if m.role == "user":
                history_messages.append(HumanMessage(content=m.content))
            else:
                history_messages.append(AIMessage(content=m.content))

    await _persist_message(session_id, "user", req.message, {})

    llm = await get_active_llm(db)
    graph = build_agent_graph(llm)

    messages = [*history_messages, HumanMessage(content=req.message)]
    state = initial_state(
        messages, repo_id=req.repo_id, repo_root=repo.path,
        agent_type=req.agent_type or "qa", auto_apply=True,
    )

    async def stream_response():
        yield f"data: {json.dumps({'event': 'session', 'session_id': session_id, 'is_new': is_new_session})}\n\n"
        yield f"data: {json.dumps({'event': 'retrieval_start'})}\n\n"

        seen_progress = 0
        mode_sent = False
        final_state = state

        try:
            async for mode_name, payload in graph.astream(state, stream_mode=["values", "custom"]):
                if mode_name == "custom":
                    # Token-level progress from inside the coder node (get_stream_writer) —
                    # this is what lets the UI show growing char/line counts while a file
                    # is still being generated, instead of a spinner frozen for 20s.
                    yield f"data: {json.dumps(payload)}\n\n"
                    continue

                snapshot = payload
                final_state = snapshot

                # Live "which node just ran" signal — the Claude-Code-style step trail.
                stage = snapshot.get("mode") or "routing"
                if snapshot.get("clarifying_question"):
                    stage = "clarifying"
                elif snapshot.get("plan") and not snapshot.get("write_results"):
                    stage = "planning"
                elif snapshot.get("_pending_writes") is not None and not snapshot.get("write_results"):
                    stage = "coding"
                elif snapshot.get("write_results"):
                    stage = "applying"
                elif snapshot.get("context_sgl") and snapshot.get("mode") == "read":
                    stage = "retrieving"
                yield f"data: {json.dumps({'event': 'step', 'stage': stage})}\n\n"

                if not mode_sent and snapshot.get("mode"):
                    mode_sent = True
                    yield f"data: {json.dumps({'event': 'mode', 'mode': snapshot.get('mode'), 'agent_type': snapshot.get('agent_type'), 'decided_by': snapshot.get('mode_decided_by')})}\n\n"

                # Replay any new progress events (context_ready / plan_ready /
                # writing_file / file_written / implement_done / clarify) as they land.
                prog = snapshot.get("progress", [])
                for evt in prog[seen_progress:]:
                    yield f"data: {json.dumps(evt)}\n\n"
                seen_progress = len(prog)
        except Exception as e:
            logger.error("agent_stream_failed", repo_id=req.repo_id, error=str(e), exc_info=True)
            err_content = f"Something went wrong while processing this: {e}"
            yield f"data: {json.dumps({'event': 'answer', 'content': err_content, 'done': True})}\n\n"
            await _persist_message(session_id, "assistant", err_content, {"error": True})
            return

        result = final_state
        mode = result.get("mode", "read")
        is_clarifying = bool(result.get("clarifying_question"))

        if mode == "write" and result.get("files_written"):
            bg.add_task(_reindex_after_write, req.repo_id, repo.path)
            invalidate_repo_map(req.repo_id)

        retrieval_meta = {}
        if result.get("retrieval_trace"):
            trace = result.get("retrieval_trace", [])
            anchors = result.get("anchors", [])
            intent = result.get("intent", "semantic")
            has_commits = bool(result.get("commit_context"))
            coverage = result.get("coverage", "")
            retrieval_meta = {"anchors": anchors, "intent": intent, "has_commits": has_commits,
                               "coverage": coverage, "trace": trace}
            yield f"data: {json.dumps({'event': 'retrieval_done', **retrieval_meta})}\n\n"

        ai_messages = [m for m in result["messages"] if hasattr(m, "content") and m.content != req.message]
        content = ai_messages[-1].content if ai_messages else "No response generated."
        yield f"data: {json.dumps({'event': 'answer', 'content': content, 'done': True})}\n\n"

        meta = {
            "mode": mode, "is_clarifying": is_clarifying,
            "retrieval": retrieval_meta or None,
            "write_results": result.get("write_results") or None,
            "plan_summary": result.get("plan_summary") or None,
            "placement_dir": result.get("placement_dir") or None,
        }
        await _persist_message(session_id, "assistant", content, meta)

    return StreamingResponse(stream_response(), media_type="text/event-stream")


class BenchmarkRequest(BaseModel):
    repo_id: str
    query: str
    provider_a_id: str
    provider_b_id: str


@router.post("/benchmark")
async def benchmark(req: BenchmarkRequest, db: AsyncSession = Depends(get_db)):
    from core.models import LLMProvider, BenchmarkResult
    from agents.llm_factory import build_llm_from_provider

    repo_result = await db.execute(select(Repository).where(Repository.id == req.repo_id))
    repo = repo_result.scalar_one_or_none()
    repo_root = repo.path if repo else ""

    async def run_one(provider_id: str):
        result = await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
        provider = result.scalar_one_or_none()
        if not provider:
            return "", 0.0
        llm = build_llm_from_provider(provider)
        graph = build_agent_graph(llm)
        state = initial_state([HumanMessage(content=req.query)], repo_id=req.repo_id, repo_root=repo_root)
        t0 = time.time()
        out = await graph.ainvoke(state)
        latency = time.time() - t0
        ai_msgs = [m for m in out["messages"] if hasattr(m, "content") and m.content != req.query]
        return (ai_msgs[-1].content if ai_msgs else ""), latency

    (resp_a, lat_a), (resp_b, lat_b) = await asyncio.gather(
        run_one(req.provider_a_id),
        run_one(req.provider_b_id),
    )

    bench = BenchmarkResult(
        id=str(uuid.uuid4()),
        repo_id=req.repo_id,
        query=req.query,
        provider_a_id=req.provider_a_id,
        provider_b_id=req.provider_b_id,
        response_a=resp_a,
        response_b=resp_b,
        latency_a=lat_a,
        latency_b=lat_b,
    )
    db.add(bench)
    await db.commit()
    return {
        "id": bench.id,
        "response_a": resp_a,
        "response_b": resp_b,
        "latency_a": round(lat_a, 2),
        "latency_b": round(lat_b, 2),
    }


@router.post("/benchmark/{bench_id}/vote")
async def vote(bench_id: str, winner: Literal["a", "b"], db: AsyncSession = Depends(get_db)):
    from core.models import BenchmarkResult
    result = await db.execute(select(BenchmarkResult).where(BenchmarkResult.id == bench_id))
    bench = result.scalar_one_or_none()
    if bench:
        bench.winner = winner
        await db.commit()
    return {"ok": True}
