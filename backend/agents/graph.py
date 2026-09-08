"""
LangGraph agent — graph-augmented retrieval.

Retrieval principle (Opus):
  Graph (Neo4j) = structure — all text that reaches the LLM
  Vector (Qdrant) = entity linker — returns UIDs only, never text
  Disk = last-mile source bodies, fetched only when needed

Query routing:
  structural intent  → Neo4j only (call chains, symbol cards)
  historical intent  → Qdrant commits → Neo4j MODIFIED_IN
  semantic/concept   → Qdrant uids → Neo4j resolve_uids_to_cards → SGL
"""
from typing import TypedDict, Annotated, Sequence, Literal
from langgraph.graph import StateGraph, END
from langchain.schema import BaseMessage, HumanMessage, SystemMessage
from langchain.schema import BaseLanguageModel
from ingestion.embedder import embedder
from ingestion.graph_builder import graph_builder, serialize_cards_to_sgl, SGL_LEGEND
import operator
import re
import structlog

logger = structlog.get_logger()

# Identifier patterns for anchor extraction
_IDENT_RE = re.compile(r'`([^`]+)`|"([A-Za-z_]\w*(?:\.\w+)*)"|\b([A-Z][a-zA-Z0-9]{2,})\b|\b([a-z_][a-z0-9_]{2,})\b')


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    repo_id: str
    agent_type: str             # qa | debug | review
    intent: str                 # structural | historical | semantic
    anchors: list[str]          # resolved symbol names
    context_sgl: str            # SGL serialized context from Neo4j
    commit_context: str         # serialized commit hits
    retrieval_trace: list[dict]


# ── Intent + anchor extraction ────────────────────────────────────────────

def classify_intent(message: str) -> str:
    msg = message.lower()
    structural = {"calls", "who calls", "called by", "depends on", "imports",
                  "inherits", "extends", "entry point", "defined in", "uses"}
    historical = {"commit", "when did", "who added", "changed", "history",
                  "last month", "introduced", "removed", "why was"}
    for s in structural:
        if s in msg:
            return "structural"
    for h in historical:
        if h in msg:
            return "historical"
    return "semantic"


def extract_anchors(message: str) -> list[str]:
    """Pull identifier candidates from the user message."""
    candidates = set()
    for m in _IDENT_RE.finditer(message):
        name = m.group(1) or m.group(2) or m.group(3) or m.group(4)
        if name and len(name) > 2:
            candidates.add(name)
    # Also grab snake_case words longer than 4 chars
    for word in message.split():
        clean = word.strip('`"\'.,?!')
        if "_" in clean and len(clean) > 4:
            candidates.add(clean)
    return list(candidates)[:6]


# ── Retrieval node ────────────────────────────────────────────────────────

async def retrieve_context(state: AgentState) -> AgentState:
    query = state["messages"][-1].content if state["messages"] else ""
    repo_id = state["repo_id"]
    intent = classify_intent(query)
    anchors = extract_anchors(query)
    trace = [{"step": "intent", "value": intent}, {"step": "anchors", "value": anchors}]

    sgl_parts = []
    commit_ctx = ""

    if intent == "structural" and anchors:
        # Neo4j only — call chain or symbol card
        for anchor in anchors[:2]:
            if "call" in query.lower() or "who uses" in query.lower():
                data = await graph_builder.reverse_calls(repo_id, anchor)
                if data:
                    callers = data.get("callers", [])
                    target = data.get("target", {})
                    sgl_parts.append(f"# Callers of {target.get('qualname', anchor)}")
                    for c in callers[:20]:
                        chain = " -> ".join(c.get("chain", []))
                        sgl_parts.append(f"  depth={c['depth']} conf={c['conf']:.2f} {chain}  [{c.get('at','')}]")
            else:
                card = await graph_builder.symbol_card(repo_id, anchor)
                if card:
                    sgl_parts.append(serialize_cards_to_sgl(
                        [{"s": card.get("fn", card), "callees": card.get("callees", []), "callers": card.get("callers", [])}],
                        include_legend=not sgl_parts,
                    ))
        trace.append({"step": "neo4j_structural", "anchors": anchors})

    elif intent == "historical":
        # Qdrant commits → metadata only
        commits = await embedder.search_commits(repo_id, query, limit=8)
        if commits:
            lines = ["# Relevant commits"]
            for c in commits:
                lines.append(f"  {c['sha']} ({c['date']}) {c['author']} — files: {', '.join(c['files'][:4])}")
            commit_ctx = "\n".join(lines)
        trace.append({"step": "commit_search", "hits": len(commits)})

        # If anchors found, also get structural context
        if anchors:
            uids = await embedder.search_symbols(repo_id, query, limit=6)
            if uids:
                cards = await graph_builder.resolve_uids_to_cards(repo_id, [u["uid"] for u in uids])
                if cards:
                    sgl_parts.append(serialize_cards_to_sgl(cards, include_legend=True))
            trace.append({"step": "uid_resolve", "count": len(uids)})

    else:
        # Semantic: Qdrant → UIDs → Neo4j → SGL
        uid_hits = await embedder.search_symbols(repo_id, query, limit=12)
        trace.append({"step": "qdrant_uids", "hits": len(uid_hits)})
        if uid_hits:
            uids = [h["uid"] for h in uid_hits if h["uid"]]
            cards = await graph_builder.resolve_uids_to_cards(repo_id, uids)
            if cards:
                sgl_parts.append(serialize_cards_to_sgl(cards, include_legend=True))
            trace.append({"step": "neo4j_resolve", "cards": len(cards)})

    context_sgl = "\n\n".join(sgl_parts)
    return {
        **state,
        "intent": intent,
        "anchors": anchors,
        "context_sgl": context_sgl,
        "commit_context": commit_ctx,
        "retrieval_trace": trace,
    }


