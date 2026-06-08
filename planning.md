# Project 1 Planning: The Unofficial Guide

> Write this document before you write any pipeline code.
> Your spec and architecture diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Update the Retrieval Approach and Chunking Strategy sections if you change your approach during implementation.
> Update this file before starting any stretch features.

---

## Domain

<!-- What domain did you choose? Why is this knowledge valuable and hard to find through official channels? -->

I chose UCLA as my university, and gathered 10 documents to explore off campus life, parking situations, college food and student life at UCLA through unofficial sources.  

## Documents

<!-- List your specific sources: URLs, subreddit names, forum threads, or file descriptions.
     Aim for at least 10 sources that together cover different subtopics or perspectives within your domain. -->

| # | Source | Description | URL or location |
|---|--------|-------------|-----------------|
| 1 | r/ucla - Off Campus Apartments | Reddit thread where UCLA students discuss finding and living in off-campus apartments in Westwood | https://www.reddit.com/r/ucla/comments/1b16h81/off_campus_apartments/ |
| 2 | r/ucla - Parking Discussion | Reddit thread where students discuss parking experiences and tips near UCLA | https://www.reddit.com/r/ucla/comments/1q49rn6/parking/ |
| 3 | r/ucla Wiki - Parking | UCLA subreddit wiki page with community-compiled parking information and guidance | https://www.reddit.com/r/ucla/wiki/parking/ |
| 4 | r/ucla - Parking Permits Walkthrough | Reddit thread where students ask for and share step-by-step guidance on obtaining UCLA parking permits | https://www.reddit.com/r/ucla/comments/1mhrjit/please_walk_me_through_parking_permits/ |
| 5 | Daily Bruin Stack - Campus Living | Daily Bruin data journalism piece analyzing UCLA campus living costs, options, and student trends | https://stack.dailybruin.com/2022/11/30/campus-living/ |
| 6 | Daily Bruin - Westwood Apartment Hunting | Daily Bruin article covering the competitive and fast-moving Westwood off-campus rental market | https://dailybruin.com/2026/03/07/high-demand-fast-pace-inside-the-westwood-apartment-hunting-process |
| 7 | Bruin Commuters | Official UCLA resource hub for commuter students covering transportation, parking, and off-campus life | https://bruincommuters.ucla.edu/ |
| 8 | UCLA Housing - Ask Housing | Official UCLA Housing knowledge base and FAQ portal for student housing questions | https://ask.housing.ucla.edu/ |
| 9 | UCLA Transportation - Student Parking | Official UCLA Transportation page detailing student parking permit options, lots, and policies | https://transportation.ucla.edu/campus-parking/students |
| 10 | r/ucla - Unofficial Guide to UCLA (2018) | Comprehensive community-written Reddit guide covering many aspects of UCLA student life including housing and commuting | https://www.reddit.com/r/ucla/comments/9itxyf/the_redditors_unofficial_guide_to_ucla_2018/ |

---

## Chunking Strategy

<!-- How will you split documents into chunks?
     State your chunk size (in tokens or characters), overlap size, and explain why those
     numbers fit the structure of your documents.
     A review-heavy corpus warrants different chunking than a long FAQ. -->

**Chunk size:**
600 characters (ceiling, not average) most short Reddit comments end up as single sub-600 chunks because the splitter never crosses segment boundaries
**Overlap:**
80 characters, snapped to word boundary, only applied between chunks split from the same segment
**Reasoning:**
Since most of the documents are reddit discussions, and some of them are 9 paragraphs long and some just short one-liners, implementing a chunking strategy with fixed-size chunks will not be suitable. That is why using segment boundaries ensure every chunk holds a meaning, and the overlap of 80 does not create coherence damage.
---

## Retrieval Approach

<!-- Which embedding model are you using (e.g., all-MiniLM-L6-v2 via sentence-transformers)?
     How many chunks will you retrieve per query (top-k)?
     If you were deploying this for real users and cost wasn't a constraint, what tradeoffs
     would you weigh in choosing a different embedding model — context length, multilingual
     support, accuracy on domain-specific text, latency? -->

**Embedding model:**
Using all-MiniLM-L6-v2. Saw it's use in Hugging Face as well, and seems to fit our needs of semantic search. 
**Top-k:**
5 — ~2,500 chars of context, enough to surface multiple Reddit perspectives without diluting precision.
**Production tradeoff reflection:**
if cost weren't a constraint, I'd consider BAAI/bge-base-en-v1.5 for higher retrieval accuracy and add a cross-encoder re-rank stage. For 364 chunks and 5 eval questions, the MiniLM baseline is the right call — the cost of a worse embedding model is more visible than the cost of a worse k.
---

## Evaluation Plan

<!-- List your 5 test questions with their expected correct answers.
     Questions should be specific enough that you can judge whether the system's response
     is right or wrong. "What are good dining halls?" is too vague.
     "What do students say about wait times at [dining hall name] during lunch?" is testable. -->

