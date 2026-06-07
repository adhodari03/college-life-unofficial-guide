"""Chunk preprocessed segments into retrieval-ready text chunks.

Reads processed/corpus.jsonl (one cleaned segment per line) and emits
chunks/chunks.jsonl (one chunk per line, with source metadata).

Strategy (Option A from planning.md):
  - Target chunk size : 600 chars (~150 tokens)
  - Overlap           : 80 chars  (~20 tokens), snapped to word boundary
  - Splitter          : recursive character splitter with separator priority
                        ["\\n\\n", "\\n", ". ", " ", ""]
                        — prefers paragraph, then sentence, then word, then char
  - Segment boundary  : NEVER cross it. A short Reddit comment becomes one
                        chunk; a long one becomes several; but two comments
                        never merge into one chunk.
  - Metadata prefix   : each chunk text is prefixed with a short header
                        ("[r/ucla thread \"Parking?\" — u/itwontmendyourheart]")
                        so the embedding model picks up source context.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

CORPUS_PATH = Path("processed/corpus.jsonl")
OUT_DIR = Path("chunks")
OUT_PATH = OUT_DIR / "chunks.jsonl"

CHUNK_SIZE = 600
CHUNK_OVERLAP = 80
SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


# ---------------------------------------------------------------------------
# Core splitter
# ---------------------------------------------------------------------------

def _recursive_split(text: str, size: int, separators: List[str]) -> List[str]:
    """Split text into pieces of <= `size` chars.

    Walks the separator list in priority order: tries `\\n\\n` first
    (paragraph breaks), falls back to `\\n`, then `. ` (sentence boundary),
    then ` ` (word boundary), and finally a hard character cut. Pieces are
    re-merged greedily into target-sized chunks afterward.
    """
    if len(text) <= size:
        return [text] if text else []

    for i, sep in enumerate(separators):
        if sep == "":
            # Last resort: split mid-word every `size` chars.
            return [text[j:j + size] for j in range(0, len(text), size)]
        if sep in text:
            raw_pieces = text.split(sep)
            # Any piece still too long → recurse with the next-weaker separator
            split_pieces: List[str] = []
            for p in raw_pieces:
                if not p:
                    continue
                if len(p) <= size:
                    split_pieces.append(p)
                else:
                    split_pieces.extend(
                        _recursive_split(p, size, separators[i + 1:])
                    )
            return _greedy_merge(split_pieces, sep, size)
    return [text]


def _greedy_merge(pieces: List[str], sep: str, size: int) -> List[str]:
    """Merge consecutive small pieces back together up to `size` using `sep`."""
    out: List[str] = []
    cur = ""
    for p in pieces:
        candidate = (cur + sep + p) if cur else p
        if len(candidate) <= size:
            cur = candidate
        else:
            if cur:
                out.append(cur)
            cur = p
    if cur:
        out.append(cur)
    return out


def _add_overlap(chunks: List[str], overlap: int) -> List[str]:
    """Prepend a snippet of each chunk's tail to the next one.

    Overlap is taken from the ORIGINAL previous chunk (not the
    already-overlapped one) so overlaps don't compound across chunks.
    The cut is snapped to a word boundary when possible.
    """
    if len(chunks) <= 1 or overlap <= 0:
        return chunks
    out = [chunks[0]]
    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        tail = prev[-overlap:]
        # Snap forward to the next space so we don't start mid-word.
        first_space = tail.find(" ")
        if 0 < first_space < overlap // 2:
            tail = tail[first_space + 1:]
        glue = "" if tail.endswith(" ") or chunks[i].startswith(" ") else " "
        out.append(tail + glue + chunks[i])
    return out


# ---------------------------------------------------------------------------
# Per-segment chunking
# ---------------------------------------------------------------------------

def _build_prefix(seg: Dict) -> str:
    """Compact metadata header prepended to every chunk."""
    title = (seg.get("title") or "").strip()
    if len(title) > 90:
        title = title[:87] + "..."
    if seg["source_type"] == "reddit":
        author = seg.get("author") or "anon"
        role = "OP " if seg["segment_type"] == "post" else ""
        return f'[r/ucla thread "{title}" — {role}u/{author}]'
    return f"[{title}]"


def chunk_segment(seg: Dict) -> List[Dict]:
    """Turn one segment into one or more chunks with prefixed text.

    Segments are atomic: the splitter only operates *inside* a segment, so
    two Reddit comments never end up in the same chunk.
    """
    text = seg["text"].strip()
    if not text:
        return []

    prefix = _build_prefix(seg)
    # Reserve room for the prefix + a newline. Fall back to a minimum body
    # size if the prefix itself is unusually long.
    effective_size = max(200, CHUNK_SIZE - len(prefix) - 1)

    body_pieces = _recursive_split(text, effective_size, SEPARATORS)
    body_pieces = _add_overlap(body_pieces, CHUNK_OVERLAP)

    chunks: List[Dict] = []
    for idx, piece in enumerate(body_pieces):
        full = f"{prefix}\n{piece}"
        chunks.append({
            "chunk_id": (f"{seg['source_id']}"
                         f"__seg{seg['segment_index']:03d}"
                         f"__c{idx:02d}"),
            "source_id": seg["source_id"],
            "source_type": seg["source_type"],
            "title": seg["title"],
            "segment_index": seg["segment_index"],
            "segment_type": seg["segment_type"],
            "chunk_index_in_segment": idx,
            "author": seg.get("author"),
            "text": full,           # what gets embedded
            "raw_text": piece,      # body only, no prefix
            "char_count": len(full),
        })
    return chunks


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> None:
    if not CORPUS_PATH.exists():
        raise SystemExit(
            f"{CORPUS_PATH} not found — run preprocess.py first."
        )

    OUT_DIR.mkdir(exist_ok=True)
    per_source: Dict[str, int] = {}
    sizes: List[int] = []
    total = 0

    with CORPUS_PATH.open(encoding="utf-8") as fin, \
         OUT_PATH.open("w", encoding="utf-8") as fout:
        for line in fin:
            seg = json.loads(line)
            for c in chunk_segment(seg):
                fout.write(json.dumps(c, ensure_ascii=False) + "\n")
                per_source[c["source_id"]] = per_source.get(c["source_id"], 0) + 1
                sizes.append(c["char_count"])
                total += 1

    sizes.sort()
    print(f"Wrote {total} chunks -> {OUT_PATH}\n")
    print("=== chunks per source ===")
    for sid in sorted(per_source):
        print(f"  {per_source[sid]:4d}  {sid}")
    if sizes:
        print("\n=== chunk-size stats (chars) ===")
        print(f"  count : {len(sizes)}")
        print(f"  min   : {sizes[0]}")
        print(f"  p50   : {sizes[len(sizes) // 2]}")
        print(f"  p95   : {sizes[int(len(sizes) * 0.95)]}")
        print(f"  max   : {sizes[-1]}")
        print(f"  mean  : {sum(sizes) // len(sizes)}")
        oversized = sum(1 for s in sizes if s > CHUNK_SIZE + CHUNK_OVERLAP + 20)
        if oversized:
            print(f"  >{CHUNK_SIZE + CHUNK_OVERLAP + 20}: {oversized} chunks")


if __name__ == "__main__":
    main()
