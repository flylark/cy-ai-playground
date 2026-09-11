#!/usr/bin/env node
/**
 * Tailored Application Assistant
 * ================================
 * Given a job posting and the structured resume in resume_data.js, asks
 * Claude to (a) pick and rank the resume bullets most relevant to this
 * specific posting, with a one-line reason for each, and (b) draft a
 * tailored cover letter body in a matching voice. Renders the letter as a
 * .docx styled like the existing cover letters, and prints the bullet
 * recommendations to the terminal (and to a saved highlights file).
 *
 * Usage:
 *   node generate_application.js <job_posting.txt> "<Company Name>" [output_basename]
 *
 * Example:
 *   node generate_application.js postings/acme_robotics.txt "Acme Robotics" acme_robotics
 *
 * Requires ANTHROPIC_API_KEY in .env (copy .env.example to .env first).
 *
 * A deliberate design choice carried over from the RAG eval project: never
 * trust the model's output at face value just because it came back as
 * well-formed JSON. `leadBullets` is validated against resume_data.js's
 * real bullet ids before anything is printed or rendered -- if Claude
 * invents an id that doesn't exist, that's caught and reported as an
 * error, not silently included as if it were a real resume bullet. Same
 * instinct as verify_grounding/verify_against_full_corpus in the RAG
 * project: check AI output against a real source of truth, don't just
 * assume a plausible-looking response is a correct one.
 */

const fs = require("fs");
const path = require("path");
require("dotenv").config();

const Anthropic = require("@anthropic-ai/sdk");
const resume = require("./resume_data");
const { renderCoverLetter } = require("./docx_render");

const MODEL = process.env.ANTHROPIC_MODEL || "claude-sonnet-4-5-20250929";

function extractJson(text) {
  const match = text.match(/\{[\s\S]*\}/);
  if (!match) {
    throw new Error(`No JSON object found in model output: ${text}`);
  }
  return JSON.parse(match[0]);
}

function buildPrompt(jobPostingText) {
  const bullets = resume.allBullets();
  const bulletList = bullets
    .map((b) => `[${b.id}] (${b.company}${b.category ? ` — ${b.category}` : ""}) ${b.text}`)
    .join("\n");
  const strengthsList = resume.CORE_STRENGTHS.map((s) => `[${s.id}] ${s.text}`).join("\n");

  return `You are helping a job applicant tailor their materials to a specific job posting.

CANDIDATE SUMMARY:
${resume.SUMMARY}

CANDIDATE CORE STRENGTHS (each has an ID):
${strengthsList}

CANDIDATE RESUME BULLETS (each has an ID -- you MUST use these exact IDs, do not invent new ones):
${bulletList}

JOB POSTING:
${jobPostingText}

Do two things:

1. Select the 4-6 resume bullets (from the IDs listed above, and/or core-strength IDs) most
   relevant to this specific posting. For each, give a one-sentence reason tying it to something
   the posting actually asks for -- not a generic reason that would apply to any job.

2. Draft a cover letter body as 3-4 paragraphs (no greeting, no sign-off -- just the paragraphs
   between "Dear Hiring Team," and "Sincerely,"). Write it in a professional, direct, technical
   voice consistent with the candidate summary above. Ground every specific claim in the resume
   bullets and strengths listed above -- do not invent achievements, numbers, or experience that
   isn't in the material you were given.

Respond with ONLY a JSON object, no other text, in this exact shape:
{"leadBullets": [{"id": "<bullet or strength id from the lists above>", "reason": "<one sentence tying it to the posting>"}], "coverLetterParagraphs": ["<paragraph 1>", "<paragraph 2>", "..."]}`;
}

async function callClaude(prompt) {
  const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
  const response = await client.messages.create({
    model: MODEL,
    max_tokens: 2000,
    messages: [{ role: "user", content: prompt }],
  });
  return response.content[0].text;
}

