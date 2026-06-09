# The Unofficial Guide — Project 1

> **How to use this template:**
> Complete each section *after* you've built and tested the corresponding part of your system.
> Do not write placeholder text — if a section isn't done yet, leave it blank and come back.
> Every section below is required for submission. One-liners will not receive full credit.

---

## Domain

<!-- What topic or category of knowledge does your system cover?
     Why is this knowledge valuable, and why is it hard to find through official channels?
     Example: "Student reviews of CS professors at [university] — useful because official
     course descriptions don't reflect teaching style, exam difficulty, or workload." -->

UCLA student life from unofficial sources — specifically parking, off-campus housing, dining options, and general advice for new students. This knowledge is valuable because official UCLA channels (Housing, Transportation, dining services) publish policies, prices, and procedures, but they do not publish the lived experience: which lots actually have spots on a Tuesday morning, which off-campus buildings have bug problems, which dining halls have the best food on which days, or what current students wish they had known at freshman orientation. Reddit threads, Daily Bruin reporting, and the r/ucla wiki capture that operational knowledge in a way the official sites can't, because the official sites have legal and PR obligations that prevent them from being candid about trade-offs.

---

## Document Sources

<!-- List every source you collected documents from.
     Be specific: include URLs, subreddit names, forum thread titles, or file names.
     Aim for variety — sources that together cover different subtopics or perspectives. -->

| # | Source | Type | URL or file path |
|---|--------|------|-----------------|
| 1 | r/ucla — Off Campus Apartments | Reddit thread | https://www.reddit.com/r/ucla/comments/1b16h81/off_campus_apartments/ |
| 2 | r/ucla — Parking? | Reddit thread | https://www.reddit.com/r/ucla/comments/1q49rn6/parking/ |
| 3 | r/ucla Wiki — Parking | Subreddit wiki page | https://www.reddit.com/r/ucla/wiki/parking/ |
| 4 | r/ucla — Please walk me through parking permits | Reddit thread | https://www.reddit.com/r/ucla/comments/1mhrjit/please_walk_me_through_parking_permits/ |
| 5 | The Stack — On-campus vs off-campus living | Daily Bruin data journalism | https://stack.dailybruin.com/2022/11/30/campus-living/ |
| 6 | Daily Bruin — Westwood Apartment Hunting | News article | https://dailybruin.com/2026/03/07/high-demand-fast-pace-inside-the-westwood-apartment-hunting-process |
| 7 | r/ucla — The Redditor's Guide to UCLA 2016 | Reddit thread (community guide) | https://www.reddit.com/r/ucla/comments/9itxyf/ (linked from #10) |
| 8 | r/ucla — The Redditors' Unofficial Guide to UCLA 2018 | Reddit thread (community guide) | https://www.reddit.com/r/ucla/comments/9itxyf/the_redditors_unofficial_guide_to_ucla_2018/ |
| 9 | r/ucla — Favorite and least favorite part about UCLA | Reddit thread | r/ucla discussion thread |
| 10 | BruinLife — Where to eat at UCLA | Student magazine article | https://bruinlife.com/where-to-eat-at-ucla-meal-plans-dining-halls-and-campus-spots/ |

All ten sources were saved as PDFs in `documents/` and processed by `preprocess.py`. Source types split as 7 Reddit (threads + wiki) + 3 article (Daily Bruin, The Stack, BruinLife), giving the corpus a mix of conversational community knowledge and journalistic / structured reporting.

---

## Chunking Strategy

<!-- Describe your chunking approach with enough specificity that someone else could reproduce it.
     Include:
     - Chunk size (characters or tokens) and why that size fits your documents
     - Overlap size and why (or why not) you used overlap
     - Any preprocessing you did before chunking (e.g., stripping HTML, removing headers)
     - What your final chunk count was across all documents -->

**Chunk size:** 600 characters as a ceiling, with a recursive character splitter that tries separator priority `["\n\n", "\n", ". ", " ", ""]`. This is the maximum size — most chunks are smaller because the splitter never crosses what I call a "segment boundary" (one Reddit comment, one article paragraph, one wiki section). Final p50 is 303 characters and mean is 351 characters — well below the ceiling because most short Reddit comments become a single sub-600 chunk on their own. The 600 ceiling exists so that no chunk exceeds the embedding model's 256-token context window.

