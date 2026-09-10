"""
LangGraph agent — graph-augmented retrieval AND graph-guided implementation.

Read path (unchanged):
  Graph (Neo4j) = structure — all text that reaches the LLM
  Vector (Qdrant) = entity linker — returns UIDs only, never text
  classify -> retrieve -> grade -> llm | widen | retry -> llm

Write path (new):
  classify -> plan_context (graph picks placement + exemplars, no LLM)
           -> planner (1 LLM call -> file-level task list)
           -> coder (1 LLM call per file -> full file content)
           -> apply (validate + write to disk, no LLM)
           -> summarize (deterministic markdown, no LLM)

No user-facing mode tabs: classify_mode() infers read vs write from the
query text alone, so a single chat box serves ask/debug/review/implement.
"""
from typing import TypedDict, Annotated, Sequence, Literal, Optional
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langchain_core.language_models import BaseLanguageModel
from ingestion.embedder import embedder
from ingestion.graph_builder import graph_builder, serialize_cards_to_sgl
from agents.intent import (
    classify_mode, classify_intent, extract_anchors, infer_agent_type, infer_roles,
)
from agents.write_context import build_write_context, render_write_context
from agents.write_tool import FileWrite, apply_write, preview_write
import json
import operator
import re
import structlog

logger = structlog.get_logger()


class FileTask(TypedDict):
    rel_path: str
    op: str          # create | rewrite | append
    intent: str


class AgentState(TypedDict):
    # shared
    messages: Annotated[Sequence[BaseMessage], operator.add]
    repo_id: str
    repo_root: str
    agent_type: str
    mode: str                    # read | write
    mode_decided_by: str
    auto_apply: bool

    # read path
    intent: str
    anchors: list
    context_sgl: str
    commit_context: str
    retrieval_trace: list
    coverage: str

    # write path
    role_hint: list
    placement_dir: str
    plan: list
    plan_summary: str
    plan_attempts: int
    write_results: list
    files_written: list
    write_errors: list
    progress: list               # SSE-friendly progress events, drained by the router
    _pending_writes: list        # FileWrite dicts staged by coder, consumed by apply_writes
    clarifying_question: str     # set when the model asks instead of guessing; ends the turn


def initial_state(messages, repo_id: str, repo_root: str = "", agent_type: str = "qa",
                   auto_apply: bool = True) -> "AgentState":
    return {
        "messages": messages,
        "repo_id": repo_id,
        "repo_root": repo_root,
        "agent_type": agent_type,
        "mode": "", "mode_decided_by": "",
        "auto_apply": auto_apply,
        "intent": "", "anchors": [], "context_sgl": "", "commit_context": "",
        "retrieval_trace": [], "coverage": "",
        "role_hint": [], "placement_dir": "", "plan": [], "plan_summary": "",
        "plan_attempts": 0, "write_results": [], "files_written": [],
        "write_errors": [], "progress": [], "_pending_writes": [],
        "clarifying_question": "",
    }


def _coverage(sgl: str, commits: str) -> str:
    if not sgl and not commits:
        return "empty"
    combined = len(sgl) + len(commits)
    if combined > 800:
        return "complete"
    if combined > 200:
        return "partial"
    return "sparse"


# ── Shared entry: classify read vs write ────────────────────────────────

async def classify(state: AgentState) -> AgentState:
    query = state["messages"][-1].content if state["messages"] else ""
    mode, decided_by = classify_mode(query)
    agent_type = infer_agent_type(query)
    return {**state, "mode": mode, "mode_decided_by": decided_by, "agent_type": agent_type}


def route_mode(state: AgentState) -> Literal["read", "write"]:
    if state.get("mode") == "write" and state.get("repo_root"):
        return "write"
    return "read"


