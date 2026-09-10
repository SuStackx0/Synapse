"""
Autonomous project scaffolding.

Reuses the exact same graph-guided planner -> coder -> apply pipeline that
powers a single "implement X" chat turn, just called directly in a loop
instead of through the classify/route machinery (there's nothing to
classify — every iteration here is unconditionally a write). Each
iteration re-indexes before the next one plans, so iteration N+1 sees
everything iteration N actually wrote (via the graph, not just a diff),
the same way a human continuing their own work would.

Stops when the planner itself reports there's nothing left to add (empty
plan) twice in a row, or after max_iterations as a hard backstop.
"""
import asyncio
import uuid
from datetime import datetime
from typing import Optional

from langchain_core.messages import HumanMessage
import structlog

from agents.graph import (
    initial_state, plan_context, make_planner_node, make_coder_node, apply_writes,
    invalidate_repo_map,
)
from agents.llm_factory import get_active_llm
from core.database import SessionLocal
from core.models import Repository, ChatSession, ChatMessage
from ingestion.ast_parser import walk_repo
from ingestion.graph_builder import graph_builder
from ingestion.embedder import embedder
from sqlalchemy import select

logger = structlog.get_logger()


async def _set_status(repo_id: str, stage: str, detail: str, pct: Optional[int] = None):
    async with SessionLocal() as db:
        result = await db.execute(select(Repository).where(Repository.id == repo_id))
        repo = result.scalar_one_or_none()
        if not repo:
            return
        repo.indexing_stage = stage
        repo.indexing_detail = detail
        if pct is not None:
            repo.indexing_pct = pct
        if stage == "done":
            repo.indexed = True
        await db.commit()


async def _create_build_session(repo_id: str, repo_name: str) -> str:
    """A dedicated, persisted chat session for this build — every iteration lands in
    it as a real turn, so opening the repo's Ask AI tab shows the exact same
    ActivityFeed/WritePanel step-by-step view a manual implement turn gets, instead
    of only the coarse progress bar on the homepage card."""
    session_id = str(uuid.uuid4())
    async with SessionLocal() as db:
        db.add(ChatSession(id=session_id, repo_id=repo_id, title=f"Building {repo_name}"))
        result = await db.execute(select(Repository).where(Repository.id == repo_id))
        repo = result.scalar_one_or_none()
        if repo:
            repo.meta = {**(repo.meta or {}), "build_session_id": session_id}
        await db.commit()
    return session_id


async def _persist_turn(session_id: str, query: str, content: str, meta: dict):
    async with SessionLocal() as db:
        db.add(ChatMessage(id=str(uuid.uuid4()), session_id=session_id, role="user", content=query, meta={}))
        db.add(ChatMessage(id=str(uuid.uuid4()), session_id=session_id, role="assistant", content=content, meta=meta))
        result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
        session = result.scalar_one_or_none()
        if session:
            session.updated_at = datetime.utcnow()
        await db.commit()


async def _reindex(repo_id: str, repo_root: str) -> int:
    parsed = await asyncio.get_event_loop().run_in_executor(None, walk_repo, repo_root)
    await graph_builder.build_graph(repo_id, parsed)
    await embedder.index_symbols(repo_id, parsed)
    invalidate_repo_map(repo_id)
    async with SessionLocal() as db:
        result = await db.execute(select(Repository).where(Repository.id == repo_id))
        repo = result.scalar_one_or_none()
        if repo:
            repo.file_count = len(parsed)
            await db.commit()
    return len(parsed)


