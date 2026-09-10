from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import uuid, os, asyncio

from core.config import settings
from core.database import get_db, SessionLocal
from core.models import Repository
from ingestion.ast_parser import walk_repo
from ingestion.graph_builder import graph_builder
from ingestion.embedder import embedder
from ingestion.git_history import get_commit_history
from connectors.local import clone_local
from connectors.github import clone_github
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/repos", tags=["repos"])


class LocalRepoRequest(BaseModel):
    path: str
    name: Optional[str] = None
    in_place: bool = False


class GitHubRepoRequest(BaseModel):
    url: str
    pat: str
    name: Optional[str] = None


class NewProjectRequest(BaseModel):
    name: str
    description: str
    in_place: bool = False
    path: Optional[str] = None  # required when in_place=True — where to create it


# Checkpoint stages, in order, with their target completion percentage —
# shown in the UI so the user knows how much longer indexing will take.
STAGES = [
    ("walking", "Parsing source files", 15),
    ("graph", "Building call graph in Neo4j", 45),
    ("embedding_symbols", "Embedding symbols in Qdrant", 80),
    ("embedding_commits", "Indexing commit history", 95),
    ("done", "Indexed", 100),
]


async def _set_stage(repo_id: str, stage: str, detail: str = "", pct: Optional[int] = None, error: str = ""):
    async with SessionLocal() as db:
        result = await db.execute(select(Repository).where(Repository.id == repo_id))
        repo = result.scalar_one_or_none()
        if not repo:
            return
        repo.indexing_stage = stage
        repo.indexing_detail = detail
        if pct is not None:
            repo.indexing_pct = pct
        if error:
            repo.indexing_error = error
        if stage == "done":
            repo.indexed = True
        await db.commit()


async def _index_repo(repo_id: str, repo_path: str):
    """Background task with its own DB session — not request-scoped. Reports
    checkpoint progress at each stage so the UI can show real status instead
    of an indefinite spinner."""
    try:
        _, _, pct = STAGES[0]
        await _set_stage(repo_id, "walking", "Parsing source files", pct)
        # CPU-bound AST walk — off the event loop, or it blocks every other request
        parsed = await asyncio.get_event_loop().run_in_executor(None, walk_repo, repo_path)

        _, _, pct = STAGES[1]
        await _set_stage(repo_id, "graph", f"Building call graph ({len(parsed)} files)", pct)
        await graph_builder.build_graph(repo_id, parsed)

        _, _, pct = STAGES[2]
        n_symbols = sum(len(f.get("functions", [])) + len(f.get("classes", [])) for f in parsed)
        await _set_stage(repo_id, "embedding_symbols", f"Embedding {n_symbols} symbols", pct)
        await embedder.index_symbols(repo_id, parsed)

        _, _, pct = STAGES[3]
        await _set_stage(repo_id, "embedding_commits", "Indexing commit history", pct)
        commits = await asyncio.get_event_loop().run_in_executor(None, get_commit_history, repo_path)
        await embedder.index_commits(repo_id, commits)

        async with SessionLocal() as db:
            result = await db.execute(select(Repository).where(Repository.id == repo_id))
            repo = result.scalar_one_or_none()
            if repo:
                repo.file_count = len(parsed)
                await db.commit()

        _, _, pct = STAGES[4]
        await _set_stage(repo_id, "done", f"{len(parsed)} files indexed", pct)
        logger.info("repo_indexed", repo_id=repo_id, files=len(parsed), commits=len(commits))
    except Exception as e:
        logger.error("index_failed", repo_id=repo_id, error=str(e), exc_info=True)
        await _set_stage(repo_id, "error", "Indexing failed", error=str(e)[:300])


