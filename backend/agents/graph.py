"""
LangGraph agent — graph-augmented retrieval.

Retrieval principle (Opus):
  Graph (Neo4j) = structure — all text that reaches the LLM
  Vector (Qdrant) = entity linker — returns UIDs only, never text
  Disk = last-mile source bodies, fetched only when needed

Query routing (lexical-first):
  Step 0: fulltext sym_ft — identifier present? → Neo4j only, no Qdrant call
  Step 1: role/domain → subsystem reader
  Step 2: semantic → Qdrant UIDs → Neo4j cards
  Step 3: history → Qdrant commits → metadata

Coverage tiers: complete | partial | sparse | empty
"""
from typing import TypedDict, Annotated, Sequence, Literal
from langgraph.graph import StateGraph, END
from langchain.schema import BaseMessage, HumanMessage, SystemMessage
from langchain.schema import BaseLanguageModel
from ingestion.embedder import embedder
from ingestion.graph_builder import graph_builder, serialize_cards_to_sgl, SKL_LEGEND
import operator
import re
import structlog

logger = structlog.get_logger()

_IDENT_RE = re.compile(
    r'`([^`]+)`|"([A-Za-z_]\w*(?:\.\w+)*)"'
    r'|\b([A-Z][a-zA-Z0-9]{2,})\b|\b([a-z_][a-z0-9_]{2,})\b'
)

# Role keyword → role tag for subsystem queries
_ROLE_KEYWORDS = {
    "auth": "AUTH", "authentication": "AUTH", "login": "AUTH",
    "token": "AUTH", "jwt": "AUTH", "permission": "AUTH",
    "database": "DB", "db": "DB", "query": "DB", "sql": "DB",
    "route": "API", "endpoint": "API", "api": "API", "http": "API",
    "config": "CONFIG", "setting": "CONFIG", "env": "CONFIG",
    "test": "TEST", "spec": "TEST",
}


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    repo_id: str
    agent_type: str             # qa | debug | review
    intent: str                 # structural | historical | semantic | subsystem | entrypoints
    anchors: list[str]          # resolved symbol names
    context_sgl: str            # SKL serialized context from Neo4j
    commit_context: str         # serialized commit hits
    retrieval_trace: list[dict]
    coverage: str               # complete | partial | sparse | empty


# ── Intent classification ─────────────────────────────────────────────────

def classify_intent(message: str) -> tuple[str, str | None]:
    """
    Returns (intent, role_hint).
    Tries role match first (subsystem), then structural/historical/semantic.
    """
    msg = message.lower()

    # Check for subsystem/role keywords
    for kw, role in _ROLE_KEYWORDS.items():
        if kw in msg:
            return "subsystem", role

    # Structural indicators
    structural = {"calls", "who calls", "called by", "depends on", "imports",
                  "inherits", "extends", "entry point", "defined in", "uses",
                  "what calls", "what does", "explain", "show me"}
    for s in structural:
        if s in msg:
            return "structural", None

    # Historical
    historical = {"commit", "when did", "who added", "changed", "history",
                  "last month", "introduced", "removed", "why was"}
    for h in historical:
        if h in msg:
            return "historical", None

    # Entrypoint queries
    if any(w in msg for w in {"entrypoint", "entry point", "routes", "endpoints", "start"}):
        return "entrypoints", None

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


def _coverage(sgl: str, commits: str) -> str:
    if not sgl and not commits:
        return "empty"
    combined = len(sgl) + len(commits)
    if combined > 800:
        return "complete"
    if combined > 200:
        return "partial"
    return "sparse"


# ── Retrieval node ─────────────────────────────────────────────────────────

