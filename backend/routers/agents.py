from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Literal
import json, time

from core.database import get_db
from agents.graph import build_agent_graph, AgentState
from agents.llm_factory import get_active_llm
from langchain.schema import HumanMessage

router = APIRouter(prefix="/agents", tags=["agents"])


class ChatRequest(BaseModel):
    repo_id: str
    message: str
    agent_type: Literal["qa", "debug", "review"] = "qa"
    history: list[dict] = []


@router.post("/chat")
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    llm = await get_active_llm(db)
    graph = build_agent_graph(llm)

    messages = [HumanMessage(content=req.message)]
    state: AgentState = {
        "messages": messages,
        "repo_id": req.repo_id,
        "agent_type": req.agent_type,
        "context_chunks": [],
    }

    async def stream_response():
        result = await graph.ainvoke(state)
        ai_messages = [m for m in result["messages"] if hasattr(m, "content") and m != messages[0]]
        content = ai_messages[-1].content if ai_messages else "No response generated."
        yield f"data: {json.dumps({'content': content, 'done': True})}\n\n"

    return StreamingResponse(stream_response(), media_type="text/event-stream")


class BenchmarkRequest(BaseModel):
    repo_id: str
    query: str
    provider_a_id: str
    provider_b_id: str


@router.post("/benchmark")
async def benchmark(req: BenchmarkRequest, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    from core.models import LLMProvider, BenchmarkResult
    from agents.llm_factory import build_llm_from_provider
    from agents.graph import build_agent_graph, AgentState
    from langchain.schema import HumanMessage
    import uuid

    async def run_one(provider_id: str):
        result = await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
        provider = result.scalar_one_or_none()
        if not provider:
            return "", 0.0
        llm = build_llm_from_provider(provider)
        graph = build_agent_graph(llm)
        state: AgentState = {
            "messages": [HumanMessage(content=req.query)],
            "repo_id": req.repo_id,
            "agent_type": "qa",
            "context_chunks": [],
        }
        t0 = time.time()
        out = await graph.ainvoke(state)
        latency = time.time() - t0
        ai_msgs = [m for m in out["messages"] if hasattr(m, "content") and m.content != req.query]
        return ai_msgs[-1].content if ai_msgs else "", latency

    resp_a, lat_a = await run_one(req.provider_a_id)
    resp_b, lat_b = await run_one(req.provider_b_id)

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
    from sqlalchemy import select
    from core.models import BenchmarkResult
    result = await db.execute(select(BenchmarkResult).where(BenchmarkResult.id == bench_id))
    bench = result.scalar_one_or_none()
    if bench:
        bench.winner = winner
        await db.commit()
    return {"ok": True}
