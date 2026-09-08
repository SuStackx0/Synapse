# Feature Design Decisions

## Repo Brain: Force-Directed Graph

The graph visualization uses D3's `forceSimulation` — a physics simulation where nodes repel each other and edges act as springs. The simulation converges to a layout where:
- Connected nodes cluster together (they're pulled by edge springs)
- Unconnected nodes spread out (repulsion force)
- The overall shape reveals the module structure of the codebase

**Color encoding**:
- Blue (`#1e3a5f`) + Cyan border → Files (the largest structural unit)
- Dark green + Green border → Functions (the most numerous)
- Purple → Classes
- Yellow → External modules/imports

This is not decorative. Color preattentively encodes node type — engineers can identify "this repo is function-heavy, few classes" at a glance before reading a single label.

**Filtering**: users can filter to show only Files, only Functions, etc. This is implemented by recomputing the simulation from scratch with a subset of nodes and edges. The D3 simulation is destroyed and recreated on filter change.

**Why D3, not a library like react-force-graph?** D3 gives full control over forces, transition behavior, and SVG elements. Libraries wrap D3 and add convenience at the cost of customizability. Since the visual design is a core product differentiator, raw D3 was the right call.

## Vibe Check: Code Health Dashboard

The health score is computed entirely server-side from the same AST parse used for indexing:

```
score = 100
- 3 points per file with >300 lines (max -20)
- 1 point per potentially dead function (max -15)
```

"Potentially dead" means: the function name does not appear in any call list across the repo. This is a heuristic, not ground truth — it misses:
- Functions called via `getattr` or dynamic dispatch
- Functions used as callbacks or registered handlers
- Entry points (main, test functions)

The dashboard intentionally presents this as "potentially unused" not "dead code". Language matters — false precision in tooling erodes trust.

**Language breakdown** uses a D3-style horizontal bar chart built in pure CSS (`width: ${pct}%`). Avoiding a charting library for a simple bar chart is the right call: less JavaScript bundle, no version conflicts, full control.

## Model Benchmarker: Why This Feature Exists

The benchmarker is the most technically opinionated feature. It makes a claim: different models produce qualitatively different answers to the same question about the same codebase, and developers should be able to measure this.

The workflow:
1. Select two providers from the settings panel
2. Enter a query (runs against the indexed repo's vector context)
3. Both models are called concurrently (two separate LangGraph runs)
4. Responses and latencies are displayed side-by-side
5. User votes for the better answer; vote is persisted to SQLite

**Concurrency**: the two LLM calls are sequential in the current implementation (for simplicity). Upgrading to `asyncio.gather(run_a(), run_b())` would halve the wait time.

**Leaderboard potential**: each vote is stored with `winner` field. With enough votes, you can compute win rates per model per repo type — this is meaningful data for teams evaluating which model to use.

## Settings: Provider System Design

The provider system is designed around one constraint: all inference APIs, whether OpenAI, Anthropic (via proxy), or local vLLM servers, expose the same HTTP interface (`POST /v1/chat/completions`). This means a single HTTP client (LangChain's `ChatOpenAI`) parameterized with `base_url` can talk to all of them.

The provider row in SQLite stores:
- `base_url`: the endpoint (e.g., `http://10.29.210.8:8711/v1`)
- `model`: the model identifier (e.g., `gemma4`)
- `api_key`: empty string for local deployments, actual key for cloud APIs
- `is_active`: only one row can be true at a time

Switching providers is a single `UPDATE` statement. No config file edits, no container restarts.

**Why no env variables?** Env variables require a restart to change. A database row change is instant and requires no DevOps access. For a multi-user team tool, this is the correct design.

## Streaming Chat Responses

Chat uses Server-Sent Events (SSE) rather than polling or WebSockets. The choice:

- **Polling**: client hits the server every N seconds to check for new content — wastes bandwidth, introduces latency
- **WebSockets**: bidirectional — overkill for one-directional LLM streaming
- **SSE**: server pushes data over an open HTTP connection, client receives incrementally — exactly right for LLM token streaming

The SSE format is simple: `data: {json}\n\n`. The frontend uses a `ReadableStream` reader to consume the response body incrementally.

**Current simplification**: Synapse buffers the entire LLM response and sends it as one SSE event. True token-by-token streaming requires the LangGraph `astream_events` API and a streaming-aware LLM client. This is the next implementation step.

## Git History Indexing

Embedding commit history alongside code enables queries like:
- "What changed in the auth module last month?"
- "Who introduced the rate limiter and why?"
- "Find commits that mention the payment bug"

Each commit is serialized as: `"Commit SHA: message\nFiles: ...\ndiff preview..."` and chunked at 1000 characters. The diff preview (first 3000 chars) gives the model concrete code change context.

**Limitation**: with `--depth 50` during GitHub clone, shallow clones miss older history. For local repos, we index up to 200 commits.

**Design decision**: commits are indexed into the same Qdrant collection as code files, with `language: "git"` as a payload field. This means a single search query simultaneously retrieves relevant code AND relevant commits — the model sees both, enabling answers that connect current code to historical context.
