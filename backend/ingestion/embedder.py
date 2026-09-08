from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter,
    FieldCondition, MatchValue, SearchRequest
)
from sentence_transformers import SentenceTransformer
from core.config import settings
from typing import List, Dict, Any
import uuid
import structlog

logger = structlog.get_logger()

COLLECTION_PREFIX = "synapse_repo_"
VECTOR_SIZE = 384  # all-MiniLM-L6-v2


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

    def _collection(self, repo_id: str) -> str:
        return f"{COLLECTION_PREFIX}{repo_id.replace('-', '_')}"

    async def _ensure_collection(self, repo_id: str):
        col = self._collection(repo_id)
        exists = await self._client.collection_exists(col)
        if not exists:
            await self._client.create_collection(
                col,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )

    def _embed(self, texts: List[str]) -> List[List[float]]:
        return self._model.encode(texts, convert_to_numpy=True).tolist()

    async def index_files(self, repo_id: str, parsed_files: List[Dict[str, Any]]):
        await self._ensure_collection(repo_id)
        col = self._collection(repo_id)

        chunks = []
        for f in parsed_files:
            content = f.get("content", "")
            if not content.strip():
                continue
            # Chunk by ~500 chars
            for i in range(0, len(content), 500):
                chunk = content[i:i + 500]
                chunks.append({
                    "id": str(uuid.uuid4()),
                    "text": chunk,
                    "payload": {
                        "repo_id": repo_id,
                        "file_path": f.get("rel_path", f.get("path", "")),
                        "language": f.get("language", "unknown"),
                        "chunk_start": i,
                    },
                })

        if not chunks:
            return

        batch_size = 64
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            texts = [c["text"] for c in batch]
            vectors = self._embed(texts)
            points = [
                PointStruct(id=c["id"], vector=v, payload=c["payload"])
                for c, v in zip(batch, vectors)
            ]
            await self._client.upsert(col, points=points)

        logger.info("indexed", repo_id=repo_id, chunks=len(chunks))

    async def search(self, repo_id: str, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        await self._ensure_collection(repo_id)
        col = self._collection(repo_id)
        vector = self._embed([query])[0]
        results = await self._client.search(
            col, query_vector=vector, limit=limit,
            with_payload=True,
        )
        return [
            {"score": r.score, "file": r.payload.get("file_path"), "text": r.payload.get("text", "")}
            for r in results
        ]

    async def delete_collection(self, repo_id: str):
        col = self._collection(repo_id)
        try:
            await self._client.delete_collection(col)
        except Exception:
            pass


embedder = Embedder()
