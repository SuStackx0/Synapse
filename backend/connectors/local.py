import os
import shutil
import uuid
from pathlib import Path
from core.config import settings
import structlog

logger = structlog.get_logger()


async def clone_local(source_path: str, in_place: bool = False) -> tuple[str, str]:
    """
    Copy a local repo into the managed repos directory, or (if in_place)
    index a bind-mounted path directly so writes from the implement agent
    land on the real host filesystem instead of a throwaway copy.
    Returns (repo_id, dest_path).
    """
    if not os.path.isdir(source_path):
        raise ValueError(f"Path does not exist: {source_path}")

    if in_place:
        repo_id = str(uuid.uuid4())
        logger.info("local_in_place", path=source_path, repo_id=repo_id)
        return repo_id, source_path

    repo_id = str(uuid.uuid4())
    dest = os.path.join(settings.repos_base_path, repo_id)
    shutil.copytree(source_path, dest, symlinks=False, ignore_dangling_symlinks=True)
    logger.info("local_copied", src=source_path, dest=dest, repo_id=repo_id)
    return repo_id, dest
