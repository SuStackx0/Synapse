import os
import shutil
import uuid
from pathlib import Path
from core.config import settings
import structlog

logger = structlog.get_logger()


async def clone_local(source_path: str) -> tuple[str, str]:
    """Copy a local repo into the managed repos directory. Returns (repo_id, dest_path)."""
    if not os.path.isdir(source_path):
        raise ValueError(f"Path does not exist: {source_path}")

    repo_id = str(uuid.uuid4())
    dest = os.path.join(settings.repos_base_path, repo_id)
    shutil.copytree(source_path, dest, symlinks=False, ignore_dangling_symlinks=True)
    logger.info("local_copied", src=source_path, dest=dest, repo_id=repo_id)
    return repo_id, dest
