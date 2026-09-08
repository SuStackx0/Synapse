"""LangGraph agent orchestration with graph-augmented retrieval."""
from typing import TypedDict, Annotated, Sequence, Literal
from langgraph.graph import StateGraph, END
from langchain.schema import BaseMessage, HumanMessage, SystemMessage
from langchain.schema import BaseLanguageModel
from ingestion.embedder import embedder
from ingestion.graph_builder import graph_builder
import operator
import structlog

logger = structlog.get_logger()


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    repo_id: str
    agent_type: str               # qa | debug | review
    context_chunks: list[str]     # from Qdrant
    graph_context: list[str]      # from Neo4j
    retrieval_trace: list[dict]   # what was retrieved and why


# ── Intent classification ─────────────────────────────────────────────────

def classify_intent(message: str) -> Literal["structural", "semantic", "historical"]:
    """Route queries to the appropriate retrieval strategy."""
    msg = message.lower()
    structural_signals = ["calls", "calls who", "who calls", "depends on", "imports",
                          "inheritance", "extends", "defined in", "entry point"]
    historical_signals = ["commit", "changed", "when did", "who added", "history",
                          "last month", "introduced", "removed", "why was"]
    if any(s in msg for s in structural_signals):
        return "structural"
    if any(s in msg for s in historical_signals):
        return "historical"
    return "semantic"


# ── Retrieval node (Qdrant + Neo4j) ──────────────────────────────────────

async def retrieve_context(state: AgentState) -> AgentState:
    query = state["messages"][-1].content if state["messages"] else ""
    intent = classify_intent(query)
    trace = [{"step": "intent_classified", "intent": intent}]

    # 1. Vector search (Qdrant)
    chunks = await embedder.search(state["repo_id"], query, limit=8)
    trace.append({"step": "vector_search", "hits": len(chunks), "top_score": chunks[0]["score"] if chunks else 0})

    # 2. Graph expansion (Neo4j) — find symbols mentioned in top chunks and expand 2 hops
    graph_ctx: list[str] = []
    for chunk in chunks[:3]:
        graph_lines = await graph_builder.find_symbols_in_context(
            state["repo_id"], chunk["text"]
        )
        graph_ctx.extend(graph_lines)

    if graph_ctx:
        trace.append({"step": "graph_expansion", "edges_found": len(graph_ctx)})

    return {
        **state,
        "context_chunks": [f"[{c['file']}]\n{c['text']}" for c in chunks],
        "graph_context": graph_ctx,
        "retrieval_trace": trace,
    }


# ── Context quality grader ────────────────────────────────────────────────

def grade_context(state: AgentState) -> Literal["sufficient", "retry"]:
    """Simple heuristic grade: if top chunk score is very low, retry with rephrasing."""
    trace = state.get("retrieval_trace", [])
    for step in trace:
        if step.get("step") == "vector_search":
            top_score = step.get("top_score", 0)
            if top_score < 0.25 and len(state["context_chunks"]) == 0:
                return "retry"
    return "sufficient"


async def retry_retrieval(state: AgentState) -> AgentState:
    """Fallback: search with a broadened query."""
    query = state["messages"][-1].content
    broader = query.split("?")[0]  # strip question marks, use first clause
    chunks = await embedder.search(state["repo_id"], broader, limit=6)
    return {
        **state,
        "context_chunks": [f"[{c['file']}]\n{c['text']}" for c in chunks],
        "retrieval_trace": [*state.get("retrieval_trace", []), {"step": "retry_retrieval"}],
    }


# ── System prompts ────────────────────────────────────────────────────────

SYSTEM_PROMPTS = {
    "qa": (
        "You are a senior software engineer with deep knowledge of this codebase. "
        "Answer questions accurately using the code context and graph relationships provided. "
        "Cite file paths and line numbers when relevant. Be concise and precise. "
        "If graph context is provided (lines starting with [Graph]), use it to trace call chains."
    ),
    "debug": (
        "You are an expert debugger. Given an error description and relevant code context, "
        "identify the root cause and provide a targeted, actionable fix. "
        "Structure your response as:\n"
        "**ROOT CAUSE**: one sentence\n"
        "**EXPLANATION**: how it happens\n"
        "**FIX**: code snippet with explanation"
    ),
    "review": (
        "You are a meticulous code reviewer. Analyze the provided code for: "
        "correctness, edge cases, security issues, performance, and readability. "
        "Format findings as numbered items with severity: 🔴 HIGH / 🟡 MEDIUM / 🟢 LOW. "
        "End with a one-line overall verdict."
    ),
}


# ── LLM call node ─────────────────────────────────────────────────────────

def make_llm_node(llm: BaseLanguageModel):
    async def call_llm(state: AgentState) -> AgentState:
        agent_type = state.get("agent_type", "qa")
        sys_prompt = SYSTEM_PROMPTS.get(agent_type, SYSTEM_PROMPTS["qa"])

        # Build context block
        code_context = "\n\n---\n\n".join(state.get("context_chunks", []))
        graph_context = "\n".join(state.get("graph_context", []))

        context_block = ""
        if code_context:
            context_block += f"### Relevant Code\n{code_context}\n\n"
        if graph_context:
            context_block += f"### Call Graph Context\n{graph_context}\n"

        messages = [
            SystemMessage(content=sys_prompt),
            SystemMessage(content=context_block if context_block else "No context retrieved."),
            *state["messages"],
        ]

        response = await llm.ainvoke(messages)
        logger.info("llm_response", agent_type=agent_type, chars=len(response.content))
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
