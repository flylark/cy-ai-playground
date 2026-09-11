"""
Core RAG pipeline + two-tier verification, with a corrected grounding rubric.

The key fix in this file (vs. the earlier scratchbook version):

    verify_grounding() used to implicitly treat "the context doesn't mention
    this" as equivalent to "the answer is unsupported." That's wrong. Those
    are two different things:

      - A model that says "the documentation doesn't cover GraphQL support"
        when GraphQL truly isn't in the retrieved context is being FAITHFUL
        to what it was given. That should score as SUPPORTED (grounded),
        not UNSUPPORTED.
      - A model that asserts a specific fact ("GraphQL is supported at
        /api/graphql") that the context never said is UNSUPPORTED
        (hallucinated) -- that's the real failure mode grounding checks
        exist to catch.

    So verify_grounding is now a judge over one question: "did the answer
    stay faithful to the retrieved context?" -- and a correct, honest
    non-answer counts as faithful. It says nothing about whether the
    non-answer was the *right call given the full corpus* -- that's a
    separate, second question, answered by verify_against_full_corpus.

That two-question split is the whole point of the two-tier design:

    verify_grounding            -> Was the model honest about what it saw?
    verify_against_full_corpus  -> Was what it saw actually enough?

A retrieval-recall failure shows up as: grounding SUPPORTED (model was
honest about its limited context) + full-corpus INCORRECT/RETRIEVAL_MISS
(the real answer existed elsewhere and retrieval didn't surface it). If both
checks always moved together, one of them would be redundant -- so seeing
them diverge on the vocabulary-mismatch case below is the eval doing its
job, not a bug.

Provider-agnostic generation: every function that generates text (the
answer itself, and both judges) takes a `provider` object with a
`.generate(prompt) -> str` method (see providers.py) instead of a hardcoded
Gemini client. This is deliberate -- the judges and the answerer can each
be pointed at Claude or Gemini independently, so an eval run isn't hostage
to a single paid API. Embeddings are the one exception: they still go
through a Gemini client specifically, because Anthropic's API doesn't
serve an embeddings endpoint. Pass that client in separately as
`embed_client`.

Both judges now return the same five keys -- verdict, reasoning, evidence,
confidence, cited_doc_indices -- so run_eval.py can treat them uniformly
and so a wrong verdict is easy to sanity-check: `evidence` is the judge's
supporting quote, not just its own say-so.

cited_doc_indices exists because of a real bug this file used to have: the
context handed to both judges was an unnumbered bullet list, so a judge had
no actual doc index numbers to work with -- any doc number it mentioned in
its `evidence` prose was invented, not grounded in anything it was shown.
(Caught this in practice: a judge's evidence cited "entries 8, 9, and 10"
when doc 10 wasn't even topically related -- it was pattern-matching a
plausible-sounding number, not reporting one it actually saw.) Both judges
are now shown a NUMBERED list using the corpus's own indices, and asked to
return which index/indices their verdict rests on as a real JSON list
instead of a number embedded in a sentence. That makes cited_doc_indices
programmatically comparable to the retrieved indices from
find_relevant_chunks -- e.g. on a RETRIEVAL_MISS, `cited_doc_indices` minus
the indices that were actually retrieved tells you exactly which doc(s)
retrieval should have fetched, with no need to trust free-text prose.
"""

import json
import re

import numpy as np

EMBEDDING_MODEL = "gemini-embedding-001"


def _extract_json(text):
    """Judge prompts ask for JSON; strip markdown fences if the model adds them."""
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in judge output: {text!r}")
    return json.loads(match.group(0))


def _numbered_context(docs, indices):
    """
    Build a "[idx] doc text" block using the corpus's own indices, not
    positional order -- so a judge shown a subset (e.g. the retrieved
    slice) still cites the same numbers run_eval.py already has as
    `retrieved_indices`, rather than inventing its own 0..N numbering
    over whatever subset it happened to see.
    """
    return "\n".join(f"[{i}] {d}" for i, d in zip(indices, docs))


