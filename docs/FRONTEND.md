# Frontend

Next.js 14 (App Router), TailwindCSS, D3 (graph explorer), CodeMirror 6 (file
editor panel). Dark-theme only; no light mode.

## Pages

| Route | File | Purpose |
|---|---|---|
| `/` | `app/page.tsx` | Repo list + the "Connect Repository" modal (Local Path / GitHub / New Project — the three ways to bring in a codebase). |
| `/repo/[id]` | `app/repo/[id]/page.tsx` | The main workspace: four tabs — Ask AI, Repo Brain, Vibe Check, Benchmark. |
| `/settings` | `app/settings/page.tsx` | LLM provider management (add/activate/delete; API keys are encrypted server-side, see `core/crypto.py`). |

## The chat surface (`components/chat/`)

`ChatPanel.tsx` is the largest component and the one most worth understanding
before touching UI. Its message rendering deliberately treats the user's turn
and the assistant's answer asymmetrically: the user's message is a contained
card, the assistant's answer is the uncontained, primary element on the page
— metadata (retrieval intent/coverage, the step trail) is demoted to a
footer below the answer rather than a header above it, because early
versions put four competing pieces of small-print chrome *before* the actual
answer, which read as unpolished.

Supporting pieces:

- **`SessionSidebar.tsx`** — session list + switching. Sessions persist in
  SQLite (`ChatSession`/`ChatMessage`); `messagesFromHistory()` in
  `ChatPanel.tsx` reconstructs the full `Message[]` shape (including
  retrieval traces and write-result diffs) from persisted rows, so a
  reloaded session looks identical to a live one.
- **`FilePanel.tsx`** — the right-side CodeMirror editor, opened when a
  written (or any) file is clicked. Loads/saves through
  `GET`/`PUT /repos/{id}/file`.
- **`streamChat()`** — a raw `fetch` + manual SSE line-parser (not
  `EventSource`, since it's a `POST` with a body). Events it handles:
  `session`, `step`, `mode`, `context_ready`, `clarify`, `plan_ready`,
  `writing_file`, `coding_progress` (live token-streamed file content),
  `file_written`, `retrieval_done`, `answer`.

## Repo Brain (`components/graph/GraphExplorer.tsx`)

A D3 force-directed graph of the repo's Neo4j nodes/edges, fetched via
`GET /graph/{repoId}`. Nodes are keyed by the graph's stable `uid` string
(not Neo4j's internal id — see `INGESTION.md`), which is what makes a
node-detail fetch (`GET /graph/{repoId}/node/{uid}`) survive a reindex.

## Vibe Check (`components/health/HealthDashboard.tsx`)

Renders `GET /health/{repoId}`: file/line/function/class counts, a language
breakdown, large-file hotspots, and a "potentially unused functions" list —
the last one is a real Neo4j query over live `CALLS` edges (true call-graph
fan-in), not a string-matching heuristic, so it correctly excludes
entrypoints/API routes/tests that legitimately have no in-repo callers.

## Benchmark (`components/benchmark/Benchmarker.tsx`)

Runs the same query against two configured providers side by side
(`POST /agents/benchmark`) and records a vote. Needs at least two providers
configured in Settings to be usable.

## Design system

`tailwind.config.js` defines the full dark palette as named tokens
(`bg`, `surface`, `surface-2/3`, `surface-code`, `border`, `border-subtle`,
`text`, `text-2/3`, `muted`, plus semantic `cyan`/`green`/`red`/`amber`).
Rules worth preserving if you extend the UI: no glow/gradient effects, no
pill-shaped badges for non-status data, monospace reserved for code/paths
(not general UI labels), and a real typographic scale in `globals.css`'s
`.prose-synapse` block for markdown-rendered answers (headings are
distinctly larger/bolder than body text — an earlier version had them at
nearly the same size, which read as "one gray wall of text").
