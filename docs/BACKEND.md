# Backend — the agent harness

This is the part of the codebase that actually reads, debugs, reviews, and
writes code. If you're modifying agent behavior, this is the map.

## Files, in the order you'd read them

| File | Role |
|---|---|
| `agents/intent.py` | Pure-heuristic classifiers: read vs. write, qa/debug/review, role keywords, anchor extraction. No LLM calls — cheap and deterministic. |
| `agents/graph.py` | The LangGraph `StateGraph`: every node (`classify`, `retrieve_context`, `plan_context`, planner, coder, `apply_writes`, `summarize_write`) and the `AgentState` they share. |
| `agents/write_context.py` | Builds the write-path prompt context: placement directory, exemplar files, the wiring file. |
| `agents/write_tool.py` | The only code path allowed to touch the filesystem for a generated file: `safe_path`, `validate_write`, `apply_write`/`preview_write`. |
| `agents/autobuild.py` | The autonomous from-scratch build loop; reuses the same planner/coder/apply functions directly. |
| `agents/llm_factory.py` | Turns a `LLMProvider` DB row (or a dev-only fallback) into a `ChatOpenAI` client. |

## The read path

`classify()` → `retrieve_context()` → `grade_context()` → `llm` (with
`widen`/`retry` edges if coverage is poor).

`classify_intent()` in `intent.py` picks one of five strategies based on
keyword cues in the message: `entrypoints`, `historical` (git log), `structural`
(call-graph traversal via Neo4j full-text search), `subsystem` (role-tagged
symbols, e.g. "how does auth work"), or `semantic` (Qdrant similarity search
as a last resort). Each strategy assembles a different SGL ("Symbol card list")
block — see `INGESTION.md` for the format.

**`_read_referenced_files`** (in `graph.py`) is a deliberate exception to
"never send raw text, only graph-derived cards": if the message names a real
file by name (`_FILE_MENTION_RE`), its actual source is read off disk and
appended to context. This exists because a request like "check the syntax of
X" cannot be answered from signatures and call edges alone — the model needs
real text, and the backend already has filesystem access, so it should just
read the file instead of asking the user to paste it.

**Coverage grading is a character-count heuristic** (`_coverage()`): combined
context length `> 800` chars is "complete", `> 200` is "partial", otherwise
"sparse"/"empty". This is cheap but crude — 800 characters of irrelevant
symbol cards grades the same as 800 characters of exactly the right one. It's
a known, documented limitation, not an oversight.

## The write path

`plan_context()` (no LLM) → planner (1 LLM call) → coder (1 LLM call per
planned file) → `apply_writes` (no LLM) → `summarize_write` (no LLM).

### Planner reliability fixes

The planner's JSON output is a *guess*, not a filesystem query, and three
specific failure modes have been found and fixed by observing real usage:

1. **`create` vs. `rewrite` was pure LLM judgment.** The model repeatedly
   guessed `create` for files that already exist (a pre-written `README.md`
   is the most common case — `routers/repos.py` writes a stub before
   autobuild ever runs). `validate_write` correctly refuses to let `create`
   clobber an existing file, so the guess being wrong meant the write was
   silently dropped. Fix: `make_planner_node` now checks each planned file
   against the real filesystem via `_read_current_file` and flips the op if
   the model got it wrong, instead of trusting the guess.

2. **A zero-signal follow-up lost write mode.** `classify()` only looked at
   the latest message. A short reply like "yes please do it" — answering a
   clarifying question from the previous turn — carries no write/read cues of
   its own, and the tiebreak in `classify_mode()` defaults ties to "read",
   so the conversation could never recover into the write path after asking
   a single clarifying question. Fix: `classify_mode_with_history()` makes a
   zero-signal message inherit the most recent prior turn's classification
   instead of guessing.

3. **The planner invented a new path for the wiring file.** Even when the
   planner did try to wire new code in, it sometimes proposed editing e.g.
   `backend/app.py` when the only real entrypoint is `app.py` at the repo
   root — forking a duplicate file that gets "wired" while the actual running
   app is never touched. This looks like success (the write succeeds, no
   error) while doing nothing. Fix: `plan_context` now threads the real
   wiring file path(s) into state (`wiring_paths`), and `make_planner_node`
   snaps any planned path back to the real one whenever the basename matches.

