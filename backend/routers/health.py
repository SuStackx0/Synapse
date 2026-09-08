from fastapi import APIRouter, HTTPException
from ingestion.ast_parser import walk_repo
from ingestion.graph_builder import graph_builder
from core.models import Repository
from core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import Depends
import os
from pathlib import Path

router = APIRouter(prefix="/health", tags=["health"])

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}


def _compute_health(repo_path: str, parsed_files: list) -> dict:
    total_files = len(parsed_files)
    total_lines = sum(len(f.get("content", "").splitlines()) for f in parsed_files)
    total_functions = sum(len(f.get("functions", [])) for f in parsed_files)
    total_classes = sum(len(f.get("classes", [])) for f in parsed_files)

    # Complexity: files with >300 lines
    large_files = [
        {"file": f.get("rel_path", "?"), "lines": len(f.get("content", "").splitlines())}
        for f in parsed_files
        if len(f.get("content", "").splitlines()) > 300
    ]

    # Dead code estimate: functions with no name reuse across other files
    all_calls = set()
    for f in parsed_files:
        all_calls.update(f.get("calls", []))
    all_functions = [
        {"name": fn["name"], "file": f.get("rel_path", "?")}
        for f in parsed_files
        for fn in f.get("functions", [])
    ]
    potentially_dead = [
        fn for fn in all_functions
        if fn["name"] not in all_calls and not fn["name"].startswith("_")
        and fn["name"] not in {"main", "test", "setup", "teardown"}
    ][:20]

    # Language breakdown
    lang_counts: dict = {}
    for f in parsed_files:
        lang = f.get("language", "unknown")
        lang_counts[lang] = lang_counts.get(lang, 0) + 1

    # Circular import detection (simple: mutual imports)
    import_map: dict = {}
    for f in parsed_files:
        import_map[f.get("rel_path", "")] = f.get("imports", [])

    score = 100
    if large_files:
        score -= min(20, len(large_files) * 3)
    if potentially_dead:
        score -= min(15, len(potentially_dead) * 1)
    score = max(0, score)

    return {
        "score": score,
        "total_files": total_files,
        "total_lines": total_lines,
        "total_functions": total_functions,
        "total_classes": total_classes,
        "large_files": large_files[:10],
        "potentially_dead_functions": potentially_dead[:10],
        "language_breakdown": lang_counts,
    }


@router.get("/{repo_id}")
async def get_health(repo_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(404, "Repo not found")
    if not repo.indexed:
        raise HTTPException(400, "Repo not yet indexed")

    parsed = walk_repo(repo.path)
    return _compute_health(repo.path, parsed)