| # | Question | Expected answer |
|---|----------|-----------------|
| 1 | What is the daily parking rate at the closest public lot to UCLA's main campus? | A specific dollar amount (e.g. "$3/hour" or "$15/day") cited from the parking document — not a guess |
| 2 | Which off-campus neighborhoods are listed as recommended places for UCLA students to live? | A named list of neighborhoods (e.g. Westwood, Palms, Mar Vista) drawn from the housing document |
| 3 | What is the contact information for the UCLA off-campus housing office? | A specific phone number, address, or URL from the document — fail if hallucinated |
| 4 | Do any documents mention student discounts on monthly parking permits? | Either the exact discount detail from the doc, OR "the documents do not mention this" — fail if the system guesses |
| 5 | What time do UCLA dining halls close at night on weekdays? | "The provided documents do not contain this information" — the BruinLife article describes meal plans and dining locations but does not list operating hours; fail if the system invents a closing time |
---

## Anticipated Challenges

<!-- What could go wrong? Name at least two specific risks with reasoning.
     Consider: noisy or inconsistent documents, missing source attribution, off-topic
     retrieval, chunks that split key information across boundaries. -->

1. Documents and texts may not be parsed well enough to extract information. Some questions may be considered out of scope. 

2. Source of document could be hallucinated response and may not actually come from the document itself. Being able to actually source will be great.

---

## Architecture

<!-- Draw a diagram of your pipeline showing the five stages:
     Document Ingestion → Chunking → Embedding + Vector Store → Retrieval → Generation
     Label each stage with the tool or library you're using.
     You can use ASCII art, a Mermaid diagram, or embed a sketch as an image.
     You'll use this diagram as context when prompting AI tools to implement each stage. -->

```
┌──────────────────────────────────────────────────────────────────────┐
│                  THE UNOFFICIAL GUIDE — RAG PIPELINE                 │
└──────────────────────────────────────────────────────────────────────┘

   [1] DOCUMENT INGESTION
       documents/*.pdf  ──►  preprocess.py  ──►  processed/corpus.jsonl
       (10 PDFs: Reddit threads, Daily Bruin, BruinLife, UCLA wiki)
       tool: pdfplumber + per-source cleaners (Reddit / article)
       output: 249 clean text segments with metadata
                                  │
                                  ▼
   [2] CHUNKING
       processed/corpus.jsonl  ──►  chunk.py  ──►  chunks/chunks.jsonl
       recursive splitter on ["\n\n", "\n", ". ", " "]
       600-char ceiling • 80-char overlap • segment boundaries hard
       output: 334 chunks, each with [source — author] prefix
                                  │
                                  ▼
   [3] EMBEDDING + VECTOR STORE
       chunks/chunks.jsonl  ──►  embed.py  ──►  chroma/  (local DB)
       model: sentence-transformers/all-MiniLM-L6-v2  (384-dim)
       store: ChromaDB, cosine similarity
       output: 334 vectors + metadata, persisted on disk
                                  │
                                  ▼
   [4] RETRIEVAL
       user query  ──►  embed query  ──►  ChromaDB top-k=5
                                              │
                                  returns 5 chunks + sources
                                              │
                                              ▼
   [5] GENERATION
       query + 5 retrieved chunks  ──►  Groq LLM  ──►  grounded answer
       system prompt: "answer only from provided context, cite sources"
       interface: Gradio or Streamlit (milestone 5)
                                              │
                                              ▼
                                       answer + citations
```


## AI Tool Plan

<!-- For each part of the pipeline below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, which requirements)
     - What you expect it to produce
     - How you'll verify the output matches your spec

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Chunking Strategy section and ask it to implement chunk_text()
     with my specified chunk size and overlap" is a plan. -->
I will give Claude my strategy for chunking and ask it to evaluate, then implement the strategy. Preprocessing documents to .json format will be done with the help of Claude Code as well. I will review the functions used, and the logic behind every step.

**Milestone 3 — Ingestion and chunking:**
Gave Claude my Chunking Strategy section (600-char ceiling, 80-char overlap, segment boundaries hard) plus the list of source types in `documents/`. Asked it to produce `preprocess.py` (per-source PDF cleaner — Reddit thread vs. article) and `chunk.py` (recursive character splitter on `["\n\n", "\n", ". ", " "]`). Verified output with `validate_chunks.py`, which prints 5 random chunks and runs four diagnostics: empty/short chunks, HTML residue, length variation (coefficient of variation), and metadata completeness. Iterated until all checks passed and the random samples were substantive and self-contained.

**Milestone 4 — Embedding and retrieval:**
Gave Claude my Retrieval Approach section (`all-MiniLM-L6-v2`, top-k=5, cosine) and `chunks/chunks.jsonl`. Asked it to produce `embed.py` (sentence-transformers → ChromaDB with explicit `hnsw:space="cosine"` and `normalize_embeddings=True`) and `retrieve.py` (function + CLI, importing the embedding model name from `embed.py` so both scripts can't drift). Verified by running 5 probe queries spanning parking, housing, dining, and open-ended advice — confirmed top hits at 80%+ similarity for specific factual queries and correct source-thread retrieval for fuzzy ones.

**Milestone 5 — Generation and interface:**
Plan to give Claude the retrieved-chunks format from `retrieve.py` and ask it to produce `generate.py` that calls the Groq API with a grounded-answer system prompt enforcing "answer only from the provided context; cite sources by chunk_id; say 'the documents do not contain this' rather than guess." Will wrap it in a minimal Gradio interface. Verify by running the 5 Evaluation Plan questions end-to-end and checking that Q5 (no answer in corpus) correctly returns the abstention message rather than inventing closing hours.