/**
 * Cross-checks the model's chosen bullet/strength ids against the real
 * resume data. Returns { valid, invalid } -- callers should treat any
 * `invalid` entries as a bug to surface, not silently drop.
 */
function validateLeadBullets(leadBullets) {
  const validIds = new Set([
    ...resume.allBullets().map((b) => b.id),
    ...resume.CORE_STRENGTHS.map((s) => s.id),
  ]);
  const lookup = new Map([
    ...resume.allBullets().map((b) => [b.id, b.text]),
    ...resume.CORE_STRENGTHS.map((s) => [s.id, s.text]),
  ]);

  const valid = [];
  const invalid = [];
  for (const entry of leadBullets) {
    if (validIds.has(entry.id)) {
      valid.push({ ...entry, text: lookup.get(entry.id) });
    } else {
      invalid.push(entry);
    }
  }
  return { valid, invalid };
}

async function main() {
  const [, , jobPostingPath, companyName, outputBasenameArg] = process.argv;

  if (!jobPostingPath || !companyName) {
    console.error(
      'Usage: node generate_application.js <job_posting.txt> "<Company Name>" [output_basename]'
    );
    process.exit(1);
  }
  if (!process.env.ANTHROPIC_API_KEY) {
    console.error("ANTHROPIC_API_KEY not set -- copy .env.example to .env and fill it in.");
    process.exit(1);
  }

  const jobPostingText = fs.readFileSync(jobPostingPath, "utf-8");
  const outputBasename =
    outputBasenameArg || companyName.replace(/[^a-zA-Z0-9]+/g, "_").replace(/^_+|_+$/g, "");

  console.log(`Reading job posting from ${jobPostingPath}...`);
  console.log(`Calling Claude (${MODEL})...`);

  const prompt = buildPrompt(jobPostingText);
  const rawResponse = await callClaude(prompt);
  const parsed = extractJson(rawResponse);

  const { valid, invalid } = validateLeadBullets(parsed.leadBullets || []);
  if (invalid.length > 0) {
    console.error(
      `WARNING: model referenced ${invalid.length} bullet id(s) that don't exist in resume_data.js -- ` +
        `dropping these, they are not being treated as real resume content:`
    );
    invalid.forEach((e) => console.error(`  - ${e.id}: ${e.reason}`));
  }

  console.log("\n=== Bullets to lead with ===");
  valid.forEach((b, i) => {
    console.log(`${i + 1}. [${b.id}] ${b.text}`);
    console.log(`   why: ${b.reason}\n`);
  });

  const highlightsPath = `${outputBasename}_highlights.md`;
  const highlightsMd = [
    `# Application highlights — ${companyName}`,
    "",
    "Bullets to lead with (validated against resume_data.js):",
    "",
    ...valid.map((b, i) => `${i + 1}. **${b.text}**\n   - _${b.reason}_`),
    invalid.length > 0
      ? `\n> ${invalid.length} model-suggested id(s) were dropped for not matching any real resume bullet.`
      : "",
  ].join("\n");
  fs.writeFileSync(highlightsPath, highlightsMd);
  console.log(`Saved highlights to ${highlightsPath}`);

  const paragraphs = parsed.coverLetterParagraphs || [];
  const dateLine = new Date().toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  const docxBuffer = await renderCoverLetter({
    contact: resume.CONTACT,
    dateLine,
    hiringLine: "Hiring Team",
    companyName,
    paragraphs,
    signatureName: resume.CONTACT.name,
  });

  const docxPath = `${outputBasename}_cover_letter.docx`;
  fs.writeFileSync(docxPath, docxBuffer);
  console.log(`Saved cover letter to ${docxPath}`);

  const txtPath = `${outputBasename}_cover_letter.txt`;
  fs.writeFileSync(txtPath, paragraphs.join("\n\n"));
  console.log(`Saved plain-text version (for pasting into application portals) to ${txtPath}`);
}

main().catch((err) => {
  console.error("Failed:", err.message || err);
  process.exit(1);
});
