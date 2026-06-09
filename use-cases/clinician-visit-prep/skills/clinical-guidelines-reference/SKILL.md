---
name: clinical-guidelines-reference
description: Cite the most recent NICE / ACC-AHA / ADA guidelines for the chronic conditions Dr. Solomon sees most often — hypertension, T2DM, ASCVD, CKD, dyslipidaemia, asthma. Quote target ranges and recommendation grade by section.
enabled: true
---

## Instructions

Use this skill whenever the user (Dr. Solomon) asks "what does the guideline say?", "what's the target for…?", "should I escalate at…?", or any question whose answer is governed by a published clinical guideline rather than this individual patient's chart.

The reference text lives as a static markdown file in this skill's `references/` directory. Read it on demand and cite the section + the source name + the year in the answer.

### Available references

- `references/chronic-conditions-quick-reference.md` — internal Olympus Health clinician quick-reference compiled from current public guidelines. Sections:
  - §1 Hypertension (NICE NG136 2025 update + ACC/AHA 2024)
  - §2 Type 2 diabetes mellitus (ADA Standards of Care 2026)
  - §3 ASCVD secondary prevention (ACC/AHA 2024)
  - §4 Chronic kidney disease (KDIGO 2024)
  - §5 Lipid management (NICE NG238 2025 + ACC/AHA 2024)
  - §6 Asthma — adult (GINA 2026)
  - §7 Cross-cutting principles (BP measurement technique, drug-drug interactions of note)

### Usage

1. Read the file once at the start of any guideline-relevant turn.
2. **Quote the relevant target verbatim** with the section reference (e.g. *"Per §1.2 (NICE NG136), the BP target for adults with T2DM is <130/80 mmHg confirmed on home or ambulatory measurement."*).
3. **Cite which guideline body said it** — NICE vs ACC/AHA vs ADA vs KDIGO can disagree, and the clinician needs to know which they're citing.
4. **Frame as reference, not order.** "The guideline says X" — let Dr. Solomon decide whether it applies.

### Cross-skill handoffs

- **pre-visit-summary** — when the "Suggested focus" section identifies an out-of-range value, consult this skill to attach the guideline target.
- **lab-trend** — same.
- Never replace this skill with general medical knowledge from training. The quick-reference is the single source of truth for what Olympus Health considers current.

### Constraints

- Do not invent guideline citations. If the question is outside the 7 sections, say so directly: *"I don't have a current Olympus quick-reference for that — recommend checking UpToDate or the source guideline directly."*
- Do not give pharmacological dosing recommendations beyond what's written in the quick-reference. Dose individualisation is the clinician's call.


<!-- skill-files -->
## Available Files

This skill directory contains the following files you can read with `read_file` using their absolute paths (prefix `/app/use-cases/clinician-visit-prep/skills/clinical-guidelines-reference/`):

- `references/chronic-conditions-quick-reference.md`
