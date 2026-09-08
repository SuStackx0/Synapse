from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import uuid, os

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


class GitHubRepoRequest(BaseModel):
    url: str
    pat: str
    name: Optional[str] = None


async def _index_repo(repo_id: str, repo_path: str):
    """Background task with its own DB session — not request-scoped."""
    async with SessionLocal() as db:
        try:
            parsed = walk_repo(repo_path)
            # Build Neo4j call graph (structure + all doc text)
            await graph_builder.build_graph(repo_id, parsed)
            # Embed prose only — docstrings, signatures, no raw code
            await embedder.index_symbols(repo_id, parsed)
            # Embed commit messages only (not diffs)
            commits = get_commit_history(repo_path)
            await embedder.index_commits(repo_id, commits)

            result = await db.execute(select(Repository).where(Repository.id == repo_id))
            repo = result.scalar_one_or_none()
            if repo:
                repo.indexed = True
                repo.file_count = len(parsed)
                await db.commit()

            logger.info("repo_indexed", repo_id=repo_id, files=len(parsed), commits=len(commits))
        except Exception as e:
            logger.error("index_failed", repo_id=repo_id, error=str(e), exc_info=True)


@router.post("/local")
async def add_local_repo(req: LocalRepoRequest, bg: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    repo_id, dest_path = await clone_local(req.path)
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


@router.get("/")
async def list_repos(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Repository))
    return [
        {"id": r.id, "name": r.name, "source": r.source,
         "indexed": r.indexed, "file_count": r.file_count,
         "created_at": r.created_at.isoformat()}
        for r in result.scalars()
    ]


@router.get("/{repo_id}")
async def get_repo(repo_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(404, "Repo not found")
    return {
        "id": repo.id, "name": repo.name, "source": repo.source,
        "indexed": repo.indexed, "file_count": repo.file_count,
        "language": repo.language, "created_at": repo.created_at.isoformat(),
    }


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
