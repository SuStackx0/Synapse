# RAG, Embeddings, and the Agent Architecture

## What is RAG?

RAG — Retrieval-Augmented Generation — is the pattern of retrieving relevant context from a data store and injecting it into the LLM's prompt before generation. Without RAG, the LLM answers from its training weights alone. With RAG, it answers from your actual codebase.

The key insight: LLMs have a fixed context window (8K–128K tokens). A real codebase has millions of tokens. RAG is the bridge — it selects only the most relevant 4-8 code chunks (a few hundred tokens each) to include.

## Embedding Model Choice

Synapse uses `all-MiniLM-L6-v2` from sentence-transformers:

- **384 dimensions** — small enough to fit 10M+ vectors in RAM, fast to compute
- **Cosine similarity** — normalized dot product between vectors; 1 = identical, 0 = orthogonal, -1 = opposite
- **CPU inference** — no GPU needed; ~5ms per chunk on modern CPU
- **MIT licensed** — no restrictions on use

The alternative (text-embedding-3-small from OpenAI) costs money per token and requires an internet connection. `all-MiniLM-L6-v2` runs entirely in the Docker container.

**Tradeoff**: it was trained on general text, not code specifically. Models like `nomic-embed-code` or `voyage-code-3` would give better code retrieval. This is a documented known limitation and an obvious upgrade path.

## Chunking Strategy

We chunk files at fixed 500-character windows with no overlap. This is the simplest possible strategy.

Better alternatives (in order of sophistication):
1. **Overlapping windows** (e.g., 500 chars, 100-char overlap) — prevents context loss at chunk boundaries
2. **Semantic chunking** — split at function/class boundaries from the AST parse
3. **Hierarchical indexing** — store both file-level and function-level embeddings, retrieve at appropriate granularity

The current approach works for a demo. For production, AST-aware chunking (splitting at function boundaries, one chunk per function) would be the right call — it aligns the retrieval unit with the semantic unit.

## LangGraph Agent Architecture

### Why a Graph Model?

Traditional LLM applications use linear chains: input → prompt → LLM → output. LangGraph models the agent as a directed graph of nodes where:

- Each **node** is a Python function: `(state) → updated_state`
- **Edges** define control flow: which node runs after which
- **State** is a typed dictionary shared across all nodes

This enables patterns impossible in linear chains:
- **Conditional routing**: "if the query mentions an error, route to the debug node"
- **Cycles**: "if the answer doesn't cite a source, re-retrieve and retry"
- **Parallelism**: "retrieve from Neo4j and Qdrant simultaneously"

### Synapse's Agent Graph

```
START
  └─ retrieve (async)
       ├─ Embed the user's query
       ├─ Qdrant search → top 8 code chunks
       └─ Inject chunks into state.context_chunks
  └─ llm (async)
       ├─ Select system prompt by agent_type (qa / debug / review)
       ├─ Build message list: [system, context, history, user_message]
       ├─ Call LLM via OpenAI-compatible API
       └─ Append AI response to state.messages
END
```

### Three Agent Modes

| Mode | System Prompt Focus | Best For |
|---|---|---|
| `qa` | "Answer accurately using code context. Cite file paths." | Understanding code structure |
| `debug` | "ROOT CAUSE → EXPLANATION → FIX format." | Error analysis |
| `review` | "Numbered findings with HIGH/MEDIUM/LOW severity." | Code quality |

The same graph, different system prompts. This is intentional — the retrieval logic is identical; only the generation instruction changes.

## LLM Provider Abstraction

All LLM calls go through `langchain_community.ChatOpenAI` with a configurable `base_url`. This works because:
- OpenAI published an API spec that became the de facto standard
- vLLM, SGLang, Ollama, and LM Studio all implement `/v1/chat/completions`
- So one client library talks to all of them

The provider config is stored in SQLite. At request time, we fetch the active provider and pass its `base_url`, `api_key`, and `model` to `ChatOpenAI`. Switching models requires no code change — just a database row update through the settings UI.

**Tradeoff**: Anthropic's API does not implement the OpenAI spec natively (different request/response shape). We use `langchain-anthropic` for it, but for simplicity the UI currently treats it as OpenAI-compatible. A proper fix: abstract the LLM factory behind a protocol with per-provider adapters.

## Commit History as Searchable Context

Git commits are indexed as text chunks: `"Commit abc123: Fix null pointer in auth middleware\nFiles: auth/middleware.py\ndiff..."`. When a user asks "what changed in auth last month?", the embedding of that query is close in vector space to the commit chunks that modified auth files.

This is a qualitative improvement over raw `git log` because:
- Users can ask in natural language, not remember git syntax
- Semantic similarity finds relevant commits even if the query words don't exactly match the commit message
- Commits are integrated into the same search index as code — a single retrieval step gets both
