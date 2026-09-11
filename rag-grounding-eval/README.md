# RAG Grounding & Retrieval-Recall Eval

A small, self-contained eval harness for RAG (Retrieval-Augmented Generation) systems, built
against a fictional instrumentation-documentation corpus (an 18-doc knowledge base for a
made-up protein-sequencing platform, "NanoSeq X1"). It demonstrates a two-tier verification
approach that catches a failure mode a single "is this answer grounded?" check cannot: a model
being perfectly honest about a retrieval step that already failed.

## The core idea: two questions, not one

Most RAG grounding checks ask a single question: *is the answer supported by the context it was
given?* That conflates two genuinely different failures:

- The model **lied about what it saw** (hallucinated a fact the retrieved context never stated).
- **Retrieval handed it the wrong context in the first place**, and the model was completely
  honest about that limited (wrong) context.

A single-tier check scores both of these identically — "ungrounded" — which makes it impossible
to tell whether the fix belongs in the generation prompt or in the retrieval pipeline. This
project splits verification into two independent judges:

- `verify_grounding` — *was the model honest about what it saw?* Given only the retrieved
  context, is the answer consistent with it (including a faithful "the docs don't cover this"
  when that's true)?
- `verify_against_full_corpus` — *was what it saw actually enough?* Given the entire corpus, is
  the answer actually correct and complete?

The diagnostic signature of a retrieval-recall failure is **SUPPORTED + RETRIEVAL_MISS**: the
model was faithful to its context, but that context was wrong or incomplete. If the two checks
always moved together, one of them would be redundant — the whole point is to watch for them to
disagree.

## Finding 1 — absence isn't the same as "unsupported"

The first version of `verify_grounding` implicitly treated "the context doesn't mention this" as
equivalent to "the answer is wrong." That's backwards. A model that says *"the documentation
doesn't cover GraphQL support"* when GraphQL genuinely isn't in the retrieved context is being
faithful, not hallucinating — that should score as SUPPORTED. Only a claim the context never made
(or actively contradicts) should score UNSUPPORTED.

The fix: the judge prompt now has an explicit rule that a faithful, honest non-answer counts as
SUPPORTED. Q1 in `run_eval.py` ("Does the instrument support GraphQL?") is the regression test
for this — before the fix, this case risked being marked UNSUPPORTED purely because "GraphQL"
never appears in any doc.

## Finding 2 — two attempts to fool the embedding model failed (which is itself a finding)

The original plan for surfacing a retrieval-recall failure was to make retrieval pick the wrong
single document, using two different tricks:

- **Q2 — vocabulary mismatch.** Asked about reagent stock using plain language with zero
  vocabulary overlap with the source doc's jargon ("cartridge," "buffer stock," "sequencing
  run"). At `top_k=1`, this still retrieved the correct doc with a similarity score of 0.749 —
  not even a close call.
- **Q5 — near-duplicate confusable pair.** Two docs share the same "Reagent Inventory Service"
  vocabulary but cover different facts (stock levels vs. expired-cartridge rejection). A question
  worded toward one but answered by the other still retrieved the correct doc, at 0.855
  similarity — an even wider margin than Q2.

Both attempts failing is a real result, not a wasted test: it says `gemini-embedding-001`
discriminates well on short, well-separated technical documents, both across paraphrase and
across topically adjacent near-duplicates. Tricking a single retrieval call into grabbing the
wrong doc turned out to be genuinely hard here.

## Finding 3 — the actual retrieval-recall failure was structural, not a ranking problem

The failure that did reproduce didn't come from fooling the ranking — it came from asking a
**compound question** that legitimately needs facts from two different docs (doc 7, calibration
status; doc 8, reagent stock level) while `top_k=1` can only return one document, period. No
embedding model fixes this; it's a budget problem, not a quality problem.

- **Q6** (`top_k=1`): retrieved doc 9 (expiration dates) — not even one of the two intended docs,
  a third topically-adjacent one. The answer correctly reported the two things it wasn't shown
  ("does not mention checking reagent stock levels or verifying calibration status"),
  `verify_grounding` scored SUPPORTED (honest about doc 9), and `verify_against_full_corpus`
  correctly caught **RETRIEVAL_MISS**, citing the exact missing sentences from doc 7 and doc 8.
- **Q7** (identical question, `top_k=4`): retrieved docs 9, 8, 7, and 4 — all four genuine
  pre-run checks, with tightly clustered similarity scores (0.724–0.761). The answer became
  complete and both judges agreed: **CORRECT**.

Q6 → Q7 is a causal before/after: raising retrieval budget resolved the failure completely,
confirming the diagnosis. The similarity-score clustering also explains *why* `top_k=1` failed —
the model saw four comparably-relevant docs and could only take one.

## Finding 4 — judges need real document numbers, or they invent them

Early full-corpus judge output cited "documentation entries 8, 9, and 10" as evidence — but doc
10 (Data Export Service) has nothing to do with the question. The bug: both judges were shown an
unnumbered bullet list, so any doc number appearing in their reasoning text was a guess, not
something grounded in what they'd actually seen.

Fix: both judges are now shown a **numbered** list using the corpus's real indices, and required
to return `cited_doc_indices` as an actual JSON list rather than a number embedded in prose. This
makes the diagnosis mechanical: `run_eval.py` now computes `missed_docs` (cited indices minus
retrieved indices) and prints exactly which doc(s) retrieval should have fetched, with no need to
eyeball evidence text against retrieved indices by hand.

## Provider flexibility

Generation and judging can run on either Claude or Gemini (`LLM_PROVIDER=claude` or `gemini` in
`.env`) via a one-method `provider.generate(prompt)` interface in `providers.py`. Embeddings stay
on Gemini specifically in both cases, since Anthropic's API has no embeddings endpoint.

## Files

| File | Purpose |
|---|---|
| `corpus.py` | 18-doc fictional NanoSeq X1 instrumentation corpus, with near-topic distractors and a deliberate confusable pair (doc 8 vs. doc 9) |
| `providers.py` | `ClaudeProvider` / `GeminiProvider`, dispatched by `LLM_PROVIDER` |
| `rag_eval.py` | Embedding + retrieval (`find_relevant_chunks`), answering (`ask_about_docs_v2`), and the two judges (`verify_grounding`, `verify_against_full_corpus`) |
| `run_eval.py` | The 7-question eval suite and report printer |
| `requirements.txt` | `boto3`, `python-dotenv`, `google-genai`, `numpy`, `anthropic` |
| `.env.example` | `LLM_PROVIDER`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, optional model overrides |

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in whichever key(s) you have
python run_eval.py
```

`GOOGLE_API_KEY` is required regardless of `LLM_PROVIDER`, since embeddings always go through
Gemini. Retrieval isn't fully deterministic across phrasings, so Q2 and Q5 in particular are
worth re-running a few times — they're not guaranteed to diverge (and per Finding 2, currently
don't).

## What the 7 questions check

1. **GraphQL** (`top_k=2`) — genuinely absent from the whole corpus; regression test for the
   grounding-rubric fix.
2. **Reagent stock, plain phrasing** (`top_k=1`) — vocabulary-mismatch probe; the embedding model
   handles it fine.
3. **Rate limit** (`top_k=2`) — plain in-context baseline.
4. **User roles** (`top_k=2`) — plain in-context baseline.
5. **Old cartridge** (`top_k=1`) — confusable-pair probe (doc 8 vs. doc 9); retrieval discriminated
   correctly.
6. **Compound pre-run-check question** (`top_k=1`) — the confirmed retrieval-recall failure.
7. **Same question, `top_k=4`** — the causal fix, confirmed.

## Possible next steps

- **Automated pass/fail assertions.** Right now the suite is read by eye; wrapping each question
  in a `pytest` assertion (e.g. "Q6 must produce RETRIEVAL_MISS, Q7 must produce CORRECT") turns
  this into a real regression suite you can run after any prompt or corpus change.
- **Version control.** Put the project under git now that it has a stable, working state, so
  future edits are reviewable diffs instead of manual copy-paste comparison.
- **Push the eval design further.** An aggregate scorecard ("6/7 agree, 1 divergence") instead of
  only per-question output; more compound-question probes across other doc pairs; tracking
  divergence *rate* across repeated runs of the same question, since retrieval isn't fully
  deterministic.

## The underlying lesson

The original 5-document corpus with `top_k=2–3` retrieved 40–60% of the entire knowledge base on
every question — there was no way for retrieval to meaningfully miss anything, so the two-tier
check had nothing to disagree about. A test can only catch a failure mode it's actually capable
of producing. Growing the corpus to 18 documents with real distractors, and specifically
designing probes around vocabulary mismatch, near-duplicate confusion, and compound multi-doc
questions, is what made the retrieval-recall failure (and its fix) demonstrable at all.
