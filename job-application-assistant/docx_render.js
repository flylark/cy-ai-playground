/**
 * Cover-letter .docx rendering, factored out of the visual style already
 * established in resume/cover_letter.js so every generated letter looks
 * consistent with the ones already sent out -- same fonts, same colors,
 * same layout -- regardless of which job it's for.
 */

const {
  Document, Packer, Paragraph, TextRun, AlignmentType,
  BorderStyle, convertInchesToTwip,
} = require("docx");

const NAVY = "1F3864";
const DARK = "222222";
const GREY = "444444";

function nameHeader(name) {
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 40 },
    children: [
      new TextRun({ text: name.toUpperCase(), bold: true, size: 32, color: NAVY, font: "Calibri" }),
    ],
  });
}

function contactLine(contact) {
  const text = `${contact.location}  •  ${contact.phone}  •  ${contact.email}  •  ${contact.linkedin}`;
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 140 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: NAVY, space: 8 } },
    children: [new TextRun({ text, size: 20, color: GREY, font: "Calibri" })],
  });
}

function para(text, opts = {}) {
  return new Paragraph({
    spacing: { after: opts.after ?? 200 },
    children: [new TextRun({ text, size: 22, color: DARK, font: "Calibri" })],
  });
}

/**
 * Renders a tailored cover letter to a docx Buffer.
 *
 * @param {object} opts
 * @param {object} opts.contact       - from resume_data.js's CONTACT
 * @param {string} opts.dateLine      - e.g. "September 8, 2026"
 * @param {string} opts.hiringLine    - e.g. "Hiring Team"
 * @param {string} opts.companyName   - e.g. "Acme Robotics"
 * @param {string[]} opts.paragraphs  - the drafted body paragraphs, in order
 * @param {string} opts.signatureName - printed name under "Sincerely,"
 * @returns {Promise<Buffer>}
 */
async function renderCoverLetter(opts) {
  const { contact, dateLine, hiringLine, companyName, paragraphs, signatureName } = opts;

  const doc = new Document({
    sections: [
      {
        properties: {
          page: {
            size: { width: 12240, height: 15840 }, // US Letter
            margin: {
              top: convertInchesToTwip(0.75),
              bottom: convertInchesToTwip(0.75),
              left: convertInchesToTwip(0.9),
              right: convertInchesToTwip(0.9),
            },
          },
        },
        children: [
          nameHeader(contact.name),
          contactLine(contact),

          para(dateLine, { after: 200 }),
          para(hiringLine, { after: 0 }),
          para(companyName, { after: 200 }),

          para(`Dear ${hiringLine},`, { after: 200 }),

          ...paragraphs.map((p) => para(p)),

          para("Sincerely,", { after: 260 }),
          para(signatureName, { after: 0 }),
        ],
      },
    ],
  });

  return Packer.toBuffer(doc);
}

module.exports = { renderCoverLetter };