**Overlap:** 80 characters between chunks that came from the *same segment* (i.e., a long article paragraph or a 9-paragraph Reddit comment that had to be split). Overlap is snapped to the next word boundary so it never starts mid-word. There is **no overlap between separate segments** — two adjacent Reddit comments are never glued together with overlap text, because they're two different authors making two different points.

**Why these choices fit your documents:** my corpus is heterogeneous — Reddit comments range from 25 characters ("Try UclaOffCampusHousing.com!") to 9,000 characters (one user's full pros-and-cons writeup of off-campus living). A single fixed chunk size is wrong for both ends of that range. By making the segment (comment, paragraph) the atomic unit instead of a character count, the chunker produces short focused chunks for terse comments and multiple coherent chunks for long ones, without me having to tune a number that's wrong for at least one source type. The 80-character overlap exists only to repair sentence breaks that the size ceiling forces inside a long segment.

**Preprocessing before chunking:** every PDF was processed by `preprocess.py` with per-source-type cleaners. Reddit thread PDFs are parsed using the `username • Xmo ago` comment header pattern to extract the original post and each comment as separate segments, dropping flair lines, vote/reply UI noise, the "Search in r/ucla Create" page sidebar that pdfplumber otherwise injects mid-text, and moderator/user-deleted placeholders. Article PDFs use coordinate-aware extraction (pdfplumber word positions) to detect paragraph breaks by vertical line-gap and to drop sidebar columns by detecting the dominant content column per page. I also collapse doubled-glyph bold rendering (where pdfplumber sees `HHiigghh` instead of `High`).

**Final chunk count:** **334 chunks** across 10 PDFs, derived from 249 cleaned segments. Distribution: 241 segments → 1 chunk each (short Reddit comments and short paragraphs), 23 segments → 2–4 chunks, 8 segments → 5+ chunks, with the longest single segment (a 9,000-char Reddit comment) producing 14 chunks.

---

## Embedding Model

<!-- Name the embedding model you used and explain your choice.
     Then answer: if you were deploying this system for real users and cost wasn't a constraint,
     what tradeoffs would you weigh in choosing a different model?
     Consider: context length limits, multilingual support, accuracy on domain-specific text,
     latency, and local vs. API-hosted. -->

**Model used:** `sentence-transformers/all-MiniLM-L6-v2`, 384-dimensional vectors, ~22M parameters. I chose it because the corpus is general-domain English without specialized vocabulary that would justify a domain-tuned model, and because the project's local-first design rules out API-hosted embedding services. Encoding all 334 chunks finished in under 3 seconds on CPU. Embeddings are normalized (`normalize_embeddings=True`) and stored in ChromaDB with cosine distance set explicitly via `hnsw:space="cosine"` — Chroma's L2 default is the wrong metric once vectors are normalized. The same model and same normalization are used to embed user queries, enforced by importing `EMBEDDING_MODEL` from a single constant in `embed.py`.

**Production tradeoff reflection:** if cost and latency weren't constraints, the most defensible upgrade would be `BAAI/bge-base-en-v1.5` — same architecture family, ~3x larger, measurably better on standard retrieval benchmarks (BEIR, MTEB), but ~5x slower on CPU and benefits from a GPU. The next tier up would be OpenAI's `text-embedding-3-large`: higher quality still and longer context, at the cost of a paid API dependency and per-query network latency. Two other axes I would consider for production: (1) **context length** — MiniLM truncates input at 256 tokens, which is fine for my 600-character ceiling but would push me toward `mpnet-base` (514 tokens) or BGE (512) for a corpus with longer atomic units; (2) **domain adaptation** — if I were deploying this against a more specialized corpus (e.g., medical school student reviews with heavy medical vocabulary), I would consider fine-tuning MiniLM on labeled query-doc pairs from the domain, which typically beats a generic larger model on the same compute budget.

---

## Grounded Generation

<!-- Explain how your system enforces grounding — how does it prevent the LLM from answering
     beyond the retrieved documents?
     Describe both your system prompt (what instruction you gave the model) and any structural
     choices (e.g., how you formatted the context, whether you filtered low-relevance chunks).
     Do not just say "I told it to use the documents" — show the actual instruction or explain
     the mechanism. -->

**System prompt grounding instruction:** the system prompt to Groq's `llama-3.3-70b-versatile` is:

> "You are a helpful assistant answering questions about UCLA student life based on a curated set of documents (Reddit threads, Daily Bruin articles, BruinLife, and the r/ucla wiki).
>
> Answer the question using only the information in the provided documents. If the documents don't contain enough information to answer, say *'I don't have enough information on that'*.
>
> Each document is labeled [N] with its source filename. When you use a fact from a document, cite it inline using [N]. Do not invent facts, names, prices, or dates that are not in the documents."

The first sentence frames the scope; the second sentence is the hard grounding rule plus the exact abstention phrase; the third sentence handles citation and explicitly forbids invention. I also set `temperature=0.1` to suppress creative completion. The user prompt then contains the 5 retrieved chunks in `[N] (Source: filename.pdf — segment_type, u/author)` format followed by the question.

**How source attribution is surfaced in the response:** the generation pipeline always returns a structured `dict` containing both `answer` (the LLM text, with inline `[1]`, `[2]` markers) and `sources` (a list where each entry has `ref`, `filename`, `source_id`, `source_type`, `segment_type`, `author`, `title`, `raw_text`, `chunk_id`, `similarity`, and `distance`). The `filename` field is the *real* PDF filename, looked up at runtime from `processed/*.json` rather than the slugified ID. Both the CLI (`generate.py`) and the Gradio UI (`app.py`) render the source list alongside the answer so a user can verify every `[N]` claim against its actual chunk text. The filename mapping is also why "Reddit thread" chunks display the author (`u/itwontmendyourheart`) while article chunks display only the source type — the metadata is rich enough that each surface (CLI, UI, future eval script) can render attribution however it wants without losing information.

---

## Evaluation Report

<!-- Run your 5 test questions from planning.md through your system and record the results.
     Be honest — a partially accurate or inaccurate result that you explain well is more
     valuable than a suspiciously perfect result. -->

| # | Question | Expected answer | System response (summarized) | Retrieval quality | Response accuracy |
|---|----------|-----------------|------------------------------|-------------------|-------------------|
| 1 | What is the daily parking rate at the closest public lot to UCLA's main campus? | A specific dollar amount cited from the parking documents (the wiki lists $13/day for campus and medical-center structures) | System cited $7 and $17 as figures appearing in Reddit comments, noted the location/availability was unclear, then concluded with "I don't have enough information to provide a definitive daily parking rate." Did not surface the wiki's $13/day. | Partially relevant — 5 chunks were from parking threads, but the wiki chunk containing the canonical $13 figure did not make top-5 | Partially accurate |
| 2 | Which off-campus neighborhoods are listed as recommended places for UCLA students to live? | A named list (Westwood, Westwood Hills North / "UA neighborhood", and any others mentioned in the off-campus apartment thread) | "I don't have enough information on that. The provided documents do not mention specific off-campus neighborhoods recommended for UCLA students to live." | Partially relevant — chunks were all from the off-campus apartments thread, but were the platform-recommendation chunks (Tripalink, Apartments.com) rather than the chunk that names Westwood Hills North and UA neighborhood | Inaccurate |
| 3 | What is the contact information for the UCLA off-campus housing office? | "The provided documents do not contain this information" — the Ask Housing source listed in planning was not in the actual PDF set, and the answer is not derivable from the included documents | "I don't have enough information on that. None of the provided documents mention the contact information for the UCLA off-campus housing office." Then helpfully listed the search websites that *are* mentioned (UclaOffCampusHousing.com, Apartments.com, Zillow, unishack.org). | Relevant — retrieved off-campus-housing-discussion chunks, which is the correct topical retrieval for an off-domain query | Accurate |
| 4 | Do any documents mention student discounts on monthly parking permits? | Either the exact discount detail, or "the documents do not mention this" | "I don't have enough information on that. None of the documents mention student discounts on monthly parking permits. They do discuss quarterly costs, daily passes, and permit prices, but not monthly parking permits or potential student discounts." | Relevant — retrieved the wiki + Reddit permit-walkthrough chunks (correct sources for the question) | Partially accurate — the abstention is literally correct (no MONTHLY permits in the corpus, only quarterly), but the wiki lists carpool permits at $216/quarter for two-person and $132/quarter for three-person versus $258/quarter standard — that is a discount the system could have flagged, since it was in the retrieved chunks |
| 5 | What time do UCLA dining halls close at night on weekdays? | "The provided documents do not contain this information" — the BruinLife article describes meal plans and dining locations but not operating hours | "I don't have enough information on that. None of the provided documents mention the closing time of UCLA dining halls on weekdays." | Relevant — all 5 chunks from the BruinLife dining article (the correct topical source for the query, even though the answer isn't in any of them) | Accurate |

**Summary:** 2 accurate (Q3, Q5), 2 partially accurate (Q1, Q4), 1 inaccurate (Q2). Three of the five questions involved abstention; the system used the exact required abstention phrase in all three cases and did not hallucinate any prices, names, or dates that were not in the retrieved chunks.

**Retrieval quality:** Partially relevant overall — chunks were always from the right topical source(s), but in two cases (Q1, Q2) the specific chunk containing the canonical answer was outranked by other on-topic chunks.

**Response accuracy:** Partially accurate overall — the system never hallucinated, but it under-answered Q1 and Q2 because retrieval didn't surface the right chunk.

---

## Failure Case Analysis

<!-- Identify at least one question where retrieval or generation did not work as expected.
     Write a specific explanation of *why* it failed, tied to a part of the pipeline.

     "The answer was wrong" is not an explanation.

     "The relevant information was split across a chunk boundary, so retrieval returned
     only half the context — the model didn't have enough to answer correctly" is an explanation.

     "The embedding model treated the professor's nickname as out-of-vocabulary and returned
     results from an unrelated review" is an explanation. -->

**Question that failed:** Q2 — "Which off-campus neighborhoods are listed as recommended places for UCLA students to live?"

**What the system returned:** "I don't have enough information on that. The provided documents do not mention specific off-campus neighborhoods recommended for UCLA students to live."

**Why this is wrong:** the corpus *does* contain neighborhood recommendations. A comment by `u/itwontmendyourheart` in the parking thread explicitly names the relevant area — *"For free parking, the UA neighborhood (Westwood Hills North encompassing frat row + UA apartments) is your best bet"* — and other comments mention Westwood, the area south of campus, and specific buildings like 1301 Brockton Ave. I verified independently by running `python retrieve.py "where can I park near UCLA"`: the `itwontmendyourheart` chunk that names "Westwood Hills North" appears at rank #5 on a parking query, but it never enters top-5 on a "neighborhoods" query because the embedding ranks five other off-campus-apartments-thread chunks higher.

**Root cause (tied to a specific pipeline stage):** this is a **retrieval-stage failure rooted in the embedding semantics**. The `itwontmendyourheart` chunk's *dominant* topical signal is parking — that comment exists in a parking thread, the surrounding sentences are about lots and free spots, and the embedding aggregates all of that. The neighborhood names appear in passing as the *answer* to a parking question, not as the chunk's main subject. When my query "off-campus neighborhoods recommended" is embedded, it scores closer to chunks that are *about* off-campus housing in general (platform recommendations like Tripalink, specific apartment names) than to a chunk that *is about parking but happens to mention neighborhood names*. The embedding model treats topical similarity as a holistic signal across the whole chunk; it has no concept of "facts mentioned inside a chunk." Chunking didn't fail here — the segment-boundary rule did exactly what it was supposed to (kept the comment intact). The failure is that semantic similarity ≠ factual containment, and dense retrieval can't tell the difference between "this chunk is about X" and "this chunk happens to mention X."

**What you would change to fix it:** two complementary changes. (1) **Hybrid retrieval** — run a BM25 keyword search alongside the dense embedding search and merge the results. A keyword search for "Westwood Hills North" or "neighborhood" would surface the parking-thread chunk because of literal token overlap, even when the dense embedding doesn't. (2) **MMR (Maximal Marginal Relevance)** at retrieval time — currently I take the 5 nearest neighbors, which on this query are five very-similar off-campus-thread chunks. MMR would retrieve, say, 20 candidates and then pick 5 that maximize both similarity-to-query *and* diversity-from-each-other, which would force at least one parking-thread chunk into the top-5 instead of five near-duplicate apartment-thread chunks. Both options were deferred in the planning doc as stretch features; this failure is the strongest argument for revisiting MMR.

---

## Spec Reflection

<!-- Reflect on how planning.md shaped your implementation.
     Answer both questions with at least 2–3 sentences each. -->

**One way the spec helped you during implementation:** writing the Chunking Strategy section *before* writing the chunker forced me to commit to specific numbers (600-char ceiling, 80-char overlap) and a specific rule (never cross a segment boundary) before any code existed. When I gave that section to Claude as the spec, the resulting chunker had a clear contract — and when I later ran the validator and found 364 chunks down to 334 after cleanup, every number in the spec section either matched or had a documented reason for not matching. Without that pre-committed spec I would have built the chunker iteratively, with no clean way to tell whether a "looks fine" result actually met an intentional design or had silently drifted. The spec also caught two real issues during implementation: the architecture diagram had to be updated when the pre-cleanup segment count (276) differed from the post-cleanup count (249), and the evaluation Q5 had to be rewritten because the rent figure I'd assumed wasn't in the corpus turned out to be in the Daily Bruin article at $3,223/month.

**One way your implementation diverged from the spec, and why:** the spec originally floated hierarchical / parent-child retrieval as a possible approach (where small child chunks are embedded for precision and larger parent chunks are returned for generation context). I went with flat recursive chunking with segment boundaries instead, and noted the deferral in the planning doc. The reason is implementation complexity: parent-child retrieval requires a second ChromaDB lookup after the initial top-k to expand each child back to its parent, plus extra metadata bookkeeping to record parent IDs on every child chunk. For 334 chunks and 5 eval questions the complexity wasn't justified — the flat strategy gets ~80% of the benefit (chunks that respect natural boundaries) with a tenth of the code. If the corpus had been larger, or if retrieval had failed precision tests (e.g., chunks too short to embed meaningfully), I would have implemented the parent-child layer.

---

## AI Usage

<!-- Describe at least 2 specific instances where you used an AI tool during this project.
     For each: what did you give the AI as input, what did it produce, and what did you
     change, override, or direct differently?

     "I used Claude to help me code" is not sufficient.
     "I gave Claude my Chunking Strategy section from planning.md and asked it to implement
     chunk_text(). It returned a function using a fixed character split. I overrode the
     chunk size from 500 to 200 because my documents are short reviews, not long guides." -->

**Instance 1 — Chunking strategy validation and per-source preprocessing**

- *What I gave the AI:* my proposed chunking parameters (600-character ceiling, 80-character overlap, recursive separator priority `["\n\n", "\n", ". ", " "]`) along with the actual file listing in `documents/` — 7 Reddit PDFs and 3 article PDFs. I asked Claude to evaluate the strategy and tell me whether hierarchical / parent-child retrieval was worth implementing for my corpus.
- *What it produced:* Claude pointed out that a single fixed chunk size would be wrong for the heterogeneous corpus because Reddit comments span 25 to 9,000 characters while news article paragraphs cluster around 100–200 words. It recommended *per-source preprocessing first* (treating Reddit comment boundaries differently from article paragraph boundaries) and treating segment boundaries as hard walls inside the chunker. It explicitly recommended deferring hierarchical retrieval as overkill for 334 chunks and 5 eval questions.
- *What I changed or overrode:* I accepted the per-source preprocessing recommendation and let Claude implement `preprocess.py` with separate Reddit-thread and article parsers, then `chunk.py` as the segment-aware recursive splitter. I kept the deferral on hierarchical retrieval, but later when Q2 failed in the evaluation I revisited that decision — the failure case section above identifies MMR as the right next step rather than parent-child, which I now consider the correct call for this corpus size.

**Instance 2 — Embedding and retrieval implementation with explicit invariants**

- *What I gave the AI:* my Retrieval Approach section from planning.md (model = `sentence-transformers/all-MiniLM-L6-v2`, top-k = 5, distance = cosine) and the chunked corpus at `chunks/chunks.jsonl`. I asked Claude to implement `embed.py` and `retrieve.py` while being conservative about the parts that fail silently if you get them wrong.
- *What it produced:* `embed.py` with four explicit invariants documented inline — `normalize_embeddings=True` on the sentence-transformer call, `hnsw:space="cosine"` on the Chroma collection, defensive metadata coercion to handle `None` author fields on article paragraphs, and a delete-and-rebuild pattern instead of incremental updates. `retrieve.py` then imported `EMBEDDING_MODEL`, `COLLECTION_NAME`, and `CHROMA_DIR` directly from `embed.py` so the query side and document side can't drift. Claude also added a distance-to-similarity conversion (`similarity = 1 - distance`) so result scores read intuitively (larger = better).
- *What I changed or overrode:* I added a structured-source contract on top of what Claude initially produced. The first version of `retrieve.py` returned the raw ChromaDB query response; I asked Claude to wrap it in a dict with explicit `rank`, `similarity`, `distance`, and `metadata` fields, and I added `raw_text` (chunk body without the source prefix) to the metadata stored in ChromaDB so the eventual UI could display clean snippets without parsing prefixes out of the embedded text. I also asked Claude to add a sanity-check probe step that verifies the persisted collection is queryable end-to-end before declaring the embed step complete — that probe caught a metadata-coercion bug during development (one row had `author=None` and would have been silently dropped by Chroma).