@router.post("/local")
async def add_local_repo(req: LocalRepoRequest, bg: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    repo_id, dest_path = await clone_local(req.path, in_place=req.in_place)
    name = req.name or os.path.basename(req.path.rstrip("/"))
    repo = Repository(id=repo_id, name=name, path=dest_path, source="local")
    db.add(repo)
    await db.commit()
    bg.add_task(_index_repo, repo_id, dest_path)
    return {"repo_id": repo_id, "name": name, "status": "indexing"}


@router.post("/github")
async def add_github_repo(req: GitHubRepoRequest, bg: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    repo_id, dest_path = await clone_github(req.url, req.pat)
    name = req.name or req.url.rstrip("/").split("/")[-1].replace(".git", "")
    repo = Repository(id=repo_id, name=name, path=dest_path, source="github",
                      meta={"url": req.url})
    db.add(repo)
    await db.commit()
    bg.add_task(_index_repo, repo_id, dest_path)
    return {"repo_id": repo_id, "name": name, "status": "indexing"}


@router.post("/new")
async def create_new_project(req: NewProjectRequest, bg: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """
    Start a project from nothing — no local path, no GitHub URL. Creates an
    empty (git-initialized) directory, registers it as a Repository, then
    autonomously builds it out via the same graph-guided implement pipeline
    used for a single "implement X" chat turn, looped until the planner
    itself says there's nothing meaningful left to add.
    """
    import subprocess

    repo_id = str(uuid.uuid4())
    if req.in_place:
        if not req.path:
            raise HTTPException(400, "path is required when in_place is true")
        dest = req.path
    else:
        dest = os.path.join(settings.repos_base_path, repo_id)
    os.makedirs(dest, exist_ok=True)

    readme = os.path.join(dest, "README.md")
    if not os.path.exists(readme):
        with open(readme, "w", encoding="utf-8") as fh:
            fh.write(f"# {req.name}\n\n{req.description}\n")

    if not os.path.isdir(os.path.join(dest, ".git")):
        subprocess.run(["git", "init"], cwd=dest, capture_output=True, timeout=10)

    repo = Repository(
        id=repo_id, name=req.name, path=dest, source="new",
        meta={"description": req.description},
        indexing_stage="building", indexing_detail="Queued…", indexing_pct=0,
    )
    db.add(repo)
    await db.commit()

    from agents.autobuild import run_autonomous_build
    bg.add_task(run_autonomous_build, repo_id, dest, req.description)
    return {"repo_id": repo_id, "name": req.name, "status": "building"}


def _serialize(r: Repository) -> dict:
    return {
        "id": r.id, "name": r.name, "source": r.source,
        "indexed": r.indexed, "file_count": r.file_count,
        "created_at": r.created_at.isoformat(),
        "indexing_stage": r.indexing_stage,
        "indexing_detail": r.indexing_detail,
        "indexing_pct": r.indexing_pct,
        "indexing_error": r.indexing_error,
        "build_session_id": (r.meta or {}).get("build_session_id"),
    }


@router.get("/")
async def list_repos(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Repository))
    return [_serialize(r) for r in result.scalars()]


@router.get("/{repo_id}")
async def get_repo(repo_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(404, "Repo not found")
    return {**_serialize(repo), "language": repo.language, "path": repo.path}


class FileContentRequest(BaseModel):
    path: str
    content: str


@router.get("/{repo_id}/file")
async def get_file(repo_id: str, path: str, db: AsyncSession = Depends(get_db)):
    """Read a file's current content — powers the side-panel editor."""
    from agents.write_tool import safe_path, PathViolation

    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(404, "Repo not found")
    try:
        abs_path = safe_path(repo.path, path)
    except PathViolation as e:
        raise HTTPException(400, str(e))
    if not os.path.isfile(abs_path):
        raise HTTPException(404, "File not found")
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
    except Exception as e:
        raise HTTPException(500, f"Could not read file: {e}")
    return {"path": path, "content": content, "lines": content.count("\n") + 1}


@router.put("/{repo_id}/file")
async def save_file(repo_id: str, req: FileContentRequest, bg: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Save a user's manual edit from the side-panel editor straight to disk."""
    from agents.write_tool import safe_path, PathViolation
    from agents.graph import invalidate_repo_map
    import ast as _ast

    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(404, "Repo not found")
    try:
        abs_path = safe_path(repo.path, req.path)
    except PathViolation as e:
        raise HTTPException(400, str(e))

    if req.path.endswith(".py"):
        try:
            _ast.parse(req.content)
        except SyntaxError as e:
            raise HTTPException(400, f"Syntax error at line {e.lineno}: {e.msg}")

    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    tmp = abs_path + ".synapse.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(req.content)
    os.replace(tmp, abs_path)

    invalidate_repo_map(repo_id)
    bg.add_task(_reindex_single_file, repo_id, repo.path)
    logger.info("file_saved", repo_id=repo_id, path=req.path, bytes=len(req.content))
    return {"saved": req.path, "lines": req.content.count("\n") + 1}


async def _reindex_single_file(repo_id: str, repo_path: str):
    """Lightweight background reindex after a manual save from the editor panel."""
    try:
        parsed = await asyncio.get_event_loop().run_in_executor(None, walk_repo, repo_path)
        await graph_builder.build_graph(repo_id, parsed)
        await embedder.index_symbols(repo_id, parsed)
        logger.info("reindexed_after_manual_save", repo_id=repo_id, files=len(parsed))
    except Exception as e:
        logger.error("reindex_after_manual_save_failed", repo_id=repo_id, error=str(e))


@router.delete("/{repo_id}")
async def delete_repo(repo_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(404)
    await embedder.delete_collection(repo_id)
    await graph_builder.clear_repo(repo_id)
    await db.delete(repo)
    await db.commit()
    return {"deleted": repo_id}
