"""
Intent + mode classification — shared by the read and write paths.

Two orthogonal classifications, both derived from text only:
  mode        "read" | "write"   — gates which half of the agent graph runs
  agent_type  "qa" | "debug" | "review"  — prompt selection for the read path
              (previously a UI tab; now inferred, no user-facing selector)
"""
from typing import Literal, Tuple
import re

Mode = Literal["read", "write"]

_IDENT_RE = re.compile(
    r'`([^`]+)`|"([A-Za-z_]\w*(?:\.\w+)*)"'
    r'|\b([A-Z][a-zA-Z0-9]{2,})\b|\b([a-z_][a-z0-9_]{2,})\b'
)

_ROLE_KEYWORDS = {
    "auth": "AUTH", "authentication": "AUTH", "login": "AUTH",
    "token": "AUTH", "jwt": "AUTH", "permission": "AUTH", "password": "AUTH",
    "database": "DB", "db": "DB", "query": "DB", "sql": "DB",
    "route": "API", "endpoint": "API", "api": "API", "http": "API",
    "config": "CONFIG", "setting": "CONFIG", "env": "CONFIG",
    "test": "TEST", "spec": "TEST",
}

# Imperative code-authoring verbs. Weight 2 at the start of the request, 1 elsewhere.
_WRITE_VERBS = {
    "implement", "add", "create", "write", "build", "scaffold", "generate",
    "refactor", "rename", "extend", "wire", "hook", "migrate", "port",
    "convert", "introduce", "insert", "expose", "register", "stub",
}
_WRITE_PHRASES = (
    "wire up", "hook up", "add a new", "create a new", "make a new",
    "set up a", "write a function", "write the code", "add an endpoint",
    "add a route", "apply the fix", "make the change",
)
_LEAD_READ = (
    "what", "why", "how", "where", "who", "when", "which", "does", "do",
    "is", "are", "can i", "should i", "could you explain", "explain",
)
_READ_CUES = (
    "explain", "review", "audit", "walk me through", "show me",
    "list all", "list the", "give me a list", "find", "root cause",
    "why does", "what does", "how does",
    "traceback", "stack trace", "smell", "vulnerab", "bottleneck",
)
_TRACEBACK_RE = re.compile(
    r"(Traceback \(most recent call last\)|^\s*File \".+\", line \d+|"
    r"\b\w*(Error|Exception)\b:\s)", re.M
)


def _score(msg: str) -> Tuple[int, int]:
    m = msg.lower().strip()
    words = re.findall(r"[a-z_]+", m)
    w = r = 0
    for p in _WRITE_PHRASES:
        if p in m:
            w += 2
    for i, tok in enumerate(words[:4]):
        if tok in _WRITE_VERBS:
            w += 2 if i == 0 else 1
    for tok in words[4:]:
        if tok in _WRITE_VERBS:
            w += 1
    for c in _READ_CUES:
        if c in m:
            r += 2
    if any(m.startswith(l) for l in _LEAD_READ):
        r += 3
    if m.endswith("?"):
        r += 2
    if _TRACEBACK_RE.search(msg):
        r += 4
    return w, r


def classify_mode(message: str) -> Tuple[Mode, str]:
    """Heuristic-only classifier: cheap, deterministic, no extra LLM round trip."""
    w, r = _score(message)
    if w >= 2 and r == 0:
        return "write", "heuristic"
    if r >= 3 and w == 0:
        return "read", "heuristic"
    return ("write" if w > r else "read"), "default"


def classify_mode_with_history(current_message: str, prior_human_messages: list[str]) -> Tuple[Mode, str]:
    """
    Same heuristic, but a genuinely zero-signal reply ("yes please do it",
    "body app.py") no longer defaults to read. A short follow-up like that
    carries no write/read cues of its own - it's answering the previous
    turn, not starting a new request - so inherit the most recent prior
    turn's classification instead of guessing "read" via the w==r tiebreak.
    """
    mode, decided_by = classify_mode(current_message)
    w, r = _score(current_message)
    if w == 0 and r == 0:
        for prior in reversed(prior_human_messages):
            prior_mode, prior_decided_by = classify_mode(prior)
            if prior_decided_by != "default":
                return prior_mode, "inherited"
    return mode, decided_by


def infer_agent_type(message: str) -> Literal["qa", "debug", "review"]:
    """Replaces the old UI mode tabs for the read path."""
    m = message.lower()
    if _TRACEBACK_RE.search(message) or any(
        k in m for k in ("error", "exception", "fails", "failing", "broken",
                         "not working", "bug", "crash", "500", "root cause")
    ):
        return "debug"
    if any(k in m for k in ("review", "audit", "code smell", "vulnerab",
                            "security", "best practice", "improve", "critique")):
        return "review"
    return "qa"


def infer_roles(message: str) -> list[str]:
    msg = message.lower()
    roles = []
    for kw, role in _ROLE_KEYWORDS.items():
        if kw in msg and role not in roles:
            roles.append(role)
    return roles or ["API"]


def classify_intent(message: str) -> Tuple[str, str | None]:
    """
    Read-path sub-router. Returns (intent, role_hint).
    Priority: entrypoints > historical > structural > subsystem > semantic.
    """
    msg = message.lower()

    if any(w in msg for w in {"entrypoint", "entry point", "all routes", "all endpoints",
                               "list routes", "list endpoints", "what routes", "what endpoints",
                               "api routes", "where does it start"}):
        return "entrypoints", None

    historical = {"commit", "when did", "who added", "changed", "history",
                  "last month", "introduced", "removed", "why was"}
    for h in historical:
        if h in msg:
            return "historical", None

    structural = {"calls", "who calls", "called by", "depends on", "inherits",
                  "extends", "entry point", "defined in", "what calls", "what does",
                  "explain", "show me", "callers of", "callees of"}
    for s in structural:
        if s in msg:
            return "structural", None

    for kw, role in _ROLE_KEYWORDS.items():
        if kw in msg:
            return "subsystem", role

    return "semantic", None


def extract_anchors(message: str) -> list[str]:
    candidates = set()
    for m in _IDENT_RE.finditer(message):
        name = m.group(1) or m.group(2) or m.group(3) or m.group(4)
        if name and len(name) > 2:
            candidates.add(name)
    for word in message.split():
        clean = word.strip('`"\'.,?!')
        if "_" in clean and len(clean) > 4:
            candidates.add(clean)
    return list(candidates)[:6]
