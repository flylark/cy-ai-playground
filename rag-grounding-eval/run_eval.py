"""
Eval harness tying corpus.py + rag_eval.py + providers.py together.

Setup:
    pip install -r requirements.txt
    cp .env.example .env   # fill in whichever key(s) you actually have

Provider choice (generation only -- see providers.py for why embeddings
stay on Gemini regardless):

    LLM_PROVIDER=claude   -> needs ANTHROPIC_API_KEY   (default)
    LLM_PROVIDER=gemini   -> needs GOOGLE_API_KEY

Either way GOOGLE_API_KEY is still required for embeddings, since that's
the only embedding model wired up here. If you're on Claude for generation,
Gemini's embedding endpoint is typically usable on a free tier even when
generation quota is the thing that's exhausted -- but if that's not true
for your account, the fix is to swap get_embedding()'s implementation in
rag_eval.py for a different embedding provider (e.g. Voyage AI, OpenAI),
not to route embeddings through providers.py -- that abstraction is
generation-only by design.

What to look for in the output:

  - Q1 (GraphQL, plain top_k): this is the "genuinely not in any doc"
    probe. Expect verify_grounding=SUPPORTED (the model honestly says
    it's not covered) AND verify_against_full_corpus=CORRECT (it really
    isn't covered anywhere). This is the regression test for the grounding
    rubric fix -- before the fix, this case risked being scored
    UNSUPPORTED just because "GraphQL" doesn't appear in the context.

  - Q2 (reagent/vocabulary-mismatch, top_k=1): phrased in plain language
    with no vocabulary overlap with doc 8's jargon ("cartridge", "buffer
    stock", "sequencing run"). In practice this embedding model handles
    paraphrase well enough that this one reliably retrieves doc 8 anyway
    (~0.75 similarity, not even close) -- so it's a good sanity check that
    paraphrase alone isn't a retrieval weakness here, but it's NOT the
    probe likely to produce a divergence. See Q5 for that.

  - Q3/Q4: ordinary in-context questions as a further sanity baseline --
    both checks should agree (SUPPORTED / CORRECT) here.

  - Q5 (near-duplicate confusable pair, top_k=1): doc 8 and doc 9 are both
    "Reagent Inventory Service" docs sharing heavy vocabulary overlap --
    doc 8 covers stock-level checks before a run, doc 9 covers expired-
    cartridge rejection. The real answer to this question lives in doc 9,
    but the question is worded close enough to doc 8's territory that
    retrieval has to actually discriminate between two similar docs rather
    than just connect a paraphrase to the one relevant doc. This is a more
    realistic retrieval-recall failure shape than Q2's vocabulary gap --
    two docs about the same sub-system are much easier to confuse than two
    docs about unrelated topics. If retrieval grabs doc 8 instead of doc 9,
    expect verify_grounding=SUPPORTED (faithful to doc 8, which doesn't
    mention expiration) but verify_against_full_corpus=RETRIEVAL_MISS
    (doc 9 has the real answer). Not guaranteed every run -- rerun a few
    times if it agrees on the first try.

  - Q6 (compound question, top_k=1): a different failure shape than Q2/Q5,
    and one that doesn't depend on tricking the embedding model at all.
    The question genuinely needs facts from TWO docs -- doc 7 (calibration
    must be current before a run) and doc 8 (reagent stock must be
    sufficient before a run) -- but top_k=1 can only return one of them.
    Whichever doc wins the similarity contest, the other one's fact is
    structurally unavailable to the answerer -- this isn't about retrieval
    quality, it's about top_k being smaller than the question's true
    information need. Expect the answer to only address the retrieved
    half, verify_grounding=SUPPORTED (faithful to whichever single doc it
    saw), and verify_against_full_corpus=RETRIEVAL_MISS or INCORRECT
    (the full corpus has both checks; the answer only surfaced one). This
    should diverge close to every run, since it's a structural gap rather
    than a close similarity call. In practice this can surface an even
    more interesting failure than "only one of the two right docs came
    back": top_k=1 may retrieve neither doc 7 nor doc 8, but a third,
    topically-adjacent doc instead (e.g. doc 9, which shares doc 8's
    "Reagent Inventory Service" vocabulary but covers expiration, not
    stock levels) -- so the miss isn't just about budget, it's also about
    which single doc won the similarity contest among several plausible
    candidates.

  - Q7: the exact same question as Q6, but with top_k raised to 4. This is
    the causal check on Q6 -- if Q6 showed a RETRIEVAL_MISS, Q7 existing
    lets you confirm whether raising top_k actually fixes it (both facts
    now retrieved, answer complete, both verdicts agree) or whether
    something deeper than "not enough retrieval budget" was going on. If
    Q7 still diverges even at top_k=4, that's a real finding -- it would
    mean the embedding similarity ranking itself is failing to surface
    doc 7 and/or doc 8 for this phrasing even when there's plenty of room
    in the retrieved set, which points at a retrieval-quality problem
    rather than a top_k-tuning one.

Note on cited_doc_indices / missed_docs: earlier runs showed a judge's
`evidence` prose citing a doc number ("entries 8, 9, and 10") that was
flat-out invented -- the judges were never shown numbered docs, so any
number in their free text was a guess, not something grounded in what they
saw. Both judges now see a numbered doc list and return `cited_doc_indices`
as a real JSON list of real corpus IDs. `missed_docs` below is computed
directly from that: cited_doc_indices minus what retrieval actually
fetched, printed automatically per question instead of requiring you to
eyeball evidence text against retrieved indices yourself.
"""

import os

from dotenv import load_dotenv
from google import genai