async def retrieve_context(state: AgentState) -> AgentState:
    query = state["messages"][-1].content if state["messages"] else ""
    repo_id = state["repo_id"]
    intent, role_hint = classify_intent(query)
    anchors = extract_anchors(query)
    trace = [{"step": "intent", "value": intent}, {"step": "anchors", "value": anchors}]

    sgl_parts = []
    commit_ctx = ""
    resolved_anchors = []

    if intent == "entrypoints":
        # Index lookup — no embedding, no fulltext
        eps = await graph_builder.find_entrypoints(repo_id)
        if eps:
            lines = ["# Entrypoints / API routes"]
            for ep in eps[:20]:
                lines.append(f"  {ep['rel_path']} {ep['qualname']} {ep.get('sig','')} {ep.get('decorators',[])}")
            sgl_parts.append("\n".join(lines))
        trace.append({"step": "entrypoints", "count": len(eps) if eps else 0})

    elif intent == "subsystem" and role_hint:
        # Role index — no embedding
        syms = await graph_builder.find_by_role(repo_id, role_hint)
        if syms:
            cards = [{"s": s, "callees": [], "callers": []} for s in syms]
            sgl_parts.append(serialize_cards_to_sgl(cards, include_legend=True))
            resolved_anchors = [s["name"] for s in syms[:6]]
        trace.append({"step": "role_lookup", "role": role_hint, "hits": len(syms)})

    elif intent == "structural":
        # Step 0: lexical fulltext — try resolving identifier before Qdrant
        lexical_hits = await graph_builder.resolve_anchors_lexical(repo_id, query)
        trace.append({"step": "lexical_ft", "hits": len(lexical_hits)})

        if lexical_hits:
            # Got a name match — use graph only
            resolved_anchors = [h["name"] for h in lexical_hits[:3]]
            uids = [h["uid"] for h in lexical_hits if h.get("uid")]
            cards = await graph_builder.resolve_uids_to_cards(repo_id, uids)
            if cards:
                sgl_parts.append(serialize_cards_to_sgl(cards, include_legend=True))

            # Also check if it's a "who calls X" question
            for anchor in resolved_anchors[:2]:
                if any(w in query.lower() for w in ["calls", "uses", "who", "callers"]):
                    data = await graph_builder.reverse_calls(repo_id, anchor)
                    if data and data.get("callers"):
                        target = data.get("target", {})
                        lines = [f"# Callers of {target.get('qualname', anchor)}"]
                        for c in data["callers"][:20]:
                            chain = " -> ".join(c.get("chain", []))
                            lines.append(f"  depth={c['depth']} conf={c['conf']:.2f} {chain}  [{c.get('at','')}]")
                        sgl_parts.append("\n".join(lines))

            trace.append({"step": "neo4j_structural", "anchors": resolved_anchors})

        else:
            # No lexical hit — fall back to vector
            uid_hits = await embedder.search_symbols(repo_id, query, limit=8)
            if uid_hits:
                uids = [h["uid"] for h in uid_hits if h["uid"]]
                cards = await graph_builder.resolve_uids_to_cards(repo_id, uids)
                if cards:
                    sgl_parts.append(serialize_cards_to_sgl(cards, include_legend=True))
                resolved_anchors = [h["qualname"] for h in uid_hits[:3] if h.get("qualname")]
            trace.append({"step": "qdrant_fallback", "hits": len(uid_hits)})

    elif intent == "historical":
        commits = await embedder.search_commits(repo_id, query, limit=8)
        if commits:
            lines = ["# Relevant commits"]
            for c in commits:
                lines.append(f"  {c['sha']} ({c['date']}) {c['author']} — {', '.join(c['files'][:4])}")
            commit_ctx = "\n".join(lines)
        trace.append({"step": "commit_search", "hits": len(commits)})

        # Also resolve any named anchors structurally
        if anchors:
            lexical_hits = await graph_builder.resolve_anchors_lexical(repo_id, " ".join(anchors))
            if lexical_hits:
                uids = [h["uid"] for h in lexical_hits if h.get("uid")]
                cards = await graph_builder.resolve_uids_to_cards(repo_id, uids)
                if cards:
                    sgl_parts.append(serialize_cards_to_sgl(cards, include_legend=True))
                resolved_anchors = [h["name"] for h in lexical_hits[:3]]
            trace.append({"step": "lexical_ft", "hits": len(lexical_hits)})

    else:
        # Semantic: step 0 — try lexical first
        lexical_hits = await graph_builder.resolve_anchors_lexical(repo_id, query, limit=4)
        if lexical_hits and lexical_hits[0].get("uid"):
            trace.append({"step": "lexical_ft", "hits": len(lexical_hits)})
            uids = [h["uid"] for h in lexical_hits if h.get("uid")]
            cards = await graph_builder.resolve_uids_to_cards(repo_id, uids)
            if cards:
                sgl_parts.append(serialize_cards_to_sgl(cards, include_legend=True))
            resolved_anchors = [h["name"] for h in lexical_hits[:3]]
        else:
            # Pure semantic: Qdrant UIDs → Neo4j cards
            uid_hits = await embedder.search_symbols(repo_id, query, limit=12)
            trace.append({"step": "qdrant_uids", "hits": len(uid_hits)})
            if uid_hits:
                uids = [h["uid"] for h in uid_hits if h["uid"]]
                cards = await graph_builder.resolve_uids_to_cards(repo_id, uids)
                if cards:
                    sgl_parts.append(serialize_cards_to_sgl(cards, include_legend=True))
                resolved_anchors = [h["qualname"] for h in uid_hits[:3] if h.get("qualname")]
            trace.append({"step": "neo4j_resolve", "cards": len(cards) if uid_hits else 0})

    context_sgl = "\n\n".join(sgl_parts)
    cov = _coverage(context_sgl, commit_ctx)
    trace.append({"step": "coverage", "value": cov})

    return {
        **state,
        "intent": intent,
        "anchors": resolved_anchors,
        "context_sgl": context_sgl,
        "commit_context": commit_ctx,
        "retrieval_trace": trace,
        "coverage": cov,
    }


# ── Coverage grader ───────────────────────────────────────────────────────

def grade_context(state: AgentState) -> Literal["sufficient", "widen", "retry"]:
    cov = state.get("coverage", "empty")
    if cov in ("complete", "partial"):
        return "sufficient"
    if cov == "sparse":
        return "widen"
    return "retry"