def get_embedding(embed_client, text):
    """embed_client is always a Gemini `genai.Client` -- see module docstring."""
    result = embed_client.models.embed_content(model=EMBEDDING_MODEL, contents=text)
    return np.array(result.embeddings[0].values)


def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def embed_corpus(embed_client, docs):
    return [get_embedding(embed_client, d) for d in docs]


def find_relevant_chunks(embed_client, question, docs, doc_embeddings, top_k=2):
    q_emb = get_embedding(embed_client, question)
    sims = [cosine_similarity(q_emb, d_emb) for d_emb in doc_embeddings]
    top_indices = list(np.argsort(sims)[::-1][:top_k])
    return (
        [docs[i] for i in top_indices],
        [sims[i] for i in top_indices],
        top_indices,
    )


def ask_about_docs_v2(provider, embed_client, question, docs, doc_embeddings, top_k=2):
    relevant_docs, scores, indices = find_relevant_chunks(
        embed_client, question, docs, doc_embeddings, top_k
    )
    context = "\n".join(f"- {d}" for d in relevant_docs)
    prompt = f"""You are a technical assistant answering questions about a system's documentation.
Only use the provided documentation to answer. If the answer isn't in the docs, say so explicitly.

Documentation:
{context}

Question: {question}
Answer:"""

    answer = provider.generate(prompt)
    return {
        "answer": answer,
        "context_docs": relevant_docs,
        "scores": scores,
        "indices": indices,
    }


def verify_grounding(provider, question, answer, context_docs, context_indices):
    """
    Judges ONE thing: given only context_docs, was `answer` a faithful
    representation of what's there?

    Verdicts:
      SUPPORTED   - every claim in the answer is backed by context_docs,
                    OR the answer correctly and honestly states that
                    context_docs do not contain the requested information
                    (a faithful refusal/abstention counts as SUPPORTED).
      UNSUPPORTED - the answer asserts something as fact that context_docs
                    do not contain, or that contradicts context_docs.

    This is deliberately binary on verdict. "Not enough info in context" is
    a fact about the *context*, not a third answer-quality bucket -- what
    matters for grounding is whether the model was honest about that fact.

    context_indices must be the corpus indices matching context_docs
    positionally (e.g. rag_result["indices"] from ask_about_docs_v2) --
    this is what lets cited_doc_indices below refer to real corpus
    positions instead of the judge inventing its own numbering.

    Also returns:
      evidence           - the specific sentence/quote from context_docs
                            the judge relied on (or, for a faithful
                            abstention, the judge's summary of *why*
                            context_docs don't cover it).
      confidence         - the judge's own 0-1 confidence in the verdict.
      cited_doc_indices  - which of context_indices the verdict actually
                            rests on, as a real list -- not a number
                            parsed out of `evidence` prose.
    """
    context = _numbered_context(context_docs, context_indices)
    prompt = f"""You are a strict grounding judge for a RAG system. You will be shown a QUESTION, the CONTEXT
that was retrieved for it, and the ANSWER a model produced using only that context.

The CONTEXT is a numbered list. Each line's number is that document's real ID -- use these
exact numbers when citing which document(s) your verdict rests on. Do not invent numbers that
aren't shown below.

Decide whether the ANSWER is SUPPORTED or UNSUPPORTED by the CONTEXT.

Critical rule: if the CONTEXT does not contain the information needed to answer, and the ANSWER
honestly says so (e.g. "the documentation does not mention X" / "I cannot answer this from the
provided docs"), that is SUPPORTED. A faithful admission that the context lacks something is
NOT the same as an unsupported claim -- the absence of a topic in the context is not itself
a fact the answer got wrong, and a model should not be penalized for accurately reporting an
absence. Only mark UNSUPPORTED if the ANSWER states something as fact that the CONTEXT does not
say, or that contradicts the CONTEXT.

CONTEXT:
{context}

QUESTION: {question}

ANSWER: {answer}

Respond with ONLY a JSON object, no other text:
{{"verdict": "SUPPORTED" or "UNSUPPORTED", "reasoning": "<one sentence>", "evidence": "<the exact sentence from CONTEXT that supports your verdict, or a one-sentence summary of why CONTEXT doesn't cover it>", "confidence": numeric score 0-1, "cited_doc_indices": [list of the document ID numbers from CONTEXT your verdict relies on]}}"""

    return _extract_json(provider.generate(prompt))


