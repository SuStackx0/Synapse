# Ingestion — from files on disk to graph-grounded context

## The pipeline

```
walk_repo() ──► parsed files (functions, classes, calls, imports, roles)
     │
     ├──► graph_builder.build_graph()  ──► Neo4j (structure)
     └──► embedder.index_symbols()     ──► Qdrant (embeddings)
```

`ingestion/ast_parser.py::walk_repo` walks the repo (skipping `.git`,
`node_modules`, `__pycache__`, etc.), and for each file dispatches to a
language-specific parser:

- **Python** gets a real AST walk: functions, classes, decorators, calls
  within each function's scope, imports, and a per-function `role` tag
  (see below).
- **JS/TS** (`parse_js_file_basic`) is regex-based, not a real parser: it
  finds top-level function/class-like declarations but returns `"calls": []`
  and no real signatures for every symbol. This means the call graph for a
  JS/TS-heavy repo is effectively file/symbol structure only, with no call
  edges — a known, documented limitation (see BACKEND.md's "Known gaps").

## Role tagging (`detect_role`)

Every parsed function gets a deterministic role tag used for retrieval
(`find_by_role`, `find_placement_files`) and for the write path's "where does
new code belong" decision: `API` (decorator-matched routes), `TEST`
(test-named functions), `DB`/`AI` (import-matched), `AUTH`/`CONFIG`
(path-matched), else `UTIL`.

**A real bug lived here for a while, worth knowing about if you touch this
function again:** the path match used to split `rel_path` on `/` and compare
raw segments against the role keyword set. For a file at the repo root named
exactly `auth.py`, the only segment is the string `"auth.py"` — which never
equals `"auth"`, because the extension stays glued to the segment. So a
root-level `auth.py` or `config.py` (the single most common layout) never got
tagged `AUTH`/`CONFIG` at all, and every "how does auth work" style query
silently found nothing. The fix strips the extension off the last segment
before comparing.

## The graph schema (Neo4j)

Node labels: `File`, `Directory`, `Symbol` (also dual-labeled `Function` or
tagged by kind), `Module`, `ErrorType`. Every node carries a stable `uid` —
`{repo_id}|{rel_path}` for files, `{repo_id}|{rel_path}#{qualname}` for
symbols — which is what the graph explorer and node-lookup API key on
(Neo4j's own internal `id()` is not stable across a reindex, since
`build_graph` opens with a full `clear_repo` + rebuild every time).

Key relationship: `CALLS`, carrying a `conf` (confidence) score — resolved
by matching call-site names against known symbols, so it's necessarily
approximate for dynamic dispatch, imported-under-an-alias calls, etc. Most
retrieval queries filter on `conf >= 0.5` or `>= 0.6`.

`Symbol.rank` exists in the schema (intended to drive "most important symbol
first" ordering in `find_by_role`/`find_entrypoints`/`symbol_card`) but is
currently written as a literal `0.0` at ingest time and never recomputed —
so today those `ORDER BY rank DESC` queries are effectively unordered.

## The SKL context format

`serialize_cards_to_sgl()` turns Neo4j symbol cards into a dense, LLM-legible
text block — this is the *only* form most read-path context takes (see
`ARCHITECTURE.md` on why raw file text is avoided by default). Files get
short local IDs (`F1`, `F2`, …); each symbol line encodes kind (`f`/`af`/`C`/
`k`/`t`), line number, complexity, call/called-by edges, and flags like
`ENTRY` (exposed/entrypoint) or `DEAD` (no known callers).

One caveat worth knowing if you touch the legend text: it currently tells
the model it can "ask for a body with `body <ref>`" — there is no such tool
implemented anywhere in the harness, so this line teaches the model an
affordance that doesn't exist. It hasn't caused an observed failure (models
mostly just don't use it), but it should either be implemented as a real
tool or removed rather than left as a dangling promise.

## Qdrant's actual job

`ingestion/embedder.py` wraps a local `SentenceTransformer` model
(`settings.embed_model`, default `all-MiniLM-L6-v2`) and two collections:
symbols (docstring + signature text) and commit messages. `search_symbols`/
`search_commits` return **UIDs and scores only** — every caller immediately
resolves those UIDs back through Neo4j (`resolve_uids_to_cards`) to get the
actual symbol card. Qdrant is consulted only as a fallback when lexical/
structural resolution in Neo4j comes up empty, or for genuinely semantic
("something vague, no clear keyword") queries.

## Git history

`ingestion/git_history.py` pulls commit metadata (sha, author, date, files
touched, message) via `git log`, which gets embedded into the same Qdrant
setup for the `historical` retrieval intent ("when did this change", "who
added X").

## Re-indexing triggers

Full re-index (`clear_repo` + rebuild both stores) happens: once on initial
connect, after every autobuild iteration that wrote files, and after a
manual file save from the in-app editor (`PUT /repos/{id}/file`) — the last
one is scoped to a lighter single-file re-parse + re-embed, not a full
`clear_repo`. There is no incremental/content-hash-based indexing; every
full reindex reprocesses the entire repo from scratch.
