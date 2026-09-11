# Tailored Application Assistant

A small tool that takes a job posting and drafts a tailored cover letter plus a ranked list of
which resume bullets to lead with — instead of hand-picking bullets and rewriting a letter from
scratch for every application.

## What it does

1. Reads a job posting (plain text file) and the structured resume in `resume_data.js`.
2. Asks Claude to pick the 4-6 most relevant resume bullets/strengths for *this specific*
   posting, each with a one-sentence reason tying it to something the posting actually asks for.
3. Asks Claude to draft a 3-4 paragraph cover letter body, grounded in those same resume bullets.
4. Renders the letter as a `.docx` styled like the existing cover letters (same fonts/colors/
   layout as `resume/cover_letter.js`), plus a plain-text version for pasting into application
   portals, plus a markdown file of the bullet recommendations.

## A design choice carried over from the RAG eval project

Every bullet id Claude returns is checked against the real ids in `resume_data.js` before
anything gets printed or rendered. If Claude ever names a bullet that doesn't exist, that's
caught and reported as a warning — not silently treated as real resume content. This is the same
instinct as `verify_grounding` / `verify_against_full_corpus` from the RAG project: a
well-formed, confident-looking response from an LLM is not automatically a correct one, so check
it against a real source of truth before trusting it. Here the "source of truth" is your actual
resume data instead of a document corpus, but the discipline is identical.

## Setup

```bash
npm install
cp .env.example .env   # fill in ANTHROPIC_API_KEY
```

## Usage

```bash
node generate_application.js <job_posting.txt> "<Company Name>" [output_basename]
```

Example:

```bash
node generate_application.js postings/acme_robotics.txt "Acme Robotics" acme_robotics
```

This produces, in the current directory:

- `acme_robotics_highlights.md` — the ranked bullets to lead with, and why
- `acme_robotics_cover_letter.docx` — the styled, ready-to-send letter
- `acme_robotics_cover_letter.txt` — the same letter body as plain text, for portals that want
  pasted text instead of an attachment

## Updating your resume content

`resume_data.js` is a manually-maintained structured copy of the resume (summary, core
strengths, and every experience bullet, each with a stable id). If you update the real resume in
`resume/build.js`, update `resume_data.js` to match — this is deliberately not auto-parsed from
`build.js` at runtime, since regex-parsing arbitrary JS is fragile; keeping it a manual,
intentional sync means a resume change can't silently produce garbled output here.

## Possible next steps

- Auto-fetch a job posting from a URL instead of requiring a saved text file.
- A second pass that checks the drafted cover letter for claims not actually grounded in the
  selected resume bullets (the same UNSUPPORTED-detection idea from the RAG project, applied to
  this tool's own output).
- Track past applications (company, date, which bullets were used) — this is the natural
  jumping-off point toward the "application tracker" idea from earlier, if that's still wanted
  later.
