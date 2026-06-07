"""Preprocess PDF documents into structured text ready for chunking.

Reads every *.pdf in documents/, classifies it as a Reddit thread or an
article-style document, strips per-source noise (page headers, nav menus,
vote/reply lines, etc.), and emits clean segments preserving natural
boundaries (one OP post + one segment per comment for Reddit; one segment
per paragraph for articles).

Outputs:
  processed/<source_id>.json   -- one file per source, full metadata
  processed/corpus.jsonl       -- one line per segment across all sources
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

import pdfplumber

DOCS_DIR = Path("documents")
OUT_DIR = Path("processed")


# ---------------------------------------------------------------------------
# Source classification
# ---------------------------------------------------------------------------

def classify(filename: str) -> str:
    """Reddit thread PDFs are saved with a trailing '_ r_ucla.pdf' suffix.

    The subreddit wiki page starts with 'r_ucla ' instead, and we route it
    through the article parser because its content is structured prose, not
    a comment thread.
    """
    n = filename.lower()
    if n.endswith("_ r_ucla.pdf") or n.endswith("_r_ucla.pdf"):
        return "reddit"
    return "article"


# ---------------------------------------------------------------------------
# Generic line-level cleanup applied before either parser runs
# ---------------------------------------------------------------------------

PAGE_FOOTER_RE = re.compile(r"^\d+\s+of\s+\d+\s+\d+/\d+/\d+,\s*\d+:\d+\s*[AP]M$")
URL_RE = re.compile(r"https?://\S+")


def extract_raw(path: Path) -> str:
    parts: List[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def strip_generic_noise(text: str) -> List[str]:
    """Drop page footers and URL-only header lines; keep blank lines as
    paragraph separators."""
    out: List[str] = []
    for raw in text.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            out.append("")
            continue
        if PAGE_FOOTER_RE.match(line.strip()):
            continue
        # Reddit/Bruin/BruinLife per-page URL header line
        if URL_RE.search(line) and ("reddit.com" in line or "dailybruin.com" in line
                                    or "bruinlife.com" in line):
            continue
        out.append(line)
    return out


# ---------------------------------------------------------------------------
# Reddit thread parser
# ---------------------------------------------------------------------------

# Examples that must match:
#   "itwontmendyourheart • 5mo ago"
#   "BatManatee MOD • 8y ago• Edited 8y ago"
#   "[deleted]• 5mo ago"
COMMENT_HEADER_RE = re.compile(
    r"^(?P<author>\[deleted\]|[A-Za-z0-9_\-]+)(?:\s+MOD)?\s*•\s*"
    r"\d+\s*(?:y|mo|d|h|min|s)\s*ago"
    r"(?:\s*•\s*Edited[^$]*)?\s*$"
)
SUBREDDIT_HEADER_RE = re.compile(r"^r/ucla\s*•")
VOTE_PAIR_RE = re.compile(r"^-?\d+\s+-?\d+\s*$")          # "10 10"  (post score)
VOTE_REPLY_RE = re.compile(r"^-?\d+\s+Reply(\s+.*)?$")    # "9 Reply"  (comment end)
FLAIR_RE = re.compile(r"^Top \d+% Commenter\s*$")
REDDIT_UI_NOISE = {
    "Join the conversation", "Search Comments", "Reply", "Share",
    "Award", "Report", "Save", "Follow", "More replies",
}


def parse_reddit(lines: List[str], title_fallback: str) -> Dict:
    n = len(lines)
    segments: List[Dict] = []

    # 1. Skip preamble until we find the subreddit header "r/ucla •Xmo ago"
    i = 0
    while i < n and not SUBREDDIT_HEADER_RE.match(lines[i].strip()):
        i += 1
    if i >= n:
        return {"title": title_fallback, "segments": []}
    i += 1

    def next_nonblank() -> str:
        nonlocal i
        while i < n and not lines[i].strip():
            i += 1
        if i >= n:
            return ""
        val = lines[i].strip()
        i += 1
        return val

    op_author = next_nonblank()
    op_title = next_nonblank()

    # 2. Collect post body until the vote-pair line or "Join the conversation"
    body: List[str] = []
    while i < n:
        ln = lines[i].strip()
        if ln == "Join the conversation" or VOTE_PAIR_RE.match(ln):
            break
        if ln:
            body.append(ln)
        i += 1
    op_body = " ".join(body).strip()

    if op_title or op_body:
        segments.append({
            "segment_type": "post",
            "author": op_author,
            "text": (op_title + "\n\n" + op_body).strip(),
        })

    # 3. Advance to the first comment header
    while i < n and not COMMENT_HEADER_RE.match(lines[i].strip()):
        i += 1

    # 4. Walk through comments
    cur_author: str | None = None
    cur_body: List[str] = []

    def flush() -> None:
        nonlocal cur_author, cur_body
        if cur_author and cur_body:
            text = " ".join(cur_body).strip()
            if len(text) >= 20:  # drop empty / one-word comments
                segments.append({
                    "segment_type": "comment",
                    "author": cur_author,
                    "text": text,
                })
        cur_author = None
        cur_body = []

    while i < n:
        ln = lines[i].strip()
        i += 1
        if not ln:
            continue
        m = COMMENT_HEADER_RE.match(ln)
        if m:
            flush()
            cur_author = m.group("author")
            continue
        if VOTE_REPLY_RE.match(ln):
            flush()
            continue
        if cur_author is None:
            continue
        if not cur_body and FLAIR_RE.match(ln):
            continue  # drop "Top 1% Commenter" flair right after the header
        if ln in REDDIT_UI_NOISE:
            continue
        cur_body.append(ln)
    flush()

    return {"title": op_title or title_fallback, "segments": segments}


# ---------------------------------------------------------------------------
# Article / wiki parser
# ---------------------------------------------------------------------------

# Nav-bar tokens that appear on Daily Bruin / BruinLife / wiki layouts.
# We use these to detect navigation lines by token-density, not exact match.
NAV_TOKENS = {
    "ADVERTISE", "DONATE", "SUBMIT", "NEWS", "SPORTS", "ARTS", "OPINION",
    "THE QUAD", "PHOTO", "VIDEO", "ILLUSTRATIONS", "CARTOONS", "GRAPHICS",
    "THE STACK", "PRIME", "ENTERPRISE", "RECENT POSTS", "HOME", "STUDENT LIFE",
    "OUT & ABOUT", "FOOD", "ARTS & ENTERTAINMENT", "CULTURE & LIFESTYLE",
    "MULTIMEDIA", "YEARBOOKS", "STUDIO", "ABOUT", "SUBSCRIBE",
    "FEATURED", "CLASSIFIEDS", "MORE CLASSIFIEDS", "RELATED POSTS",
    "LOS ANGELES", "TRENDING", "POPULAR", "LATEST",
}
WIKI_NAV_TOKENS = {"r/ucla", "Search in r/ucla", "Create", "Joined"}
IN_THE_NEWS_RE = re.compile(r"^IN THE NEWS:", re.IGNORECASE)
IMAGE_CAPTION_RE = re.compile(r"^image (via|courtesy)", re.IGNORECASE)


def _looks_like_nav(line: str) -> bool:
    """Detect site-chrome lines (nav menus, breadcrumbs) by token density."""
    s = line.strip()
    if not s:
        return False
    if IN_THE_NEWS_RE.match(s):
        return True
    if s in NAV_TOKENS or s in WIKI_NAV_TOKENS:
        return True
    upper = s.upper()
    nav_hits = sum(1 for tok in NAV_TOKENS if tok in upper)
    # 3+ nav tokens anywhere = definitely nav
    if nav_hits >= 3:
        return True
    # 1+ nav token in a mostly-uppercase short line = nav
    upper_chars = sum(1 for c in s if c.isupper())
    lower_chars = sum(1 for c in s if c.islower())
    if nav_hits >= 1 and len(s) < 120 and upper_chars > lower_chars * 2:
        return True
    return False


def _keep_main_column(words: List[Dict], page_width: float) -> List[Dict]:
    """Drop words that fall outside the page's dominant content column.

    Histograms word x-starts into 20pt bins, finds the densest bin, and
    expands outward while neighboring bins remain dense (>=15% of the peak).
    Skipped for sparse pages and for cases where the detected column would
    be implausibly narrow.
    """
    if len(words) < 40:
        return words
    bin_width = 20
    bins: Dict[int, int] = {}
    for w in words:
        b = int(w["x0"] // bin_width)
        bins[b] = bins.get(b, 0) + 1
    if not bins:
        return words

    peak_bin = max(bins, key=lambda b: bins[b])
    threshold = bins[peak_bin] * 0.15
    lo = hi = peak_bin
    while bins.get(lo - 1, 0) >= threshold:
        lo -= 1
    while bins.get(hi + 1, 0) >= threshold:
        hi += 1

    x_lo = lo * bin_width - 10
    x_hi = (hi + 1) * bin_width + 10
    if x_hi - x_lo < page_width * 0.25:
        return words  # column too narrow to be plausible; keep everything
    return [w for w in words if w["x0"] >= x_lo and w["x1"] <= x_hi + 50]


def _dedupe_doubled_word(word: str) -> str:
    """Some PDFs render bold text by stamping each glyph twice with a tiny
    offset, so pdfplumber sees 'HHiigghh' instead of 'High'. If every character
    in a word appears as a consecutive pair, collapse it."""
    if len(word) < 4 or len(word) % 2 != 0:
        return word
    if all(word[i] == word[i + 1] for i in range(0, len(word), 2)):
        return "".join(word[i] for i in range(0, len(word), 2))
    return word


def _extract_article_paragraphs(path: Path) -> List[str]:
    """Use pdfplumber word coordinates to reconstruct paragraphs.

    pdfplumber's default `extract_text` emits one '\\n' per visual line, which
    loses paragraph structure. We instead group words into lines by y-position
    *and* horizontal continuity (so multi-column layouts don't bleed sidebars
    into body text), then treat any vertical gap > 1.5x the page's median
    line gap as a paragraph break.
    """
    paragraphs: List[str] = []
    current: List[str] = []

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(extra_attrs=["top", "bottom", "size"])
            if not words:
                continue

            # Collapse doubled-glyph bold rendering.
            for w in words:
                w["text"] = _dedupe_doubled_word(w["text"])

            # Detect the dominant content column on this page and drop words
            # outside it. Multi-column print layouts (Daily Bruin) otherwise
            # interleave sidebar links with body text at the same y-band.
            words = _keep_main_column(words, page.width)

            # Group words into visual lines: same y (±3pt) AND horizontally
            # adjacent (next word starts within 30pt of where prev word ends).
            # The horizontal check splits side-by-side columns into separate
            # "lines" so a sidebar at the same y as the headline doesn't get
            # concatenated into it.
            words.sort(key=lambda w: (w["top"], w["x0"]))
            lines: List[Dict] = []
            for w in words:
                if (lines
                        and abs(w["top"] - lines[-1]["top"]) < 3
                        and w["x0"] - lines[-1]["last_x1"] < 30):
                    lines[-1]["text"] += " " + w["text"]
                    lines[-1]["bottom"] = max(lines[-1]["bottom"], w["bottom"])
                    lines[-1]["last_x1"] = w["x1"]
                else:
                    lines.append({
                        "top": w["top"],
                        "bottom": w["bottom"],
                        "text": w["text"],
                        "last_x1": w["x1"],
                    })

            # Median inter-line gap = baseline line spacing for this page.
            gaps = [lines[i]["top"] - lines[i - 1]["bottom"]
                    for i in range(1, len(lines))]
            gaps_sorted = sorted(g for g in gaps if g >= 0)
            median_gap = (gaps_sorted[len(gaps_sorted) // 2]
                          if gaps_sorted else 0)
            para_threshold = median_gap * 1.5 + 2

            for i, line in enumerate(lines):
                text = line["text"].strip()
                if not text:
                    continue
                if PAGE_FOOTER_RE.match(text):
                    continue
                if URL_RE.search(text) and any(d in text for d in
                        ("reddit.com", "dailybruin.com", "bruinlife.com")):
                    continue
                if _looks_like_nav(text):
                    continue
                if IMAGE_CAPTION_RE.match(text):
                    continue

                gap = (line["top"] - lines[i - 1]["bottom"]) if i > 0 else 999
                if gap > para_threshold and current:
                    _flush_paragraph(current, paragraphs)
                    current = []
                current.append(text)

            # Page break also flushes the current paragraph.
            if current:
                _flush_paragraph(current, paragraphs)
                current = []

    return paragraphs


def _flush_paragraph(buf: List[str], out: List[str]) -> None:
    para = re.sub(r"\s+", " ", " ".join(buf)).strip()
    if len(para) >= 40:
        out.append(para)


def parse_article(path: Path, title_fallback: str) -> Dict:
    paragraphs = _extract_article_paragraphs(path)
    title = paragraphs[0] if paragraphs else title_fallback
    segments = [{"segment_type": "paragraph", "text": p} for p in paragraphs]
    return {"title": title, "segments": segments}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    n = re.sub(r"\.pdf$", "", name, flags=re.IGNORECASE)
    n = re.sub(r"[^A-Za-z0-9]+", "_", n).strip("_").lower()
    return n[:80]


def process_one(path: Path) -> Dict:
    source_type = classify(path.name)
    if source_type == "reddit":
        lines = strip_generic_noise(extract_raw(path))
        parsed = parse_reddit(lines, title_fallback=path.stem)
    else:
        # Articles use coordinate-aware paragraph extraction directly.
        parsed = parse_article(path, title_fallback=path.stem)
    return {
        "source_id": slugify(path.name),
        "source_type": source_type,
        "title": parsed["title"],
        "filename": path.name,
        "segment_count": len(parsed["segments"]),
        "segments": parsed["segments"],
    }


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    pdfs = sorted(DOCS_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {DOCS_DIR}/")
        return

    corpus_path = OUT_DIR / "corpus.jsonl"
    summary: List[tuple] = []
    with corpus_path.open("w", encoding="utf-8") as cf:
        for pdf in pdfs:
            print(f"  processing {pdf.name}")
            rec = process_one(pdf)
            (OUT_DIR / f"{rec['source_id']}.json").write_text(
                json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            for idx, seg in enumerate(rec["segments"]):
                cf.write(json.dumps({
                    "source_id": rec["source_id"],
                    "source_type": rec["source_type"],
                    "title": rec["title"],
                    "segment_index": idx,
                    **seg,
                }, ensure_ascii=False) + "\n")
            summary.append((rec["source_id"], rec["source_type"], rec["segment_count"]))

    print("\n=== summary ===")
    total = 0
    for sid, stype, n in summary:
        print(f"  [{stype:7s}] {n:4d} segments  {sid}")
        total += n
    print(f"\n  {len(summary)} sources, {total} total segments")
    print(f"  -> {corpus_path}")


if __name__ == "__main__":
    main()
