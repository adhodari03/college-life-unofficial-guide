"""Validate chunks before embedding.

Bad chunks can't be fixed by tuning retrieval later, so this script does a
two-part check:

  1. Diagnostics across all chunks: empties, HTML residue, suspiciously
     uniform sizes, broken metadata.
  2. Prints N random chunks for human inspection — read them and confirm
     they're substantive and self-contained.
"""
from __future__ import annotations

import json
import random
import re
import statistics
import sys
from pathlib import Path
from typing import Dict, List

CHUNKS_PATH = Path("chunks/chunks.jsonl")
SAMPLE_SIZE = 5
MIN_BODY_CHARS = 20   # below this is "suspiciously short / empty"
                      # (real one-line Reddit comments can be ~20-30c)

# Common HTML residue patterns
HTML_TAG_RE = re.compile(r"<[a-zA-Z/!][^>]{0,200}>")
HTML_ENTITY_RE = re.compile(r"&(?:[a-zA-Z]{2,8}|#\d{2,5});")
HTML_ATTR_RE = re.compile(r'\b(?:class|href|src|data-\w+)\s*=\s*"[^"]{0,80}"')

REQUIRED_FIELDS = ["chunk_id", "source_id", "source_type", "title",
                   "segment_index", "segment_type", "text", "raw_text",
                   "char_count"]


def load_chunks(path: Path) -> List[Dict]:
    if not path.exists():
        sys.exit(f"ERROR: {path} not found — run chunk.py first.")
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------------------
# Diagnostic checks
# ---------------------------------------------------------------------------

def check_empties(chunks: List[Dict]) -> Dict:
    bad = [c for c in chunks if len(c.get("raw_text", "").strip()) < MIN_BODY_CHARS]
    return {
        "name": f"Empty / sub-{MIN_BODY_CHARS}-char chunks",
        "pass": not bad,
        "detail": f"{len(bad)} chunks below threshold",
        "examples": [c["chunk_id"] for c in bad[:3]],
    }


def check_html(chunks: List[Dict]) -> Dict:
    bad = []
    for c in chunks:
        text = c.get("raw_text", "")
        if (HTML_TAG_RE.search(text)
                or HTML_ENTITY_RE.search(text)
                or HTML_ATTR_RE.search(text)):
            bad.append(c)
    return {
        "name": "HTML tags / entities / attributes",
        "pass": not bad,
        "detail": f"{len(bad)} chunks contain HTML residue",
        "examples": [c["chunk_id"] for c in bad[:3]],
    }


def check_length_variety(chunks: List[Dict]) -> Dict:
    lengths = [c["char_count"] for c in chunks]
    mean = statistics.mean(lengths)
    stdev = statistics.stdev(lengths) if len(lengths) > 1 else 0
    cv = stdev / mean if mean else 0
    # CV < 0.1 = suspiciously uniform (mechanical fixed-size cut)
    # CV > 0.25 = healthy variation
    ok = cv >= 0.15
    return {
        "name": "Length variety (coefficient of variation)",
        "pass": ok,
        "detail": (f"mean={mean:.0f}c, stdev={stdev:.0f}c, cv={cv:.2f} "
                   f"(want >=0.15; <0.1 means mechanical splitting)"),
        "examples": [],
    }


def check_metadata(chunks: List[Dict]) -> Dict:
    bad = []
    for c in chunks:
        for f in REQUIRED_FIELDS:
            if f not in c or c[f] in (None, ""):
                bad.append((c.get("chunk_id", "?"), f))
                break
    # Also: chunk_id should encode source_id
    mismatched = [c["chunk_id"] for c in chunks
                  if not c["chunk_id"].startswith(c["source_id"])]
    return {
        "name": "Metadata completeness + source_id consistency",
        "pass": not bad and not mismatched,
        "detail": (f"{len(bad)} chunks missing required fields; "
                   f"{len(mismatched)} chunk_ids don't match their source_id"),
        "examples": [b[0] + f" (missing {b[1]})" for b in bad[:3]]
                    + mismatched[:3],
    }


# ---------------------------------------------------------------------------
# Pretty print
# ---------------------------------------------------------------------------

def print_diagnostic(d: Dict) -> None:
    tag = "PASS" if d["pass"] else "FAIL"
    print(f"  [{tag}] {d['name']}")
    print(f"         {d['detail']}")
    if d["examples"]:
        for ex in d["examples"]:
            print(f"         e.g. {ex}")


def print_sample(idx: int, total: int, c: Dict) -> None:
    bar = "=" * 72
    author = f" / u/{c['author']}" if c.get("author") else ""
    print(bar)
    print(f"[{idx}/{total}] {c['chunk_id']}")
    print(f"        source : {c['source_id']}")
    print(f"        type   : {c['source_type']} / {c['segment_type']}{author}")
    print(f"        length : {c['char_count']} chars")
    print(bar)
    print(c["text"])
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(n: int = SAMPLE_SIZE, seed: int | None = None) -> None:
    chunks = load_chunks(CHUNKS_PATH)
    print(f"Loaded {len(chunks)} chunks from {CHUNKS_PATH}\n")

    print("--- DIAGNOSTICS ---")
    diagnostics = [
        check_empties(chunks),
        check_html(chunks),
        check_length_variety(chunks),
        check_metadata(chunks),
    ]
    for d in diagnostics:
        print_diagnostic(d)
    fails = [d for d in diagnostics if not d["pass"]]
    if fails:
        print(f"\n  {len(fails)} check(s) FAILED — debug before embedding.")
    else:
        print("\n  All checks passed.")

    print(f"\n--- {n} RANDOM SAMPLES ---\n")
    if seed is not None:
        random.seed(seed)
    sample = random.sample(chunks, min(n, len(chunks)))
    for i, c in enumerate(sample, 1):
        print_sample(i, n, c)


if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(seed=seed)