# ── Read path (unchanged behavior) ──────────────────────────────────────

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
        eps = await graph_builder.find_entrypoints(repo_id)
        if eps:
            lines = ["# Entrypoints / API routes"]
            for ep in eps[:20]:
                lines.append(f"  {ep['rel_path']} {ep['qualname']} {ep.get('sig','')} {ep.get('decorators',[])}")
            sgl_parts.append("\n".join(lines))
        trace.append({"step": "entrypoints", "count": len(eps) if eps else 0})

    elif intent == "subsystem" and role_hint:
        syms = await graph_builder.find_by_role(repo_id, role_hint)
        if syms:
            cards = [{"s": s, "callees": [], "callers": []} for s in syms]
            sgl_parts.append(serialize_cards_to_sgl(cards, include_legend=True))
            resolved_anchors = [s["name"] for s in syms[:6]]
        trace.append({"step": "role_lookup", "role": role_hint, "hits": len(syms)})

    elif intent == "structural":
        lexical_hits = await graph_builder.resolve_anchors_lexical(repo_id, query)
        trace.append({"step": "lexical_ft", "hits": len(lexical_hits)})

        if lexical_hits:
            resolved_anchors = [h["name"] for h in lexical_hits[:3]]
            uids = [h["uid"] for h in lexical_hits if h.get("uid")]
            cards = await graph_builder.resolve_uids_to_cards(repo_id, uids)
            if cards:
                sgl_parts.append(serialize_cards_to_sgl(cards, include_legend=True))

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
        lexical_hits = await graph_builder.resolve_anchors_lexical(repo_id, query, limit=4)
        if lexical_hits and lexical_hits[0].get("uid"):
            trace.append({"step": "lexical_ft", "hits": len(lexical_hits)})
            uids = [h["uid"] for h in lexical_hits if h.get("uid")]
            cards = await graph_builder.resolve_uids_to_cards(repo_id, uids)
            if cards:
                sgl_parts.append(serialize_cards_to_sgl(cards, include_legend=True))
            resolved_anchors = [h["name"] for h in lexical_hits[:3]]
        else:
            uid_hits = await embedder.search_symbols(repo_id, query, limit=12)
            trace.append({"step": "qdrant_uids", "hits": len(uid_hits)})
            cards = []
            if uid_hits:
                uids = [h["uid"] for h in uid_hits if h["uid"]]
                cards = await graph_builder.resolve_uids_to_cards(repo_id, uids)
                if cards:
                    sgl_parts.append(serialize_cards_to_sgl(cards, include_legend=True))
                resolved_anchors = [h["qualname"] for h in uid_hits[:3] if h.get("qualname")]
            trace.append({"step": "neo4j_resolve", "cards": len(cards)})

    context_sgl = "\n\n".join(sgl_parts)
    cov = _coverage(context_sgl, commit_ctx)
    trace.append({"step": "coverage", "value": cov})

    return {
        **state,
        "intent": intent, "anchors": resolved_anchors, "context_sgl": context_sgl,
        "commit_context": commit_ctx, "retrieval_trace": trace, "coverage": cov,
    }


def grade_context(state: AgentState) -> Literal["sufficient", "widen", "retry"]:
    cov = state.get("coverage", "empty")
    if cov in ("complete", "partial"):
        return "sufficient"
    if cov == "sparse":
        return "widen"
    return "retry"


async def widen_retrieval(state: AgentState) -> AgentState:
    query = state["messages"][-1].content
    uid_hits = await embedder.search_symbols(state["repo_id"], query, limit=16)
    uids = [h["uid"] for h in uid_hits if h["uid"]]
    cards = await graph_builder.resolve_uids_to_cards(state["repo_id"], uids)
    sgl = serialize_cards_to_sgl(cards, include_legend=True) if cards else ""
    cov = _coverage(sgl, state.get("commit_context", ""))
    return {
        **state, "context_sgl": sgl or state.get("context_sgl", ""), "coverage": cov,
        "retrieval_trace": [*state.get("retrieval_trace", []), {"step": "widen", "hits": len(uid_hits)}],
    }


async def retry_retrieval(state: AgentState) -> AgentState:
    query = state["messages"][-1].content
    uid_hits = await embedder.search_symbols(state["repo_id"], query.split()[0], limit=6)
    uids = [h["uid"] for h in uid_hits if h["uid"]]
    cards = await graph_builder.resolve_uids_to_cards(state["repo_id"], uids)
    sgl = serialize_cards_to_sgl(cards, include_legend=True) if cards else ""
    return {
        **state, "context_sgl": sgl, "coverage": "sparse" if sgl else "empty",
        "retrieval_trace": [*state.get("retrieval_trace", []), {"step": "retry"}],
    }


_CLARIFY_RULE = (
    "If the request is genuinely ambiguous, or you lack information only the user can "
    "provide (e.g. which of several plausible files/approaches they mean, a business rule "
    "the codebase doesn't encode, a missing credential/config choice) — do not guess. "
    "Reply with EXACTLY one line: 'CLARIFY: <your single, specific question>' and nothing else. "
    "Only do this when actually blocked; prefer answering from the graph context whenever you can."
)