async def widen_retrieval(state: AgentState) -> AgentState:
    """Sparse coverage: broaden one axis (lower confidence, more hits)."""
    query = state["messages"][-1].content
    uid_hits = await embedder.search_symbols(state["repo_id"], query, limit=16)
    uids = [h["uid"] for h in uid_hits if h["uid"]]
    cards = await graph_builder.resolve_uids_to_cards(state["repo_id"], uids)
    sgl = serialize_cards_to_sgl(cards, include_legend=True) if cards else ""
    cov = _coverage(sgl, state.get("commit_context", ""))
    return {
        **state,
        "context_sgl": sgl or state.get("context_sgl", ""),
        "coverage": cov,
        "retrieval_trace": [*state.get("retrieval_trace", []), {"step": "widen", "hits": len(uid_hits)}],
    }


async def retry_retrieval(state: AgentState) -> AgentState:
    """Empty coverage: try first keyword of query."""
    query = state["messages"][-1].content
    uid_hits = await embedder.search_symbols(state["repo_id"], query.split()[0], limit=6)
    uids = [h["uid"] for h in uid_hits if h["uid"]]
    cards = await graph_builder.resolve_uids_to_cards(state["repo_id"], uids)
    sgl = serialize_cards_to_sgl(cards, include_legend=True) if cards else ""
    return {
        **state,
        "context_sgl": sgl,
        "coverage": "sparse" if sgl else "empty",
        "retrieval_trace": [*state.get("retrieval_trace", []), {"step": "retry"}],
    }


# ── System prompts ────────────────────────────────────────────────────────

SYSTEM_PROMPTS = {
    "qa": (
        "You are a senior engineer with deep knowledge of this codebase. "
        "Answer using the SKL context (graph-derived symbol cards) provided. "
        "SKL: f=function af=async C=class >=calls <=called-by !=raises ENTRY=entrypoint DEAD=no-callers. "
        "Cite file:line when relevant. Be precise and concise."
    ),
    "debug": (
        "You are an expert debugger. Use the codebase context to find the root cause. "
        "Structure: **ROOT CAUSE** → **EXPLANATION** → **FIX** (with code snippet). "
        "Cite the exact file and line where the bug lives."
    ),
    "review": (
        "You are a meticulous code reviewer. Use the symbol cards and call graph context provided. "
        "Format: numbered findings with 🔴 HIGH / 🟡 MEDIUM / 🟢 LOW severity. "
        "End with a one-line verdict."
    ),
}


# ── Repo map cache (per repo_id, stable across queries) ──────────────────

_REPO_MAP_CACHE: dict[str, str] = {}


async def _get_repo_map(repo_id: str) -> str:
    if repo_id not in _REPO_MAP_CACHE:
        try:
            _REPO_MAP_CACHE[repo_id] = await graph_builder.repo_map(repo_id)
        except Exception:
            _REPO_MAP_CACHE[repo_id] = ""
    return _REPO_MAP_CACHE[repo_id]


# ── LLM node ──────────────────────────────────────────────────────────────

def make_llm_node(llm: BaseLanguageModel):
    async def call_llm(state: AgentState) -> AgentState:
        agent_type = state.get("agent_type", "qa")
        sys_prompt = SYSTEM_PROMPTS.get(agent_type, SYSTEM_PROMPTS["qa"])

        # T0: repo map as stable prefix (cached per repo_id)
        repo_map = await _get_repo_map(state["repo_id"])

        context_block = ""
        if repo_map:
            context_block += f"### Repository Structure\n{repo_map}\n\n"
        if state.get("context_sgl"):
            context_block += f"### Relevant Symbols (SKL)\n{state['context_sgl']}\n\n"
        if state.get("commit_context"):
            context_block += f"### Git History\n{state['commit_context']}\n"

        cov = state.get("coverage", "")
        if cov in ("sparse", "empty"):
            context_block += f"\n_[Coverage: {cov} — answer with appropriate uncertainty]_\n"

        messages = [
            SystemMessage(content=sys_prompt),
            SystemMessage(content=context_block or "No context retrieved."),
            *state["messages"],
        ]
        response = await llm.ainvoke(messages)
        logger.info("llm_done", agent=agent_type, intent=state.get("intent"),
                    coverage=state.get("coverage"), ctx_len=len(context_block))
        return {**state, "messages": [*state["messages"], response]}

    return call_llm


# ── Graph factory ─────────────────────────────────────────────────────────

def build_agent_graph(llm: BaseLanguageModel) -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("retrieve", retrieve_context)
    graph.add_node("widen", widen_retrieval)
    graph.add_node("retry", retry_retrieval)
    graph.add_node("llm", make_llm_node(llm))
    graph.set_entry_point("retrieve")
    graph.add_conditional_edges("retrieve", grade_context, {
        "sufficient": "llm",
        "widen": "widen",
        "retry": "retry",
    })
    graph.add_edge("widen", "llm")
    graph.add_edge("retry", "llm")
    graph.add_edge("llm", END)
    return graph.compile()
