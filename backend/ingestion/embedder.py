"""
Qdrant vector store.

Design principle (Opus review):
  The vector store embeds PROSE ONLY — docstrings, comments, summaries,
  commit messages. Never raw code. Qdrant returns UIDs; Neo4j returns text.

Collections:
  syn_sym_{repo_id}    — one point per symbol (doc + sig context)
  syn_commit_{repo_id} — one point per commit message
"""
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
)
from sentence_transformers import SentenceTransformer
from core.config import settings
from typing import List, Dict, Any
import uuid
import structlog

logger = structlog.get_logger()

VECTOR_SIZE = 384  # all-MiniLM-L6-v2 — correct model for prose, not code


class Embedder:
    def __init__(self):
        self._client: AsyncQdrantClient = None
        self._model: SentenceTransformer = None

    async def init(self):
        self._client = AsyncQdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
        )
        self._model = SentenceTransformer(settings.embed_model)
        logger.info("embedder_initialized", model=settings.embed_model)

    def _sym_col(self, repo_id: str) -> str:
        safe = repo_id.replace("-", "_")
        return f"syn_sym_{safe}"

    def _commit_col(self, repo_id: str) -> str:
        safe = repo_id.replace("-", "_")
        return f"syn_commit_{safe}"

    async def _ensure_collection(self, name: str):
        exists = await self._client.collection_exists(name)
        if not exists:
            await self._client.create_collection(
                name,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )

    def _embed(self, texts: List[str]) -> List[List[float]]:
        return self._model.encode(texts, convert_to_numpy=True).tolist()

    def _build_prose(self, fn: Dict) -> str:
        """Build embeddable prose from a function/class record — no raw code."""
        parts = []
        kind = "async function" if fn.get("is_async") else "function"
        if fn.get("is_method"):
            kind = "method"
        if fn.get("is_test"):
            kind = "test"
        qualname = fn.get("qualname") or fn.get("name", "")
        sig = fn.get("sig", "")
        doc = fn.get("doc", "")
        raises = fn.get("raises", [])
        decos = fn.get("decorators", [])

        parts.append(f"{kind} {qualname}")
        if sig:
            parts.append(f"signature: {sig}")
        if doc:
            parts.append(doc)
        if raises:
            parts.append(f"raises: {', '.join(raises)}")
        if decos:
            parts.append(f"decorated with: {', '.join(decos)}")
        return ". ".join(p for p in parts if p)

    async def index_symbols(self, repo_id: str, parsed_files: List[Dict[str, Any]]):
        """Index prose representations of all symbols — not raw code."""
        col = self._sym_col(repo_id)
        await self._ensure_collection(col)

        points = []
        for f in parsed_files:
            rel = f.get("rel_path", "")
            lang = f.get("language", "unknown")

            for fn in f.get("functions", []) + f.get("classes", []):
                prose = self._build_prose(fn)
                if not prose.strip():
                    continue
                uid = f"{repo_id}|{rel}#{fn.get('qualname', fn.get('name',''))}"
                points.append({
                    "id": str(uuid.uuid4()),
                    "text": prose,
                    "payload": {
                        "uid": uid,
                        "repo_id": repo_id,
                        "rel_path": rel,
                        "language": lang,
                        "name": fn.get("name", ""),
                        "qualname": fn.get("qualname", ""),
                        "kind": "class" if "bases" in fn else "function",
                    },
                })

        if not points:
            return

        batch_size = 64
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            vectors = self._embed([p["text"] for p in batch])
            await self._client.upsert(col, points=[
                PointStruct(id=p["id"], vector=v, payload=p["payload"])
                for p, v in zip(batch, vectors)
            ])

        logger.info("symbols_indexed", repo_id=repo_id, count=len(points))

    async def index_commits(self, repo_id: str, commits: List[Dict[str, Any]]):
        """Index commit messages only — not diffs."""
        col = self._commit_col(repo_id)
        await self._ensure_collection(col)

        points = []
        for c in commits:
            msg = c.get("message", "").strip()
            if not msg:
                continue
            files = ", ".join(c.get("files_changed", [])[:5])
            prose = f"commit {c.get('sha','')}: {msg}. files: {files}"
            points.append({
                "id": str(uuid.uuid4()),
                "text": prose,
                "payload": {
                    "uid": f"{repo_id}|commit|{c.get('sha','')}",
                    "repo_id": repo_id,
                    "sha": c.get("sha", ""),
                    "files": c.get("files_changed", []),
                    "date": c.get("date", ""),
                    "author": c.get("author", ""),
                    "kind": "commit",
                },
            })

        if not points:
            return

        batch_size = 64
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            vectors = self._embed([p["text"] for p in batch])
            await self._client.upsert(col, points=[
                PointStruct(id=p["id"], vector=v, payload=p["payload"])
                for p, v in zip(batch, vectors)
            ])

        logger.info("commits_indexed", repo_id=repo_id, count=len(points))

    async def search_symbols(self, repo_id: str, query: str, limit: int = 12) -> List[Dict]:
        """Search symbol prose. Returns UIDs and payloads — no text to LLM."""
        col = self._sym_col(repo_id)
        await self._ensure_collection(col)
        vector = self._embed([query])[0]
        response = await self._client.query_points(col, query=vector, limit=limit, with_payload=True)
        return [
            {
                "uid": r.payload.get("uid"),
                "score": r.score,
                "qualname": r.payload.get("qualname"),
                "rel_path": r.payload.get("rel_path"),
                "kind": r.payload.get("kind"),
            }
            for r in response.points
        ]

    async def search_commits(self, repo_id: str, query: str, limit: int = 8) -> List[Dict]:
        """Search commit history by prose similarity."""
        col = self._commit_col(repo_id)
        await self._ensure_collection(col)
        vector = self._embed([query])[0]
        response = await self._client.query_points(col, query=vector, limit=limit, with_payload=True)
        return [
            {
                "uid": r.payload.get("uid"),
                "score": r.score,
                "sha": r.payload.get("sha"),
                "files": r.payload.get("files", []),
                "date": r.payload.get("date"),
                "author": r.payload.get("author"),
            }
            for r in response.points
        ]

    async def delete_collections(self, repo_id: str):
        for col in [self._sym_col(repo_id), self._commit_col(repo_id)]:
            try:
                await self._client.delete_collection(col)
            except Exception:
                pass

    # backwards compat alias used in health router
    async def delete_collection(self, repo_id: str):
        await self.delete_collections(repo_id)


embedder = Embedder()