SYSTEM_PROMPTS = {
    "qa": (
        "You are a senior engineer with deep knowledge of this codebase. "
        "Answer using the SKL context (graph-derived symbol cards) provided. "
        "SKL: f=function af=async C=class >=calls <=called-by !=raises ENTRY=entrypoint DEAD=no-callers. "
        "Cite file:line when relevant. Be precise and concise.\n" + _CLARIFY_RULE
    ),
    "debug": (
        "You are an expert debugger. Use the codebase context to find the root cause. "
        "Structure: **ROOT CAUSE** → **EXPLANATION** → **FIX** (with code snippet). "
        "Cite the exact file and line where the bug lives.\n" + _CLARIFY_RULE
    ),
    "review": (
        "You are a meticulous code reviewer. Use the symbol cards and call graph context provided. "
        "Format: numbered findings with 🔴 HIGH / 🟡 MEDIUM / 🟢 LOW severity. "
        "End with a one-line verdict.\n" + _CLARIFY_RULE
    ),
}

_REPO_MAP_CACHE: dict = {}


async def _get_repo_map(repo_id: str) -> str:
    if repo_id not in _REPO_MAP_CACHE:
        try:
            _REPO_MAP_CACHE[repo_id] = await graph_builder.repo_map(repo_id)
        except Exception:
            _REPO_MAP_CACHE[repo_id] = ""
    return _REPO_MAP_CACHE[repo_id]


def invalidate_repo_map(repo_id: str):
    _REPO_MAP_CACHE.pop(repo_id, None)


def make_llm_node(llm: BaseLanguageModel):
    async def call_llm(state: AgentState) -> AgentState:
        agent_type = state.get("agent_type", "qa")
        sys_prompt = SYSTEM_PROMPTS.get(agent_type, SYSTEM_PROMPTS["qa"])

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
        raw = (response.content or "").strip()
        clarifying = ""
        if raw.upper().startswith("CLARIFY:"):
            clarifying = raw.split(":", 1)[1].strip()
            response = AIMessage(content=clarifying)

        logger.info("llm_done", agent=agent_type, intent=state.get("intent"),
                    coverage=state.get("coverage"), ctx_len=len(context_block),
                    clarifying=bool(clarifying))

        progress = state.get("progress", [])
        if clarifying:
            progress = [*progress, {"event": "clarify", "question": clarifying}]
        return {**state, "messages": [*state["messages"], response],
                "clarifying_question": clarifying, "progress": progress}

    return call_llm


# ── Write path ───────────────────────────────────────────────────────────

async def plan_context(state: AgentState) -> AgentState:
    query = state["messages"][-1].content if state["messages"] else ""
    roles = infer_roles(query)
    anchors = extract_anchors(query)
    wc = await build_write_context(state["repo_id"], state["repo_root"], roles, anchors)
    rendered = render_write_context(wc)
    progress = [*state.get("progress", []), {
        "event": "context_ready",
        "placement_dir": wc.placement_dir,
        "exemplars": [p for p, _ in wc.exemplars],
        "anchors": anchors,
        "roles": roles,
    }]
    return {
        **state,
        "role_hint": roles,
        "placement_dir": wc.placement_dir,
        "context_sgl": rendered,   # reuse this field to carry the rendered write context
        "progress": progress,
    }


