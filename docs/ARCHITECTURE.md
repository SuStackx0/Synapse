# Architecture

## System overview

```
                         ┌─────────────────────────────────┐
                         │           Next.js frontend        │
                         │  (App Router, Tailwind, D3, CM6)  │
                         └────────────────┬──────────────────┘
                                          │ REST + SSE
                         ┌────────────────▼──────────────────┐
                         │            FastAPI backend          │
                         │  routers/  agents/  ingestion/ core/ │
                         └───┬─────────────┬──────────────┬────┘
                             │             │              │
                    ┌────────▼───┐ ┌───────▼──────┐ ┌─────▼─────┐
                    │   Neo4j     │ │   Qdrant     │ │  SQLite   │
                    │ call graph  │ │  embeddings  │ │ sessions, │
                    │ (structure) │ │ (entity link)│ │ repos,    │
                    │             │ │              │ │ providers │
                    └─────────────┘ └──────────────┘ └───────────┘
```

Four services, orchestrated by `docker-compose.yml`: `frontend`, `backend`,
`neo4j`, `qdrant`. SQLite is a file inside the backend container (no separate
service) — see `backend/core/database.py` / `backend/core/models.py`.

## Why two databases, not one

This is the one architectural decision worth understanding before anything
else, because it shapes almost every file in `backend/agents/` and
`backend/ingestion/`:

- **Neo4j is structure.** Files, functions, classes, call edges, imports,
  directory containment. Every piece of text that reaches an LLM prompt is
  built from data pulled out of Neo4j (see `serialize_cards_to_sgl` in
  `ingestion/graph_builder.py`).
- **Qdrant is an entity linker, not a text source.** It embeds symbol
  docstrings/signatures and commit messages, and a similarity search returns
  **UIDs only** — those UIDs are then resolved back into real symbol cards
  through Neo4j. Qdrant's job is "which symbols are probably relevant," never
  "what does this code say."

The practical effect: retrieval quality depends on the graph being complete
and current, not on embedding quality. See `INGESTION.md` for how the graph
gets built and kept current, including a real bug found and fixed this
project's history (`detect_role()` silently mis-tagging root-level files).

## Request flow: asking a question (read path)

1. Frontend POSTs to `POST /agents/chat` (`routers/agents.py`) with
   `{repo_id, message, session_id}`.
2. The router loads prior turns for that session (if any) from SQLite so
   follow-ups have context, persists the new user message, then builds a
   LangGraph `AgentState` and streams `graph.astream(...)`.
3. Inside the graph (`agents/graph.py`): `classify()` decides read vs. write
   using a heuristic word-scorer (`agents/intent.py`) that also considers the
   *previous* turn when the new message carries no signal of its own (a bare
   "yes" shouldn't flip mode back to read — see BACKEND.md).
4. For a read: `retrieve_context()` picks a retrieval strategy based on
   `classify_intent()` (entrypoints / historical / structural / subsystem /
   semantic), pulls symbol cards from Neo4j, grades coverage, and — if the
   message names specific files — reads their real source straight off disk
   too (`_read_referenced_files`), so "check the syntax of X" gets grounded
   answers instead of the model asking the user to paste code.
5. `make_llm_node` sends the assembled context + conversation history to the
   active LLM and streams the answer back over SSE, persisting the final
   turn to SQLite when it's done.

## Request flow: making a change (write path)

1. Same entry point, but `classify()` routes to `plan_context()` →
   `make_planner_node` → `make_coder_node` → `apply_writes` →
   `summarize_write`.
2. `plan_context` (no LLM call) uses the graph to pick a placement directory,
   up to 3 "exemplar" files showing existing patterns, and — critically — the
   file(s) that register/import/call things into the running app (the
   "wiring file", found by `find_wiring_files`: `main.py`/`app.py`/
   `__init__.py`/`urls.py`).
3. `make_planner_node` (1 LLM call) turns the request + that context into a
   strict-JSON plan: which files, `create`/`rewrite`/`append`, one-line
   intent each. Two deterministic corrections run on the model's output
   before it becomes the real plan (both added after real bugs were found in
   production use — see BACKEND.md for the specifics):
   - the `create`/`rewrite` choice is checked against the real filesystem
     and flipped if wrong;
   - a planned path is snapped back to the real wiring file's path if the
     model invented a new location for it (e.g. `backend/app.py` when the
     only real entrypoint is `app.py` at repo root).
4. `make_coder_node` (1 LLM call per planned file, streamed token-by-token
   over SSE) generates each file's full content. For a `rewrite`, it now
   reads the file's actual current contents first and includes them in the
   prompt — otherwise the model would rewrite a file it has never seen.
5. `apply_writes` validates each file (`agents/write_tool.py`: path-traversal
   guard, extension allow-list, syntax gate — `ast.parse` for Python,
   `json.loads`/`yaml.safe_load` for config files, checked against the full
   resulting content including for `append`) and only then writes it to disk
   atomically with a `.synapse.bak` backup.
6. `summarize_write` renders a deterministic markdown summary (no LLM call);
   the frontend also gets a structured `write_results` list it renders as a
   file-diff manifest.

## Autonomous project scaffolding

`POST /repos/new` (`routers/repos.py`) creates an empty git-initialized
directory and kicks off `agents/autobuild.py::run_autonomous_build` as a
background task. It reuses the exact same `plan_context` → planner → coder →
`apply_writes` functions as a single chat turn, just called directly in a
Python loop (there's nothing to classify — every iteration is unconditionally
a write) instead of through the full graph. Each iteration re-indexes before
the next one plans, so the planner sees everything actually written so far,
not just its own memory of what it intended. It stops after two consecutive
empty plans or a hard iteration cap.

Each iteration's plan/write results are persisted into a real `ChatSession`
(`build_session_id` on the `Repository` row), so opening that repo's "Ask AI"
tab shows the exact same step-by-step activity feed and file-diff manifest a
manual implement turn gets — not a separate, coarser progress UI.

## Data model (SQLite)

`core/models.py`: `Repository` (indexing status/stage/path/source),
`LLMProvider` (base_url/model/**encrypted** api_key/is_active),
`ChatSession` + `ChatMessage` (persisted conversations, `meta` JSON carries
mode/retrieval-trace/write-results so history can be replayed into the UI
verbatim), `BenchmarkResult` (side-by-side provider comparisons).
