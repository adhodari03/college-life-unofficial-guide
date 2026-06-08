"""Retrieve top-k relevant chunks for a query.

Loads the ChromaDB collection built by embed.py, embeds the incoming query
with the SAME sentence-transformer model and normalization, and returns the
top-k chunks ranked by cosine similarity.

Two use modes:

  - As a library:  `from retrieve import retrieve; hits = retrieve(q, k=5)`
                   (used by milestone 5's UI)
  - As a CLI:      `python retrieve.py "where can I park near UCLA?" -k 5`

Critical invariants enforced here:

  1. The query embedding uses the same EMBEDDING_MODEL as embed.py — both
     are imported from embed.py so a typo can only break one place.
  2. The query is normalized identically (`normalize_embeddings=True`).
  3. Chroma returns "distance"; we convert to "similarity = 1 - distance"
     before exposing scores, so larger values consistently mean "better
     match" (the natural reading).
"""
from __future__ import annotations

import argparse
import sys
from functools import lru_cache
from typing import Dict, List

import chromadb
from sentence_transformers import SentenceTransformer

# Single source of truth: pull model + collection details from embed.py so
# the two scripts can never drift.
from embed import CHROMA_DIR, COLLECTION_NAME, EMBEDDING_MODEL

DEFAULT_K = 5


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """Model load is ~3s on first call; cached for reuse across queries."""
    return SentenceTransformer(EMBEDDING_MODEL)


@lru_cache(maxsize=1)
def _get_collection():
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        return client.get_collection(COLLECTION_NAME)
    except Exception as e:
        raise SystemExit(
            f"Collection '{COLLECTION_NAME}' not found at {CHROMA_DIR}/. "
            f"Run embed.py first. (underlying: {e})"
        )


def retrieve(query: str, k: int = DEFAULT_K) -> List[Dict]:
    """Return the top-k chunks most relevant to `query`, ranked by similarity.

    Each result dict contains:
      rank        : 1-based rank
      chunk_id    : the chunk's ID
      similarity  : cosine similarity in [0, 1] (higher = better)
      distance    : raw cosine distance from Chroma (lower = better)
      document    : the embedded text (body + source prefix)
      metadata    : all chunk metadata, including `raw_text` for display
    """
    if not query or not query.strip():
        raise ValueError("Empty query.")

    model = _get_model()
    collection = _get_collection()

    # IMPORTANT: normalize the query embedding exactly like the doc embeddings
    # in embed.py. Mismatched normalization silently corrupts ranking.
    q_vec = model.encode(
        [query],
        normalize_embeddings=True,
        convert_to_numpy=True,
    )[0].tolist()

    raw = collection.query(
        query_embeddings=[q_vec],
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )

    # Chroma returns {"ids": [[...]], ...} — the outer list is one row per
    # input query. We only ever send one query, so always index with [0].
    n = len(raw["ids"][0])
    results: List[Dict] = []
    for i in range(n):
        distance = float(raw["distances"][0][i])
        results.append({
            "rank": i + 1,
            "chunk_id": raw["ids"][0][i],
            "similarity": 1.0 - distance,  # cosine: distance = 1 - similarity
            "distance": distance,
            "document": raw["documents"][0][i],
            "metadata": raw["metadatas"][0][i],
        })
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _format_result(r: Dict, snippet_chars: int = 260) -> str:
    md = r["metadata"]
    sim_pct = r["similarity"] * 100
    author = f" / u/{md['author']}" if md["author"] else ""
    body = md["raw_text"]
    if len(body) > snippet_chars:
        body = body[:snippet_chars].rstrip() + "..."
    return (
        f"#{r['rank']}  similarity={sim_pct:5.1f}%  "
        f"[{md['source_type']}/{md['segment_type']}{author}]\n"
        f"   source : {md['source_id']}\n"
        f"   id     : {r['chunk_id']}\n"
        f"   text   : {body}"
    )


def main() -> None:
    p = argparse.ArgumentParser(
        description="Retrieve top-k chunks from the UCLA unofficial-guide "
                    "vector store."
    )
    p.add_argument("query", nargs="+",
                   help="Query text (quotes optional; multiple words OK)")
    p.add_argument("-k", "--top-k", type=int, default=DEFAULT_K,
                   help=f"How many chunks to return (default: {DEFAULT_K})")
    args = p.parse_args()

    query = " ".join(args.query)
    print(f"Query : {query!r}")
    print(f"Top-{args.top_k} results:\n")

    results = retrieve(query, k=args.top_k)
    for r in results:
        print(_format_result(r))
        print()


if __name__ == "__main__":
    main()
