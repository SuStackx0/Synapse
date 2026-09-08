import git
from pathlib import Path
from typing import List, Dict, Any
import structlog

logger = structlog.get_logger()


def get_commit_history(repo_path: str, max_commits: int = 200) -> List[Dict[str, Any]]:
    try:
        repo = git.Repo(repo_path)
    except git.InvalidGitRepositoryError:
        logger.warning("not_a_git_repo", path=repo_path)
        return []

    commits = []
    for commit in list(repo.iter_commits("HEAD", max_count=max_commits)):
        diff_text = ""
        try:
            if commit.parents:
                diffs = commit.parents[0].diff(commit, create_patch=True)
                diff_text = "\n".join(
                    d.diff.decode("utf-8", errors="ignore")[:1000]
                    for d in diffs
                )[:3000]
        except Exception:
            pass

        commits.append({
            "sha": commit.hexsha[:8],
            "full_sha": commit.hexsha,
            "message": commit.message.strip(),
            "author": str(commit.author),
            "date": commit.committed_datetime.isoformat(),
            "files_changed": [item.a_path for item in commit.stats.files],
            "diff_preview": diff_text,
        })
    return commits


def build_commit_chunks(commits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten commits into embeddable text chunks."""
    chunks = []
    for c in commits:
        text = f"Commit {c['sha']}: {c['message']}\nFiles: {', '.join(c['files_changed'][:10])}\n{c['diff_preview']}"
        chunks.append({"text": text, "meta": c})
    return chunks