from corpus import CORPUS
from providers import get_provider
from rag_eval import (
    ask_about_docs_v2,
    embed_corpus,
    verify_against_full_corpus,
    verify_grounding,
)

load_dotenv()

EVAL_QUESTIONS = [
    {
        "question": "Does the instrument support GraphQL for controlling runs?",
        "top_k": 2,
        "note": "Genuinely absent from the whole corpus -- tests the grounding fix.",
    },
    {
        "question": "Can I start a run if I'm not sure there's enough reagent left?",
        "top_k": 1,
        "note": "Vocabulary-mismatch probe for doc 8 (Reagent Inventory Service).",
    },
    {
        "question": "What happens if I exceed the API rate limit?",
        "top_k": 2,
        "note": "Baseline: clearly in-context (doc 3), should agree both ways.",
    },
    {
        "question": "What are the three user roles and what can each one do?",
        "top_k": 2,
        "note": "Baseline: clearly in-context (doc 13), should agree both ways.",
    },
    {
        "question": "If my last reagent cartridge is old, will the system stop me from starting a run?",
        "top_k": 1,
        "note": "Near-duplicate confusable pair: real answer is doc 9 (expiration), "
        "shares vocabulary with doc 8 (stock levels) -- see module docstring.",
    },
    {
        "question": "What does the system check before letting me start a run -- "
        "does it verify both reagent stock and calibration status?",
        "top_k": 1,
        "note": "Compound question needing doc 7 + doc 8; top_k=1 structurally "
        "can only return one -- see module docstring.",
    },
    {
        "question": "What does the system check before letting me start a run -- "
        "does it verify both reagent stock and calibration status?",
        "top_k": 4,
        "note": "Same question as Q6, but with more retrieval budget -- causal check "
        "on whether raising top_k actually fixes the Q6 RETRIEVAL_MISS, or "
        "whether that failure was something deeper than an insufficient top_k.",
    },
]


def run():
    gemini_key = os.environ.get("GOOGLE_API_KEY")
    if not gemini_key:
        raise SystemExit(
            "GOOGLE_API_KEY not set -- embeddings always use Gemini regardless of "
            "LLM_PROVIDER. Copy .env.example to .env and fill it in."
        )
    embed_client = genai.Client(api_key=gemini_key)

    provider_name = os.environ.get("LLM_PROVIDER", "claude")
    provider = get_provider(provider_name)
    print(f"Using '{provider_name}' for generation/judging, Gemini for embeddings.\n")

    print(f"Embedding {len(CORPUS)} corpus documents...")
    doc_embeddings = embed_corpus(embed_client, CORPUS)
    print("Done.\n")

    results = []
    for case in EVAL_QUESTIONS:
        question = case["question"]
        top_k = case["top_k"]

        rag_result = ask_about_docs_v2(
            provider, embed_client, question, CORPUS, doc_embeddings, top_k=top_k
        )
        grounding = verify_grounding(
            provider,
            question,
            rag_result["answer"],
            rag_result["context_docs"],
            rag_result["indices"],
        )
        full_corpus = verify_against_full_corpus(
            provider, question, rag_result["answer"], CORPUS
        )

        retrieved_indices = [int(i) for i in rag_result["indices"]]
        missed_docs = sorted(
            set(full_corpus.get("cited_doc_indices", []) or []) - set(retrieved_indices)
        )

        results.append(
            {
                "question": question,
                "note": case["note"],
                "top_k": top_k,
                "retrieved_indices": retrieved_indices,
                "scores": [round(float(s), 3) for s in rag_result["scores"]],
                "answer": rag_result["answer"].strip(),
                "grounding_verdict": grounding["verdict"],
                "grounding_reasoning": grounding["reasoning"],
                "grounding_evidence": grounding.get("evidence", ""),
                "grounding_confidence": grounding.get("confidence", None),
                "grounding_cited_indices": grounding.get("cited_doc_indices", []),
                "full_corpus_verdict": full_corpus["verdict"],
                "full_corpus_reasoning": full_corpus["reasoning"],
                "full_corpus_evidence": full_corpus.get("evidence", ""),
                "full_corpus_confidence": full_corpus.get("confidence", None),
                "full_corpus_cited_indices": full_corpus.get("cited_doc_indices", []),
                "missed_docs": missed_docs,
            }
        )

    print("=" * 100)
    for r in results:
        diverges = r["grounding_verdict"] == "SUPPORTED" and r["full_corpus_verdict"] in (
            "RETRIEVAL_MISS",
            "INCORRECT",
        )
        print(f"Q: {r['question']}")
        print(f"   ({r['note']})")
        print(f"   top_k={r['top_k']}  retrieved doc indices={r['retrieved_indices']}  "
              f"similarity scores={r['scores']}")
        print(f"   Answer: {r['answer']}")
        print(f"   verify_grounding           -> {r['grounding_verdict']}  ({r['grounding_reasoning']})")
        print(f"      evidence: {r['grounding_evidence']}  confidence: {r['grounding_confidence']}  "
              f"cited: {r['grounding_cited_indices']}")
        print(f"   verify_against_full_corpus -> {r['full_corpus_verdict']}  ({r['full_corpus_reasoning']})")
        print(f"      evidence: {r['full_corpus_evidence']}  confidence: {r['full_corpus_confidence']}  "
              f"cited: {r['full_corpus_cited_indices']}")
        if diverges:
            print("   >>> DIVERGENCE: grounded-but-wrong -- retrieval likely missed the real doc.")
        if r["missed_docs"]:
            print(f"   >>> retrieval should have fetched doc(s) {r['missed_docs']} but didn't "
                  f"(retrieved {r['retrieved_indices']} instead).")
        print("-" * 100)

    return results


if __name__ == "__main__":
    run()
