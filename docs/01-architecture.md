# Synapse Architecture

## System Overview

Synapse is a multi-service system. Each service has a single responsibility:

```
Browser
  └─ Next.js (port 3000)         ← UI, SSR, API client
       └─ FastAPI (port 8000)    ← Orchestration, agent routing
            ├─ Neo4j (7687)      ← Code knowledge graph
            ├─ Qdrant (6333)     ← Semantic vector index
            └─ SQLite            ← Repo metadata, provider config
```

## Why This Stack?

### FastAPI + LangGraph (not Flask, not LangChain alone)

FastAPI gives us async I/O from day one — critical because agent calls involve multiple LLM roundtrips and DB lookups that should not block. Flask is synchronous by default.

LangGraph models the agent as a **directed acyclic graph** of nodes. Each node is a function that reads state and returns new state. This is a fundamental improvement over chain-style orchestration:

- Nodes run in parallel when there are no data dependencies
- State is typed (TypedDict), so bugs surface at definition time
- New agents are new graph configurations, not new classes

**Tradeoff**: LangGraph adds ~30MB of dependency weight and has a learning curve. Alternative: raw `asyncio` tasks — simpler but no graph visualization, no streaming state, no checkpointing.

### Neo4j (not PostgreSQL with adjacency lists)

The call graph is a property graph: nodes have labels (File, Function, Class), edges have types (DEFINES, IMPORTS, CALLS). Cypher, Neo4j's query language, expresses graph traversals that would require recursive CTEs in SQL:

```cypher
MATCH path = (f:Function {name: 'process_payment'})-[:CALLS*1..3]->(g)
RETURN path
```

The equivalent in PostgreSQL requires `WITH RECURSIVE` and is 5× harder to read and optimize.

**Tradeoff**: Neo4j needs its own container and ~512MB RAM. For tiny repos (<100 files), a NetworkX in-memory graph is faster. Neo4j wins at scale and at Cypher expressiveness.

### Qdrant (not Pinecone, not FAISS)

Qdrant is self-hosted, production-grade, and has a proper REST+gRPC API. FAISS is a library (no server, no persistence). Pinecone is cloud-only (no local development without billing).

For code search specifically: we chunk files at ~500 chars, embed with `all-MiniLM-L6-v2` (384-dim, runs on CPU, ~80MB), and do cosine similarity search. Qdrant returns the top-k chunks with their file path metadata — those chunks become the LLM's context window.

**Tradeoff**: Qdrant over Chroma because Qdrant has async client, better payload filtering, and a production-ready roadmap. Chroma is excellent for prototyping.

## Data Flow: A Single Chat Request

```
1. User types: "How does authentication work?"
2. POST /agents/chat {repo_id, message, agent_type: "qa"}
3. FastAPI → LangGraph: invoke graph
4. Node 1 (retrieve):
   - Embed query → 384-dim vector
   - Qdrant cosine search → top 8 code chunks
   - Neo4j query → file nodes connected to auth-related functions
   - Merge results into state.context_chunks
5. Node 2 (llm):
   - Build messages: [SystemPrompt, ContextChunks, UserMessage]
   - Async call to LLM endpoint (Gemma/OpenAI/etc.)
   - Stream response tokens
6. Response: SSE stream → frontend renders incrementally
```

Total latency: retrieval ~50ms, LLM ~2-10s depending on model.

## Ingestion Pipeline

When a repo is connected:

```
Repo path
  └─ walk_repo() → list of files (skip: .git, node_modules, __pycache__)
       ├─ parse_file() → AST nodes (functions, classes, imports, calls)
       │    ├─ Python: ast module (precise)
       │    └─ JS/TS: regex heuristic (approximate but fast)
       ├─ graph_builder.build_graph() → Neo4j nodes + edges
       ├─ embedder.index_files() → chunked, embedded, stored in Qdrant
       └─ git_history.get_commit_history() → commits embedded as text chunks
```

This runs in a FastAPI BackgroundTask — the HTTP response returns immediately with `status: "indexing"`. The frontend polls every 5 seconds until `repo.indexed == true`.

## Deployment

`docker compose up --build` spins up four containers with health checks. Neo4j and Qdrant are ready-checked before the backend starts (depends_on + condition: service_healthy). This prevents the "connection refused at startup" failure mode common in compose setups.