# ── Context grader ────────────────────────────────────────────────────────

def grade_context(state: AgentState) -> Literal["sufficient", "retry"]:
    if not state.get("context_sgl") and not state.get("commit_context"):
        return "retry"
    return "sufficient"


async def retry_retrieval(state: AgentState) -> AgentState:
    """Fallback: broaden search."""
    query = state["messages"][-1].content
    uid_hits = await embedder.search_symbols(state["repo_id"], query.split()[0], limit=6)
    uids = [h["uid"] for h in uid_hits if h["uid"]]
    cards = await graph_builder.resolve_uids_to_cards(state["repo_id"], uids)
    sgl = serialize_cards_to_sgl(cards, include_legend=True) if cards else ""
    return {
        **state,
        "context_sgl": sgl,
        "retrieval_trace": [*state.get("retrieval_trace", []), {"step": "retry"}],
    }


# ── System prompts ────────────────────────────────────────────────────────

SYSTEM_PROMPTS = {
    "qa": (
        "You are a senior engineer with deep knowledge of this codebase. "
        "Answer using the SGL context (graph-derived symbol cards) provided. "
        "SGL format: f=function, af=async, C=class, >=calls, <=called-by, !=raises, ENTRY=entrypoint. "
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


# ── LLM node ─────────────────────────────────────────────────────────────

def make_llm_node(llm: BaseLanguageModel):
    async def call_llm(state: AgentState) -> AgentState:
        agent_type = state.get("agent_type", "qa")
        sys_prompt = SYSTEM_PROMPTS.get(agent_type, SYSTEM_PROMPTS["qa"])

        context_block = ""
        if state.get("context_sgl"):
            context_block += f"### Codebase Context (SGL)\n{state['context_sgl']}\n\n"
        if state.get("commit_context"):
            context_block += f"### Git History\n{state['commit_context']}\n"

        messages = [
            SystemMessage(content=sys_prompt),
            SystemMessage(content=context_block or "No context retrieved."),
            *state["messages"],
        ]
        response = await llm.ainvoke(messages)
        logger.info("llm_done", agent=agent_type, intent=state.get("intent"),
                    ctx_len=len(context_block))
        return {**state, "messages": [*state["messages"], response]}

    return call_llm


# ── Graph factory ─────────────────────────────────────────────────────────

def build_agent_graph(llm: BaseLanguageModel) -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("retrieve", retrieve_context)
    graph.add_node("retry", retry_retrieval)
    graph.add_node("llm", make_llm_node(llm))
    graph.set_entry_point("retrieve")
    graph.add_conditional_edges("retrieve", grade_context, {
        "sufficient": "llm",
        "retry": "retry",
    })
    graph.add_edge("retry", "llm")
    graph.add_edge("llm", END)
    return graph.compile()
