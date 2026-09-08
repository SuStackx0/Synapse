# Synapse: What You Built and How to Talk About It

## The 4 Resume Bullets

These are the four bullet points to put on your resume. Use them verbatim or adjust numbers based on actual testing.

---

**1. System Architecture**

> Architected a codebase-intelligence platform combining Neo4j call-graph traversal with Qdrant vector search into a graph-augmented RAG pipeline — resolving semantic hits to AST symbols and expanding 1–2 hops across CALLS/IMPORTS edges to inject caller/callee context alongside retrieved code chunks.

**What this proves**: You understand that "RAG" is not just "embed + retrieve" — it's about the quality and structure of what you retrieve. Graph augmentation is a concrete, named technique that shows awareness of GraphRAG, not just vanilla RAG.

---

**2. Agent Orchestration**

> Built a routed multi-agent system in LangGraph (FastAPI + async Python) with intent classification, conditional retrieval routing (structural → Cypher, semantic → Qdrant), a context-quality grader with corrective re-query, and real-time retrieval traces streamed to the client over SSE.

**What this proves**: You went beyond "call the LLM" — you modeled control flow as a graph, added routing logic, and implemented the CRAG (Corrective RAG) pattern. Mentioning SSE streaming shows frontend/backend integration awareness.

---

**3. LLM Provider Abstraction**

> Designed a provider-agnostic LLM layer spanning vLLM, SGLang, Ollama, OpenAI, and Anthropic behind a single OpenAI-compatible interface, with side-by-side benchmarking that records response quality, latency, and pairwise votes — enabling data-driven model selection without code changes.

**What this proves**: You thought about operationalizing AI systems, not just building them. Model selection and evaluation are real engineering concerns. The zero-code-change switching shows good abstraction design.

---

**4. Infrastructure and Data Engineering**

> Engineered an end-to-end indexing pipeline on a 4-service Docker Compose stack (Neo4j, Qdrant, FastAPI, Next.js) using Python AST parsing for code structure extraction, GitPython for commit history ingestion into a shared vector space, and background-safe session management for async database writes.

**What this proves**: You know how to compose real infrastructure, understand async Python session lifecycle (the session bug fix is a real production concern), and built a non-trivial data pipeline rather than a toy demo.

---

## Talking Points for Technical Interviews

### "Walk me through the architecture."

Start at the request: user asks a question → FastAPI → LangGraph graph → retrieve node (Qdrant cosine search + Neo4j Cypher expansion) → grade node (quality check) → LLM node → SSE stream back. Talk about why each database exists (Neo4j for graph traversal, Qdrant for semantic similarity — neither can do the other's job well).

### "Why LangGraph instead of just calling the LLM?"

LangGraph models agent logic as a directed graph of functions. This lets you: add conditional edges (route by intent), implement retry loops (corrective RAG), and reason about agent behavior as a state machine rather than a string of function calls. It also gives you checkpointing for free if you add persistence.

### "What would you do differently at production scale?"

1. Replace `all-MiniLM-L6-v2` with a code-specific embedding model (`nomic-embed-code`, `voyage-code-3`)
2. Switch from fixed-width chunking to AST-boundary chunking (one chunk = one function/class)
3. Add hybrid search (BM25 dense fusion with Qdrant sparse vectors) for exact identifier matching
4. Move indexing to a proper task queue (Celery/arq) with a Redis broker
5. Add a retrieval eval harness (Recall@k, MRR, RAGAS faithfulness) on a golden question set

### "What's the hardest bug you fixed in this project?"

The FastAPI session bug: `bg.add_task(_index_repo, ..., db)` was passing a request-scoped SQLAlchemy `AsyncSession` to a background task that runs after the HTTP response closes the session. The fix is to give the background task its own session: `async with SessionLocal() as db:` inside the task. This is a subtle async Python lifecycle issue — the session is bound to the request context, not the task lifetime.

### "What does Neo4j give you that PostgreSQL wouldn't?"

Recursive graph traversal in Cypher is idiomatic: `MATCH (fn)-[:CALLS*1..3]->(callee)`. In PostgreSQL this requires `WITH RECURSIVE`, which is verbose and harder to optimize. For a property graph with heterogeneous node types (File, Function, Class, Module) and typed edges (DEFINES, IMPORTS, CALLS), a native graph database is the right abstraction.

---

## Numbers to Know

- Embedding dimensions: **384** (all-MiniLM-L6-v2)
- Chunk size: **500 chars**
- Max files per repo: **500** (configurable)
- Max commits indexed: **200**
- Top-k retrieval: **8 chunks**
- Graph expansion: **2 hops** from each retrieved chunk's symbols
- Docker Compose services: **4** (neo4j, qdrant, backend, frontend)
- Supported languages for AST parsing: **Python** (precise), **JS/TS/JSX/TSX** (heuristic)
- Supported LLM backends: **vLLM, SGLang, Ollama, OpenAI, Anthropic** (any OpenAI-compatible)
