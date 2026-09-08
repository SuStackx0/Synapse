"""LangGraph agent orchestration for Synapse."""
from typing import TypedDict, Annotated, Sequence
from langgraph.graph import StateGraph, END
from langchain.schema import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain.schema import BaseLanguageModel
from ingestion.embedder import embedder
import operator


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    repo_id: str
    agent_type: str  # qa | debug | review
    context_chunks: list[str]


# ── Retrieval node ──────────────────────────────────────────────────────────

async def retrieve_context(state: AgentState) -> AgentState:
    query = state["messages"][-1].content if state["messages"] else ""
    chunks = await embedder.search(state["repo_id"], query, limit=6)
    state["context_chunks"] = [c["text"] for c in chunks]
    return state


# ── System prompts per agent type ───────────────────────────────────────────

SYSTEM_PROMPTS = {
    "qa": (
        "You are a senior software engineer with full knowledge of this codebase. "
        "Answer questions accurately using the code context provided. "
        "Cite file paths when relevant. Be concise and precise."
    ),
    "debug": (
        "You are an expert debugger. Given an error or bug description and relevant code context, "
        "identify the root cause and provide a targeted fix. "
        "Format your response as: ROOT CAUSE → EXPLANATION → FIX (with code snippets)."
    ),
    "review": (
        "You are a meticulous code reviewer. Analyze the provided code for: "
        "correctness, edge cases, performance, readability, and security. "
        "Provide numbered findings with severity labels (HIGH/MEDIUM/LOW)."
    ),
}


# ── LLM call node ───────────────────────────────────────────────────────────

def make_llm_node(llm: BaseLanguageModel):
    async def call_llm(state: AgentState) -> AgentState:
        agent_type = state.get("agent_type", "qa")
        sys_prompt = SYSTEM_PROMPTS.get(agent_type, SYSTEM_PROMPTS["qa"])
        context = "\n---\n".join(state.get("context_chunks", []))

        messages = [
            SystemMessage(content=sys_prompt),
            SystemMessage(content=f"Relevant code context:\n{context}" if context else "No context retrieved."),
            *state["messages"],
        ]
        response = await llm.ainvoke(messages)
        return {**state, "messages": [*state["messages"], response]}

    return call_llm


# ── Graph factory ────────────────────────────────────────────────────────────

def build_agent_graph(llm: BaseLanguageModel) -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("retrieve", retrieve_context)
    graph.add_node("llm", make_llm_node(llm))
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "llm")
    graph.add_edge("llm", END)
    return graph.compile()
