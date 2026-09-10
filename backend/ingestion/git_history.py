import os
import subprocess
from typing import List, Dict, Any
import structlog

logger = structlog.get_logger()

_SEP = "\x1f"   # unit separator — won't appear in commit messages
_REC = "\x1e"   # record separator


def get_commit_history(repo_path: str, max_commits: int = 200, timeout: int = 15) -> List[Dict[str, Any]]:
    """
    Commit metadata for embedding — messages only, no per-commit file diffing.

    Deliberately avoids `git log --name-only` (and GitPython's equivalent
    commit.diff()/commit.stats): reproduced hangs on real repos where a
    commit touches a large/binary file (a checked-in .db, a lockfile) —
    the file-list diff computation for that one commit can hang the whole
    walk indefinitely. Commit messages are what actually get embedded, so
    skip the diff machinery entirely rather than risk indexing hanging on it.
    """
    env = {
        **os.environ,
        "GIT_PAGER": "cat", "GIT_TERMINAL_PROMPT": "0",
        # Stale/foreign worktree registrations (.git/worktrees/*) make git
        # probe lock files that can hang indefinitely without this.
        "GIT_OPTIONAL_LOCKS": "0",
    }
    fmt = f"{_REC}%H{_SEP}%h{_SEP}%an{_SEP}%aI{_SEP}%s"

    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "--no-pager", "log",
             f"--pretty=format:{fmt}", f"-{max_commits}", "HEAD"],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        logger.warning("commit_history_timeout", path=repo_path)
        return []
    except FileNotFoundError:
        return []

    if result.returncode != 0:
        logger.warning("not_a_git_repo", path=repo_path, stderr=result.stderr[:200])
        return []

    commits = []
    for block in result.stdout.split(_REC):
        block = block.strip("\n")
        if not block:
            continue
        parts = block.split(_SEP)
        if len(parts) != 5:
            continue
        full_sha, sha, author, date, message = parts
        commits.append({
            "sha": sha,
            "full_sha": full_sha,
            "message": message.strip(),
            "author": author,
            "date": date,
            "files_changed": [],
            "diff_preview": "",
        })
    return commits


def build_commit_chunks(commits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten commits into embeddable text chunks."""
    chunks = []
    for c in commits:
        text = f"Commit {c['sha']}: {c['message']}"
        chunks.append({"text": text, "meta": c})
    return chunks