def verify_against_full_corpus(provider, question, answer, full_docs, full_indices=None):
    """
    Judges a DIFFERENT thing: given the ENTIRE corpus (not just what was
    retrieved), was `answer` actually correct and complete?

    Verdicts:
      CORRECT        - the answer matches what the full corpus supports,
                        including a correct "not in the docs" when that's
                        true across the WHOLE corpus, not just the
                        retrieved slice.
      RETRIEVAL_MISS - the full corpus DOES contain the answer, but the
                        given ANSWER said it wasn't available / gave a
                        different answer -- i.e. retrieval likely failed
                        to surface the relevant doc(s).
      INCORRECT      - the answer is simply wrong relative to the full
                        corpus (not a retrieval story -- the answer
                        contradicts something the corpus states).

    Comparing this verdict to verify_grounding's verdict on the same
    answer is the actual diagnostic: SUPPORTED + RETRIEVAL_MISS together
    is the retrieval-recall failure signature -- the model was honest
    about a context that shouldn't have been all it got.

    full_indices defaults to range(len(full_docs)) since full_docs is
    normally the entire CORPUS in its natural order (matching corpus.py's
    own numbering) -- pass it explicitly only if full_docs is ever a
    reordered or filtered view.

    Also returns:
      evidence           - the specific sentence from full_docs the judge
                            relied on.
      confidence         - the judge's own 0-1 confidence in the verdict.
      cited_doc_indices  - the real corpus index/indices (from
                            full_indices) the verdict rests on -- for a
                            RETRIEVAL_MISS, subtracting the indices that
                            were actually retrieved tells you exactly
                            which doc(s) retrieval should have fetched,
                            without trusting a number the judge might
                            otherwise invent inside `evidence` prose.
    """
    if full_indices is None:
        full_indices = range(len(full_docs))
    context = _numbered_context(full_docs, full_indices)
    prompt = f"""You are a completeness judge for a RAG system. You will be shown a QUESTION, the FULL
DOCUMENTATION SET (everything that exists, not just what one retrieval pass happened to fetch),
and an ANSWER that was produced using only a subset of that documentation.

The FULL DOCUMENTATION SET is a numbered list. Each line's number is that document's real ID --
use these exact numbers when citing which document(s) matter for your verdict. Do not invent
numbers that aren't shown below.

Decide:
  - CORRECT: the ANSWER is right given the FULL documentation set (including a correct "not
    covered" if the full set genuinely never addresses the question).
  - RETRIEVAL_MISS: the FULL documentation set DOES contain the information needed, but the
    ANSWER failed to use it (e.g. said "not in the docs" or gave an incomplete/wrong answer even
    though the real answer exists elsewhere in the set). This specifically means retrieval likely
    fetched the wrong document(s).
  - INCORRECT: the ANSWER contradicts the full documentation set in a way that isn't explained by
    missing a document -- it's just wrong.

FULL DOCUMENTATION SET:
{context}

QUESTION: {question}

ANSWER: {answer}

Respond with ONLY a JSON object, no other text:
{{"verdict": "CORRECT" or "RETRIEVAL_MISS" or "INCORRECT", "reasoning": "<one sentence>", "evidence": "<one sentence>", "confidence": numeric score 0-1, "cited_doc_indices": [list of the document ID numbers from FULL DOCUMENTATION SET that contain the real answer]}}"""

    return _extract_json(provider.generate(prompt))
