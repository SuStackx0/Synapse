import os
import uuid
import subprocess
from core.config import settings
import structlog

logger = structlog.get_logger()


async def clone_github(repo_url: str, pat: str) -> tuple[str, str]:
    """Clone a GitHub repo using a PAT. Returns (repo_id, dest_path)."""
    repo_id = str(uuid.uuid4())
    dest = os.path.join(settings.repos_base_path, repo_id)
    os.makedirs(dest, exist_ok=True)

    # Inject PAT into URL for auth
    if repo_url.startswith("https://"):
        authed_url = repo_url.replace("https://", f"https://x-access-token:{pat}@")
    else:
        authed_url = repo_url

    result = subprocess.run(
        ["git", "clone", "--depth", "50", authed_url, dest],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git clone failed: {result.stderr}")

    logger.info("github_cloned", url=repo_url, dest=dest, repo_id=repo_id)
    return repo_id, dest