async def run_autonomous_build(repo_id: str, repo_root: str, description: str, max_iterations: int = 10):
    try:
        async with SessionLocal() as db:
            llm = await get_active_llm(db)
    except Exception as e:
        logger.error("autobuild_no_llm", repo_id=repo_id, error=str(e))
        await _set_status(repo_id, "error", "No LLM provider configured")
        return

    planner_node = make_planner_node(llm)
    coder_node = make_coder_node(llm)

    async with SessionLocal() as db:
        result = await db.execute(select(Repository).where(Repository.id == repo_id))
        repo_row = result.scalar_one_or_none()
        repo_name = repo_row.name if repo_row else repo_id

    build_session_id = await _create_build_session(repo_id, repo_name)

    await _set_status(repo_id, "building", "Starting from an empty project…", pct=2)
    await _reindex(repo_id, repo_root)

    consecutive_empty = 0
    files_written_total = 0

    for i in range(max_iterations):
        pct = min(95, 5 + int((i / max_iterations) * 90))

        if i == 0:
            query = (
                f"Set up the initial project from scratch. Goal: {description}\n\n"
                "Create the core file/directory structure, a README describing the project, "
                "a dependency/config file appropriate for the stack this goal implies, a runnable "
                "entry point, and — if the goal involves storing data — a SQLite-backed data layer "
                "(schema + a thin data-access module). Keep the first pass minimal but real: it "
                "should run, not just look like a project."
            )
        else:
            query = (
                f"Continue building this project. Goal: {description}\n\n"
                "The repo map above shows what exists so far. Add the single most important "
                "missing piece — a core feature, the data layer, error handling, tests, or docs — "
                "whichever is the biggest gap toward a genuinely complete, working project. "
                "If the project already fully satisfies the goal and nothing meaningful is left "
                "to add, respond with the JSON plan form containing an empty files list."
            )

        try:
            state = initial_state([HumanMessage(content=query)], repo_id=repo_id, repo_root=repo_root, auto_apply=True)
            state["mode"] = "write"

            await _set_status(repo_id, "building", f"Iteration {i + 1}/{max_iterations}: planning…", pct=pct)
            state = await plan_context(state)
            state = await planner_node(state)

            plan = state.get("plan") or []
            if not plan:
                consecutive_empty += 1
                logger.info("autobuild_empty_plan", repo_id=repo_id, iteration=i, consecutive=consecutive_empty)
                if consecutive_empty >= 2:
                    break
                continue
            consecutive_empty = 0

            await _set_status(repo_id, "building", f"Iteration {i + 1}: writing {len(plan)} file(s)…", pct=pct)
            state = await coder_node(state)
            state = await apply_writes(state)

            written = state.get("files_written") or []
            write_results = state.get("write_results") or []
            files_written_total += len(written)
            logger.info("autobuild_iteration_done", repo_id=repo_id, iteration=i,
                        files_written=written, errors=state.get("write_errors"))

            summary_lines = [f"**Iteration {i + 1}: {state.get('plan_summary') or 'implementing the next piece'}**\n"]
            if write_results:
                summary_lines.append("Files written:")
                for res in write_results:
                    if res.get("applied"):
                        summary_lines.append(f"- `{res['rel_path']}` ({res['op']}, +{res['added']}/-{res['removed']} lines)")
                    elif res.get("error"):
                        summary_lines.append(f"- `{res['rel_path']}` failed — {res['error']}")
            await _persist_turn(
                build_session_id, query, "\n".join(summary_lines),
                {
                    "mode": "write", "is_clarifying": False, "retrieval": None,
                    "write_results": write_results or None,
                    "plan_summary": state.get("plan_summary") or None,
                    "placement_dir": state.get("placement_dir") or None,
                },
            )

            if written:
                await _set_status(repo_id, "building", f"Iteration {i + 1}: reindexing…", pct=pct)
                await _reindex(repo_id, repo_root)
        except Exception as e:
            logger.error("autobuild_iteration_failed", repo_id=repo_id, iteration=i, error=str(e), exc_info=True)
            break

    await _reindex(repo_id, repo_root)
    final_detail = f"Scaffolded {files_written_total} file(s) across {min(max_iterations, i + 1)} iterations"
    await _set_status(repo_id, "done", final_detail, pct=100)
    await _persist_turn(
        build_session_id, "(build complete)", f"**Build complete.** {final_detail}.",
        {"mode": "write", "is_clarifying": False, "retrieval": None,
         "write_results": None, "plan_summary": None, "placement_dir": None},
    )
    logger.info("autobuild_complete", repo_id=repo_id, total_files_written=files_written_total)
