"""Grounded answer generation using retrieved context + Groq LLM.

Pipeline:
  user query
    -> retrieve.retrieve(query, k=5)           [top-5 chunks from ChromaDB]
    -> _build_user_prompt()                    [numbered docs with filenames]
    -> Groq chat completion                    [system motto enforces grounding]
    -> structured dict                         [answer + programmatic sources]

The system prompt is the user-specified motto verbatim. The model is told to
cite sources inline using [N] which maps back to the `sources` list in the
return dict, so downstream consumers (the UI, eval scripts) get both the
human-readable answer AND a programmatic source list.

Used both as a callable (`from generate import answer`) and as a CLI
(`python generate.py "your question"`).
"""
from __future__ import annotations

import argparse
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv
from groq import Groq

from retrieve import retrieve

load_dotenv()

# Groq model. llama-3.3-70b-versatile is their flagship instruction-tuned
# model; small enough to be fast on Groq's hardware while strong on
# instruction-following (which we need for the strict grounding behavior).
GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_K = 5
PROCESSED_DIR = Path("processed")

# System prompt: the user-supplied motto is the core directive. The added
# sentence about citing [N] inline is purely structural — it does NOT relax
# the grounding rule, it only tells the model how to attribute facts when
# it has them.
SYSTEM_PROMPT = (
    "You are a helpful assistant answering questions about UCLA student "
    "life based on a curated set of documents (Reddit threads, Daily "
    "Bruin articles, BruinLife, and the r/ucla wiki).\n\n"
    "Answer the question using only the information in the provided "
    "documents. If the documents don't contain enough information to "
    "answer, say \"I don't have enough information on that\".\n\n"
    "Each document is labeled [N] with its source filename. When you use "
    "a fact from a document, cite it inline using [N]. Do not invent "
    "facts, names, prices, or dates that are not in the documents."
)


# ---------------------------------------------------------------------------
# Source-filename lookup (source_id -> original PDF filename)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _filename_map() -> Dict[str, str]:
    """source_id -> original PDF filename, loaded from processed/*.json.

    Built once and cached. Without this, the UI would show slug ids like
    'parking_r_ucla' instead of the real file 'Parking_ _ r_ucla.pdf'.
    """
    fmap: Dict[str, str] = {}
    if not PROCESSED_DIR.exists():
        return fmap
    for p in PROCESSED_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if "source_id" in d and "filename" in d:
                fmap[d["source_id"]] = d["filename"]
        except (json.JSONDecodeError, OSError):
            continue
    return fmap


# ---------------------------------------------------------------------------
# Context formatting
# ---------------------------------------------------------------------------

def _format_sources(hits: List[Dict]) -> List[Dict]:
    """Turn retrieve() hits into structured source blocks.

    Each block has both human-readable fields (filename, author, ref) and
    machine-readable fields (source_id, chunk_id, similarity) so consumers
    can render OR programmatically check provenance.
    """
    fmap = _filename_map()
    blocks: List[Dict] = []
    for i, h in enumerate(hits, 1):
        md = h["metadata"]
        source_id = md["source_id"]
        blocks.append({
            "ref": f"[{i}]",
            "filename": fmap.get(source_id, f"{source_id}.pdf"),
            "source_id": source_id,
            "source_type": md["source_type"],
            "segment_type": md["segment_type"],
            "author": md.get("author") or "",
            "title": md.get("title") or "",
            "raw_text": md["raw_text"],
            "chunk_id": h["chunk_id"],
            "similarity": h["similarity"],
            "distance": h["distance"],
        })
    return blocks


def _build_user_prompt(query: str, blocks: List[Dict]) -> str:
    """Build the user message — numbered docs followed by the question."""
    parts = ["Documents:\n"]
    for b in blocks:
        attribution_bits = [b["segment_type"]]
        if b["author"]:
            attribution_bits.append(f"u/{b['author']}")
        attribution = ", ".join(attribution_bits)
        parts.append(f"{b['ref']} (Source: {b['filename']} — {attribution})")
        parts.append(b["raw_text"])
        parts.append("")
    parts.append(f"Question: {query}")
    parts.append("\nAnswer (cite documents inline with [N]):")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_groq_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise SystemExit(
            "GROQ_API_KEY is not set. Add it to .env or export it before "
            "running."
        )
    return Groq(api_key=api_key)


def answer(query: str, k: int = DEFAULT_K, model: str = GROQ_MODEL) -> Dict:
    """Generate a grounded answer with programmatic source citations.

    Returns:
        {
          "query":   str,                # the original question
          "answer":  str,                # LLM-generated text answer
          "sources": List[Dict],         # one entry per retrieved chunk;
                                         # see _format_sources() for shape
          "model":   str,                # which Groq model produced the answer
        }
    """
    if not query or not query.strip():
        raise ValueError("Empty query.")

    hits = retrieve(query, k=k)
    if not hits:
        return {
            "query": query,
            "answer": "I don't have enough information on that.",
            "sources": [],
            "model": model,
        }

    sources = _format_sources(hits)
    user_prompt = _build_user_prompt(query, sources)

    client = _get_groq_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,  # low — we want grounded, not creative
    )

    return {
        "query": query,
        "answer": response.choices[0].message.content,
        "sources": sources,
        "model": model,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _format_cli(result: Dict) -> str:
    out = []
    out.append(f"Query : {result['query']}")
    out.append("")
    out.append("Answer:")
    out.append(result["answer"])
    out.append("")
    out.append("Sources:")
    for s in result["sources"]:
        attribution = s["segment_type"]
        if s["author"]:
            attribution += f", u/{s['author']}"
        out.append(
            f"  {s['ref']} {s['filename']} ({attribution})"
            f"  — similarity {s['similarity'] * 100:.1f}%"
        )
    out.append(f"\n[model: {result['model']}]")
    return "\n".join(out)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Generate a grounded answer from the UCLA "
                    "unofficial-guide vector store."
    )
    p.add_argument("query", nargs="+", help="Question text")
    p.add_argument("-k", "--top-k", type=int, default=DEFAULT_K,
                   help=f"Number of chunks to retrieve (default: {DEFAULT_K})")
    p.add_argument("-m", "--model", default=GROQ_MODEL,
                   help=f"Groq model name (default: {GROQ_MODEL})")
    args = p.parse_args()

    query = " ".join(args.query)
    result = answer(query, k=args.top_k, model=args.model)
    print(_format_cli(result))


if __name__ == "__main__":
    main()