_PLANNER_SYS = (
    "You are a senior engineer planning a code change. Given the request and the "
    "repository context (map, placement directory, exemplar files showing existing "
    "patterns), produce a plan as STRICT JSON only — no prose, no markdown fence.\n"
    'Format: {"summary": "one sentence", "files": ['
    '{"rel_path": "path/to/file.py", "op": "create|rewrite", "intent": "one line description"}'
    ']}\n'
    "Rules: reuse the import/framework style shown in the exemplar files. "
    "Prefer creating new files over rewriting large existing ones. "
    "Plan at most 3 files. rel_path must be relative to the repo root.\n"
    "If the request is genuinely ambiguous or you're missing information only the user "
    "can supply (which auth strategy, which of two plausible locations, an unstated "
    "business rule) — do not guess a plan. Instead output ONLY: "
    '{"question": "<your single, specific question>"}. '
    "Only do this when actually blocked, not out of caution."
)


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def make_planner_node(llm: BaseLanguageModel):
    async def planner(state: AgentState) -> AgentState:
        messages = [
            SystemMessage(content=_PLANNER_SYS),
            SystemMessage(content=state.get("context_sgl", "")),
            *state["messages"],  # full conversation — follow-ups ("also add tests for that") need it
        ]
        response = await llm.ainvoke(messages)
        raw = response.content or ""
        data = _extract_json(raw)
        plan = []
        summary = ""
        question = ""
        if data and isinstance(data.get("question"), str) and data["question"].strip():
            question = data["question"].strip()
        elif data and isinstance(data.get("files"), list):
            summary = data.get("summary", "")
            for f in data["files"][:3]:
                rel_path = f.get("rel_path", "").strip()
                op = f.get("op", "create")
                intent = f.get("intent", "")
                if rel_path and op in ("create", "rewrite", "append"):
                    plan.append({"rel_path": rel_path, "op": op, "intent": intent})

        logger.info("planner_done", plan_files=len(plan), question=bool(question),
                    raw_len=len(raw), raw_preview=raw[:500])

        progress = list(state.get("progress", []))
        if question:
            progress.append({"event": "clarify", "question": question})
        else:
            progress.append({"event": "plan_ready", "summary": summary, "files": plan})

        return {
            **state, "plan": plan, "plan_summary": summary,
            "clarifying_question": question,
            "plan_attempts": state.get("plan_attempts", 0) + 1, "progress": progress,
        }
    return planner


def grade_plan(state: AgentState) -> Literal["ok", "replan", "abandon", "ask"]:
    if state.get("clarifying_question"):
        decision = "ask"
    elif state.get("plan"):
        decision = "ok"
    elif state.get("plan_attempts", 0) < 2:
        decision = "replan"
    else:
        decision = "abandon"
    logger.info("grade_plan", decision=decision, plan_len=len(state.get("plan") or []),
                attempts=state.get("plan_attempts", 0))
    return decision


async def ask_user(state: AgentState) -> AgentState:
    """The planner needs information only the user can supply — end the turn with a question."""
    question = state.get("clarifying_question", "")
    return {**state, "messages": [*state["messages"], AIMessage(content=question)]}


_CODER_SYS = (
    "You write one complete source file. Output ONLY the file content inside a single "
    "fenced code block — no explanation before or after. Follow the import style and "
    "conventions shown in the exemplar files exactly. The file must be syntactically valid."
)


def make_coder_node(llm: BaseLanguageModel):
    async def coder(state: AgentState) -> AgentState:
        from langgraph.config import get_stream_writer
        try:
            writer = get_stream_writer()
        except Exception:
            writer = None

        write_ctx_block = state.get("context_sgl", "")
        pending: list[FileWrite] = []
        progress = list(state.get("progress", []))

        for i, task in enumerate(state.get("plan", [])):
            progress.append({
                "event": "writing_file", "rel_path": task["rel_path"],
                "index": i, "total": len(state["plan"]), "intent": task.get("intent", ""),
            })
            messages = [
                SystemMessage(content=_CODER_SYS),
                SystemMessage(content=write_ctx_block),
                HumanMessage(content=(
                    f"File: {task['rel_path']}\n"
                    f"Operation: {task['op']}\n"
                    f"Intent: {task.get('intent', '')}\n"
                    f"Write the complete file content now."
                )),
            ]
            content = ""
            try:
                # Stream tokens as they generate — this is what actually lets the UI
                # show "writing line 40 of ~..." instead of a spinner frozen for 20s.
                last_emit_len = 0
                async for chunk in llm.astream(messages):
                    piece = getattr(chunk, "content", "") or ""
                    if not piece:
                        continue
                    content += piece
                    if writer and len(content) - last_emit_len >= 24:
                        last_emit_len = len(content)
                        lines = content.count("\n") + 1
                        writer({
                            "event": "coding_progress", "rel_path": task["rel_path"],
                            "chars": len(content), "lines": lines,
                            "tail": content[-160:],
                        })

                code = _extract_code_block(content)
                logger.info("coder_done", rel_path=task["rel_path"], raw_len=len(content), code_len=len(code))
                if writer:
                    writer({
                        "event": "coding_progress", "rel_path": task["rel_path"],
                        "chars": len(content), "lines": content.count("\n") + 1,
                        "tail": content[-160:], "done": True,
                    })
                if code.strip():
                    pending.append(FileWrite(rel_path=task["rel_path"], op=task["op"],
                                              content=code, reason=task.get("intent", "")))
            except Exception as e:
                logger.error("coder_failed", rel_path=task["rel_path"], error=str(e), exc_info=True)

        return {**state, "_pending_writes": [p.model_dump() for p in pending], "progress": progress}
    return coder


