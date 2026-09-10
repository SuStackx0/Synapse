"""
File-write tool for the implement agent.

Contract: full-file content, not a unified diff. A local ~8-30B model
cannot reliably emit correct diff hunk headers; full-file output is a
single valid source file (the highest-probability shape for a code
model) and is verifiable before it ever touches disk via ast.parse.

Every write goes through safe_path() — the only function allowed to
turn a model-supplied rel_path into a real filesystem path.
"""
from pydantic import BaseModel
from typing import Literal, Optional
import ast
import difflib
import os
import shutil

ALLOWED_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md",
               ".yml", ".yaml", ".toml", ".txt", ".sql", ".css", ".env.example"}
DENY_PARTS = {".git", "node_modules", "__pycache__", ".venv", "venv",
              ".env", ".ssh", "dist", "build", ".next"}
MAX_BYTES = 256 * 1024


class PathViolation(Exception):
    pass


class FileWrite(BaseModel):
    rel_path: str
    op: Literal["create", "rewrite", "append"]
    content: str
    reason: str = ""


class WriteResult(BaseModel):
    rel_path: str
    op: str
    ok: bool
    applied: bool
    lines: int = 0
    added: int = 0
    removed: int = 0
    diff: str = ""
    error: Optional[str] = None


def safe_path(repo_root: str, rel_path: str) -> str:
    """Resolve rel_path inside repo_root or raise. The only path to the filesystem."""
    if not rel_path or os.path.isabs(rel_path) or "\x00" in rel_path:
        raise PathViolation(f"invalid path: {rel_path!r}")
    root = os.path.realpath(repo_root)
    cand = os.path.realpath(os.path.join(root, rel_path))
    if cand != root and not cand.startswith(root + os.sep):
        raise PathViolation(f"path escapes repo root: {rel_path!r}")
    rel_parts = set(os.path.relpath(cand, root).split(os.sep))
    if rel_parts & DENY_PARTS:
        raise PathViolation(f"path in deny list: {rel_path!r}")
    ext = os.path.splitext(cand)[1].lower()
    if ext and ext not in ALLOWED_EXT:
        raise PathViolation(f"extension not allowed: {rel_path!r}")
    return cand


def _read_or_none(repo_root: str, rel_path: str) -> Optional[str]:
    try:
        abs_path = safe_path(repo_root, rel_path)
    except PathViolation:
        return None
    if not os.path.exists(abs_path):
        return None
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except Exception:
        return None


def validate_write(repo_root: str, fw: FileWrite, original: Optional[str] = None) -> tuple[bool, Optional[str]]:
    try:
        abs_path = safe_path(repo_root, fw.rel_path)
    except PathViolation as e:
        return False, str(e)
    if len(fw.content.encode()) > MAX_BYTES:
        return False, "content exceeds size cap"
    if not fw.content.strip():
        return False, "empty content"
    if fw.rel_path.endswith(".py") and fw.op != "append":
        try:
            ast.parse(fw.content)
        except SyntaxError as e:
            return False, f"syntax error line {e.lineno}: {e.msg}"
    if fw.op == "create" and os.path.exists(abs_path):
        return False, "file exists (use rewrite)"
    if fw.op == "rewrite":
        if original is not None:
            old_n, new_n = len(original.splitlines()), len(fw.content.splitlines())
            if old_n >= 20 and new_n < old_n * 0.5:
                return False, f"suspected truncation: {old_n}L -> {new_n}L"
    return True, None


def preview_write(repo_root: str, fw: FileWrite) -> WriteResult:
    """Validate + produce a unified diff. Never touches disk."""
    old = _read_or_none(repo_root, fw.rel_path) or ""
    ok, err = validate_write(repo_root, fw, old if old else None)
    new = old + fw.content if fw.op == "append" else fw.content
    diff = "".join(difflib.unified_diff(
        old.splitlines(True), new.splitlines(True),
        fromfile=f"a/{fw.rel_path}", tofile=f"b/{fw.rel_path}", n=2))
    added = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
    return WriteResult(rel_path=fw.rel_path, op=fw.op, ok=ok, applied=False,
                        lines=len(new.splitlines()), added=added, removed=removed,
                        diff=diff[:8000], error=err)


def apply_write(repo_root: str, fw: FileWrite, backup: bool = True) -> WriteResult:
    """Validate, back up, write atomically. Returns applied=True on success."""
    res = preview_write(repo_root, fw)
    if not res.ok:
        return res
    abs_path = safe_path(repo_root, fw.rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    if backup and os.path.exists(abs_path):
        shutil.copy2(abs_path, abs_path + ".synapse.bak")
    tmp = abs_path + ".synapse.tmp"
    existing = _read_or_none(repo_root, fw.rel_path) or ""
    final = existing + fw.content if fw.op == "append" else fw.content
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(final)
    os.replace(tmp, abs_path)
    res.applied = True
    return res
