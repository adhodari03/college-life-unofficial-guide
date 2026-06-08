"""Embed cleaned chunks and persist them to a ChromaDB collection.

Reads chunks/chunks.jsonl, embeds each chunk's `text` field (body + source
prefix) with sentence-transformers/all-MiniLM-L6-v2, and upserts everything
into a persistent ChromaDB collection on disk at ./chroma/.

Design choices (documented here because errors at this stage propagate
silently into every downstream query):

  - Model            : all-MiniLM-L6-v2, 384-dim, CPU-friendly.
  - Normalization    : `normalize_embeddings=True`. SentenceTransformer's
                       raw output is NOT unit-norm; without this, cosine
                       distance in Chroma reduces to the wrong thing.
  - Distance metric  : cosine, set explicitly on the collection via
                       `metadata={"hnsw:space": "cosine"}`. Chroma defaults
                       to L2 — wrong choice for normalized sentence
                       embeddings.
  - What's embedded  : the `text` field (body + "[source — author]" prefix)
                       so retrieval picks up topical context, especially
                       useful for short Reddit comments.
  - What's stored as
    metadata         : everything from chunks.jsonl, including `raw_text`
                       (body without prefix) for clean display in the
                       eventual UI.
  - Re-run behavior  : the existing collection is deleted and rebuilt from
                       scratch. At 334 chunks this is ~20s on CPU and
                       guarantees we never serve stale vectors during
                       iteration.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import chromadb
from sentence_transformers import SentenceTransformer

CHUNKS_PATH = Path("chunks/chunks.jsonl")
CHROMA_DIR = Path("chroma")
COLLECTION_NAME = "ucla_unofficial_guide"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
BATCH_SIZE = 64


def load_chunks(path: Path) -> List[Dict]:
    if not path.exists():
        raise SystemExit(f"{path} not found — run chunk.py first.")
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_metadata(c: Dict) -> Dict:
    """Build the per-chunk metadata dict.

    ChromaDB rejects None values and non-scalar types — every field here
    must be str/int/float/bool. We coerce defensively because a single
    bad metadata row will silently drop a chunk from the index.
    """
    return {
        "source_id": str(c["source_id"]),
        "source_type": str(c["source_type"]),
        "title": (c.get("title") or "")[:200],
        "segment_index": int(c["segment_index"]),
        "segment_type": str(c["segment_type"]),
        "chunk_index_in_segment": int(c["chunk_index_in_segment"]),
        "author": str(c.get("author") or ""),
        "char_count": int(c["char_count"]),
        "raw_text": str(c["raw_text"]),  # for display, not for embedding
    }


def main() -> None:
    chunks = load_chunks(CHUNKS_PATH)
    print(f"Loaded {len(chunks)} chunks from {CHUNKS_PATH}\n")

    print(f"Loading embedding model: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL)
    dim = model.get_sentence_embedding_dimension()
    print(f"  -> {dim}-dim vectors\n")

    CHROMA_DIR.mkdir(exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # Idempotent rebuild: drop the old collection if it exists.
    existing = [c.name for c in client.list_collections()]
    if COLLECTION_NAME in existing:
        client.delete_collection(COLLECTION_NAME)
        print(f"Dropped existing collection '{COLLECTION_NAME}'")

    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    print(f"Created collection '{COLLECTION_NAME}' (cosine space)\n")

    # Encode all chunks at once — MiniLM handles 334 chunks comfortably.
    texts = [c["text"] for c in chunks]
    print(f"Encoding {len(texts)} chunks (batch={BATCH_SIZE}, normalized)...")
    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    print(f"  -> embeddings shape: {embeddings.shape}\n")

    metadatas = [build_metadata(c) for c in chunks]
    ids = [c["chunk_id"] for c in chunks]

    # Sanity: chunk_ids must be unique — collision would silently overwrite.
    if len(set(ids)) != len(ids):
        raise SystemExit("Duplicate chunk_ids found — abort before indexing.")

    print(f"Indexing into ChromaDB...")
    collection.add(
        ids=ids,
        embeddings=embeddings.tolist(),
        documents=texts,
        metadatas=metadatas,
    )

    final_count = collection.count()
    print(f"\nDone. Collection size: {final_count} vectors")
    print(f"Persisted at: {CHROMA_DIR.resolve()}")

    if final_count != len(chunks):
        print(f"\nWARNING: expected {len(chunks)} vectors, got {final_count}. "
              "Some chunks may have been silently rejected.")


if __name__ == "__main__":
    main()