def _extract_code_block(text: str) -> str:
    text = text.strip()
    fence = re.search(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    return text


def grade_writes(state: AgentState) -> Literal["ok", "abandon"]:
    n = len(state.get("_pending_writes") or [])
    logger.info("grade_writes", pending=n)
    return "ok" if n else "abandon"


async def apply_writes(state: AgentState) -> AgentState:
    logger.info("apply_writes_start", pending=len(state.get("_pending_writes") or []), repo_root=state.get("repo_root"))
    repo_root = state["repo_root"]
    auto_apply = state.get("auto_apply", True)
    results = []
    files_written = []
    errors = []
    progress = list(state.get("progress", []))

    for raw in state.get("_pending_writes", []):
        fw = FileWrite(**raw)
        res = apply_write(repo_root, fw) if auto_apply else preview_write(repo_root, fw)
        results.append(res.model_dump())
        if res.ok and res.applied:
            files_written.append(fw.rel_path)
        elif not res.ok:
            errors.append(f"{fw.rel_path}: {res.error}")
        progress.append({"event": "file_written", **res.model_dump()})

    if files_written:
        invalidate_repo_map(state["repo_id"])

    return {**state, "write_results": results, "files_written": files_written,
            "write_errors": errors, "progress": progress}


async def summarize_write(state: AgentState) -> AgentState:
    files_written = state.get("files_written", [])
    errors = state.get("write_errors", [])
    plan_summary = state.get("plan_summary", "")

    lines = []
    if files_written:
        lines.append(f"**{plan_summary or 'Implemented the requested change.'}**\n")
        lines.append("Files written:")
        for res in state.get("write_results", []):
            if res.get("applied"):
                lines.append(f"- `{res['rel_path']}` ({res['op']}, +{res['added']}/-{res['removed']} lines)")
    else:
        lines.append("I wasn't able to safely apply this change.")

    if errors:
        lines.append("\nIssues:")
        for e in errors:
            lines.append(f"- {e}")

    if not files_written and not errors and not state.get("plan"):
        lines = ["I couldn't produce a safe plan for this request — no files were identified to change."]

    content = "\n".join(lines)
    progress = [*state.get("progress", []), {
        "event": "implement_done",
        "applied": state.get("auto_apply", True),
        "files": state.get("write_results", []),
        "summary_md": content,
    }]
    return {**state, "messages": [*state["messages"], AIMessage(content=content)], "progress": progress}


async def abandon_to_read(state: AgentState) -> AgentState:
    """Write request we couldn't safely plan/execute — degrade to a read-style answer."""
    logger.warning("abandon_to_read", plan=state.get("plan"), pending=state.get("_pending_writes"))
    return {**state, "agent_type": "qa"}


# ── Graph factory ─────────────────────────────────────────────────────────

def build_agent_graph(llm: BaseLanguageModel) -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("classify", classify)
    graph.add_node("retrieve", retrieve_context)
    graph.add_node("widen", widen_retrieval)
    graph.add_node("retry", retry_retrieval)
    graph.add_node("llm", make_llm_node(llm))

    graph.add_node("plan_context", plan_context)
    graph.add_node("planner", make_planner_node(llm))
    graph.add_node("coder", make_coder_node(llm))
    graph.add_node("apply", apply_writes)
    graph.add_node("summarize", summarize_write)
    graph.add_node("abandon", abandon_to_read)
    graph.add_node("ask", ask_user)

    graph.set_entry_point("classify")
    graph.add_conditional_edges("classify", route_mode, {"read": "retrieve", "write": "plan_context"})

    graph.add_conditional_edges("retrieve", grade_context, {
        "sufficient": "llm", "widen": "widen", "retry": "retry",
    })
    graph.add_edge("widen", "llm")
    graph.add_edge("retry", "llm")
    graph.add_edge("llm", END)

    graph.add_edge("plan_context", "planner")
    graph.add_conditional_edges("planner", grade_plan, {
        "ok": "coder", "replan": "planner", "abandon": "abandon", "ask": "ask",
    })
    graph.add_conditional_edges("coder", grade_writes, {"ok": "apply", "abandon": "abandon"})
    graph.add_edge("apply", "summarize")
    graph.add_edge("summarize", END)
    graph.add_edge("abandon", "retrieve")
    graph.add_edge("ask", END)

    return graph.compile()
