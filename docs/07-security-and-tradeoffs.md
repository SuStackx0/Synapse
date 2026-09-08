# Security Considerations and Known Tradeoffs

## Security Issues (Know These for Interviews)

### 1. API Keys Stored Plaintext
`core/models.py` stores `api_key` as a plain `Mapped[str]`. In production, this should be encrypted at rest using `cryptography.Fernet` with a key derived from an environment variable:

```python
from cryptography.fernet import Fernet
import os

_fernet = Fernet(os.environ["SECRET_KEY"].encode())

def encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()

def decrypt(value: str) -> str:
    return _fernet.decrypt(value.encode()).decode()
```

Store the encrypted value, decrypt only at LLM call time. The `GET /settings/providers` endpoint should redact `api_key` (return `"***"`).

### 2. Local Repo Path Traversal
`POST /repos/local` accepts any absolute path and calls `shutil.copytree`. A malicious caller could point it at `/etc` or any sensitive directory. Fix: validate that the path is within an allowlist (`/repos`, `~`, project directories) before copying.

### 3. GitHub PAT in Request Body
The PAT is passed in the request body and injected into the git clone URL. It is not logged (we don't log request bodies), but it should not be stored — only used for the clone, then discarded.

### 4. No Authentication
There is no auth on any endpoint. This is intentional for a local development tool. For a multi-user deployment, add OAuth2 + JWT (FastAPI's `OAuth2PasswordBearer` or an external provider).

---

## Deliberate Architectural Tradeoffs

| Decision | What Was Chosen | What Was Not Chosen | Why |
|---|---|---|---|
| Embedding model | all-MiniLM-L6-v2 (CPU, local) | nomic-embed-code, voyage-code-3 | Zero cost, zero API calls, runs in container |
| Chunking | Fixed 500-char windows | AST-boundary (per function) | Simpler to implement; easy upgrade path |
| LLM client | langchain ChatOpenAI | openai SDK directly | One client for all OpenAI-compatible endpoints |
| Vector DB | Qdrant | Chroma, Pinecone, FAISS | Self-hosted, async client, production-grade |
| Graph DB | Neo4j | PostgreSQL recursive CTEs | Native Cypher traversal syntax |
| Agent framework | LangGraph | LangChain chains, raw asyncio | Conditional edges, corrective loops |
| Frontend | Next.js + Tailwind | React + Vite, Streamlit | SSR, App Router, recruiter recognition |
| Indexing | FastAPI BackgroundTask | Celery, arq | Lower infrastructure footprint for demo |
| Persistence | SQLite | PostgreSQL | Zero infra, embeds in Docker volume |
| Streaming | SSE (Server-Sent Events) | WebSockets, polling | Unidirectional stream, HTTP-native |

Each tradeoff is defensible and documented. Being able to articulate *why* you made each choice — and what the upgrade path is — is more impressive than having made the "right" choice without knowing why.

---

## What "Production-Ready" Would Add

1. **Authentication**: OAuth2 + JWT, user isolation in the DB
2. **Secret encryption**: Fernet-encrypted API keys, redacted in API responses
3. **Task queue**: Celery + Redis for indexing, with live progress via SSE
4. **Incremental indexing**: blake2b hashes per file, re-embed only changed files
5. **AST-boundary chunking**: one chunk per function/class, with `qualified_name` and `docstring` in payload
6. **Hybrid search**: Qdrant sparse vectors (BM25) + dense, fused with Reciprocal Rank Fusion
7. **Cross-encoder reranking**: top-30 candidates → rerank to top-6 for LLM context
8. **Retrieval eval harness**: golden Q&A set, Recall@k / MRR scoring, RAGAS faithfulness
9. **Rate limiting**: `slowapi` middleware per IP
10. **Observability**: structured JSON logs (structlog), OpenTelemetry traces, Prometheus metrics

These are not missing because of ignorance — they're scope decisions for a portfolio project. Know all of them.