4. **New code wasn't being wired in at all.** Before the fix above even
   mattered, the planner frequently just created a new file and stopped —
   the system prompt had no explicit instruction that a new module is dead
   code until something imports/registers/calls it. `_PLANNER_SYS` now says
   this explicitly, and `render_write_context`'s wiring-file block spells out
   *why* the edit matters instead of a soft "may need editing" hint.

5. **A retry re-issued the identical failing prompt.** When the planner's
   output was unparseable or empty and `grade_plan` routed back to `replan`,
   the second attempt got the exact same messages as the first — nothing
   told it what went wrong. Fix: `plan_last_raw_output` carries the failed
   response into the retry prompt with an explicit "don't repeat this" note.

### The coder

`make_coder_node` streams one file at a time via `llm.astream(...)`, emitting
`coding_progress` events (`get_stream_writer()`) so the UI can show live
character/line counts instead of a frozen spinner. For a `rewrite`, it now
reads the target file's actual current content (`_read_current_file`) and
prepends it to the prompt as a labeled block — the earlier behavior let the
model rewrite a file it had never seen, which the truncation guard doesn't
reliably catch (a same-length-but-wrong rewrite still "passes").

### The write tool (`agents/write_tool.py`)

`safe_path()` is the only function allowed to turn a model-supplied
`rel_path` into a real filesystem path: rejects absolute paths, null bytes,
path traversal, anything under a deny-listed directory (`.git`,
`node_modules`, `.env`, `.ssh`, …), and anything outside a broad but explicit
extension allow-list.

`validate_write()` checks, against the **full resulting content** (not just
an appended fragment): Python via `ast.parse`, JSON via `json.loads`, YAML
via `yaml.safe_load`; plus a truncation guard that rejects a `rewrite`
collapsing to under 50% of the original file's line count. `apply_write`
backs up the existing file (`.synapse.bak`) before writing atomically via a
temp-file + `os.replace`.

## The autonomous build loop (`agents/autobuild.py`)

Reuses `plan_context`, the planner/coder functions, and `apply_writes`
directly in a plain Python loop — there's no `classify` step because every
iteration is unconditionally a write. Each iteration:

1. Builds a query ("set up the initial project" on iteration 0, "continue
   building — the repo map above shows what exists so far" afterward).
2. Plans, codes, applies, and — if anything was written — re-indexes before
   the next iteration, so the planner's next repo map reflects reality
   rather than its own stale memory of what it intended to do.
3. Stops after two consecutive empty plans (the model signaling "nothing
   meaningful left to add") or a hard `max_iterations` cap.

Each iteration is persisted as a real `ChatMessage` pair in a dedicated
`ChatSession` (`build_session_id` on the `Repository`), reusing the exact
same `meta` shape (`write_results`, `plan_summary`) a manual chat turn
produces — this is what lets the homepage's "Ask AI" tab for a from-scratch
project show genuine task-by-task history instead of a single coarse
progress bar.

**Known fragility, not yet fixed:** each iteration is wrapped in a bare
`except Exception: break` — a single transient error (an LLM connection
drop, for instance) aborts the *entire* remaining build, not just that
iteration. This has been observed live: a build that should have produced
several files completed with 0 files written because the very first
iteration hit a connection error. The fix would be a bounded retry per
iteration instead of an immediate abort; it hasn't landed yet.

## Known gaps (by design, not oversight)

These are documented so they're not mistaken for bugs, and so anyone
extending the harness knows what ground truth to build on:

- **Nothing runs the code it writes.** There is no test-execution step, no
  lint/typecheck-and-retry loop, anywhere in the write path. A change is
  validated for syntax only, never behavior.
- **No human approval gate before a write lands on disk.** `preview_write`
  (full validation + unified diff, no filesystem write) exists and is fully
  implemented, but every call site hardcodes `auto_apply=True` — it's never
  actually reached in production.
- **The LLM has no tools.** Every node makes exactly one `ainvoke`/`astream`
  call with a pre-assembled context string. There's no `grep`, no "read one
  more file," no way for the model to look at something it wasn't handed —
  everything it might need has to be anticipated and included up front.
- **JS/TS parsing is regex-based, not a real AST.** `ingestion/ast_parser.py`
  gives Python full call-graph extraction; JS/TS symbols get `"calls": []`
  and no real signature parsing, so the call graph for those files is
  effectively structure-only (files, top-level defs) with no edges.
