"""Gradio interface for the UCLA Unofficial Guide RAG system.

Thin wrapper around generate.answer(). The interface deliberately surfaces
BOTH the model's text answer AND the underlying source chunks side-by-side
so users can verify any factual claim against its actual provenance — this
is the "show your work" pattern that makes a grounded system trustworthy.

Run with:    python app.py
Then open:   http://127.0.0.1:7860/
"""
from __future__ import annotations

from typing import Tuple

import gradio as gr

from generate import DEFAULT_K, GROQ_MODEL, answer

# The 5 evaluation questions from planning.md, used as one-click examples.
EVAL_QUESTIONS = [
    "What is the daily parking rate at the closest public lot to UCLA's main campus?",
    "Which off-campus neighborhoods are listed as recommended places for UCLA students to live?",
    "What is the contact information for the UCLA off-campus housing office?",
    "Do any documents mention student discounts on monthly parking permits?",
    "What time do UCLA dining halls close at night on weekdays?",
]


def query_handler(question: str, k: int) -> Tuple[str, str]:
    """Run the query through the RAG pipeline and format the response for the UI.

    Returns:
      (answer_markdown, sources_markdown)
    """
    if not question or not question.strip():
        return "_Please enter a question._", ""

    try:
        result = answer(question.strip(), k=int(k))
    except Exception as e:  # surface errors in the UI instead of crashing
        return f"**Error:** `{type(e).__name__}: {e}`", ""

    # --- Answer block --------------------------------------------------
    answer_md = f"### Answer\n\n{result['answer']}\n\n"
    answer_md += f"<sub>_model: `{result['model']}` · top-k: {k}_</sub>"

    # --- Sources block -------------------------------------------------
    if not result["sources"]:
        return answer_md, "_No sources retrieved._"

    src_lines = ["### Sources retrieved\n"]
    for s in result["sources"]:
        attribution = s["segment_type"]
        if s["author"]:
            attribution += f" by u/{s['author']}"
        snippet = s["raw_text"].replace("\n", " ").strip()
        if len(snippet) > 320:
            snippet = snippet[:320].rstrip() + "..."
        src_lines.append(
            f"**{s['ref']} `{s['filename']}`**  \n"
            f"<sub>{attribution} · similarity {s['similarity'] * 100:.1f}% "
            f"· chunk `{s['chunk_id']}`</sub>\n\n"
            f"> {snippet}\n"
        )
    return answer_md, "\n".join(src_lines)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

with gr.Blocks(title="UCLA Unofficial Guide") as demo:
    gr.Markdown(
        "# UCLA Unofficial Guide\n"
        "Ask questions about parking, off-campus housing, dining, and "
        "student life at UCLA. Answers come **only** from the curated "
        "corpus (Reddit threads, Daily Bruin, BruinLife, r/ucla wiki). "
        "If the documents don't contain the answer, the system will say "
        "so rather than guess."
    )

    with gr.Row():
        with gr.Column(scale=4):
            query_input = gr.Textbox(
                label="Your question",
                placeholder="e.g. How do I get a parking permit at UCLA?",
                lines=2,
            )
        with gr.Column(scale=1):
            k_slider = gr.Slider(
                minimum=1, maximum=10, value=DEFAULT_K, step=1,
                label="Top-k chunks",
            )

    submit_btn = gr.Button("Ask", variant="primary")

    with gr.Row():
        with gr.Column(scale=3):
            answer_output = gr.Markdown(label="Answer")
        with gr.Column(scale=2):
            sources_output = gr.Markdown(label="Sources")

    gr.Markdown("### Evaluation questions (click to load)")
    gr.Examples(
        examples=[[q, DEFAULT_K] for q in EVAL_QUESTIONS],
        inputs=[query_input, k_slider],
        label=None,
    )

    submit_btn.click(
        fn=query_handler,
        inputs=[query_input, k_slider],
        outputs=[answer_output, sources_output],
    )
    # Also fire on Enter inside the textbox for ergonomics.
    query_input.submit(
        fn=query_handler,
        inputs=[query_input, k_slider],
        outputs=[answer_output, sources_output],
    )


if __name__ == "__main__":
    demo.launch(theme=gr.themes.Soft())
