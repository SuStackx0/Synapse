# Vector Search: Theory and Implementation

## From Text to Numbers

Machine learning models operate on numbers, not text. An embedding model maps text to a high-dimensional vector — a list of floats. Similar texts get vectors that are close together in this space.

`all-MiniLM-L6-v2` produces 384-dimensional vectors. Each dimension captures some latent semantic feature of the text. No individual dimension is interpretable; the meaning is in the relationships between vectors.

Example:
```python
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("all-MiniLM-L6-v2")

vectors = model.encode([
    "def authenticate_user(token):",
    "JWT validation and token decoding",
    "def calculate_shipping_cost(weight):",
])
# vectors[0] and vectors[1] will have high cosine similarity
# vectors[2] will be far from both
```

## Cosine Similarity

Given two vectors A and B:

```
cosine_similarity(A, B) = (A · B) / (||A|| × ||B||)
```

This measures the angle between vectors, ignoring magnitude. Range: [-1, 1].

- **1.0**: identical direction (same semantic meaning)
- **0.0**: orthogonal (unrelated)
- **-1.0**: opposite direction (antonyms, in theory)

Code chunks typically cluster in the 0.5–0.95 range for related content.

## Why Qdrant?

Qdrant is a purpose-built vector database implemented in Rust. Key properties:

- **HNSW index** (Hierarchical Navigable Small World): approximate nearest-neighbor search in O(log N) — fast even with millions of vectors
- **Payload filtering**: filter by metadata (repo_id, language, file_path) before or after the vector search
- **Async Python client**: compatible with FastAPI's async model
- **Persistence**: vectors survive container restarts via Docker volume mounts
- **Collection isolation**: each repo gets its own Qdrant collection, so searches are scoped automatically

### HNSW vs. Brute Force

Brute force search is O(N × D) where N = number of vectors and D = dimensions. At 100K chunks and 384 dimensions, that's 38.4M multiplications per query.

HNSW builds a multi-layer graph of connections between vectors. At query time it starts from the top layer (few nodes, long-range connections) and descends to the bottom layer (all nodes, short-range connections), following the closest connections at each step. Search is O(log N) with ~95–99% recall. The recall-speed tradeoff is configurable via `ef` (beam width during search).

## Indexing Pipeline

```python
# Simplified from embedder.py
chunks = []
for file in parsed_files:
    content = file["content"]
    for i in range(0, len(content), 500):
        chunks.append({
            "id": str(uuid.uuid4()),
            "text": content[i:i+500],
            "payload": {
                "repo_id": repo_id,
                "file_path": file["rel_path"],
                "chunk_start": i,
            }
        })

# Batch encode (faster than one-by-one)
vectors = model.encode([c["text"] for c in chunks])  # shape: (N, 384)

# Upsert in batches of 64 to avoid memory spikes
await qdrant.upsert(collection, points=[
    PointStruct(id=c["id"], vector=v, payload=c["payload"])
    for c, v in zip(chunks, vectors)
])
```

## Query-Time Retrieval

```python
query_vector = model.encode(["How does auth work?"])[0]  # (384,)
results = await qdrant.search(
    collection_name,
    query_vector=query_vector,
    limit=8,               # top-8 chunks
    with_payload=True,     # return file path and text
)
# Each result: score (cosine similarity) + payload (file, text)
```

The top-8 chunks are concatenated and injected into the LLM's system prompt. Total context: ~4K tokens, well within any modern model's window.

## Tradeoffs and Known Limitations

| Limitation | Impact | Better Approach |
|---|---|---|
| Fixed 500-char chunks | Splits functions mid-definition | AST-aware chunking at function boundaries |
| No chunk overlap | Context lost at boundaries | 100-char overlap windows |
| General embedding model | Mediocre code retrieval | `nomic-embed-code` or `voyage-code-3` |
| Single-stage retrieval | No re-ranking | HyDE (hypothetical document embeddings) + cross-encoder rerank |

These are all well-understood and implementable given more development time.
