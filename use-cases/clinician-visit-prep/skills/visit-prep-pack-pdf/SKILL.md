---
name: visit-prep-pack-pdf
description: Build the downloadable visit-prep pack PDF for the day's clinic — cover with practitioner + date + roster, then one full pre-visit-summary page per patient. Renders via the inline HTML template + Playwright.
enabled: true
---

## Instructions

Use this skill when Dr. Solomon asks for "the pack", "the PDF", "print my prep", or any variation. This is the **deliverable** the persona exists to produce.

### Workflow

1. **Gather the data** by chaining other skills first:
   - The roster: `daily-schedule` flow against `PRA-9001` for the requested date (default to today, 2026-06-02)
   - Per-patient context: for each booked patient, in parallel:
     - `epic_get_patient`
     - `epic_list_conditions`
     - `epic_list_medications` (status: active)
     - `epic_list_allergies`
     - `epic_list_observations` (limit: 10 recent)
     - The current `epic_get_encounter` for the day's appointment (for `reason_text` if present)
2. **Render** by invoking `scripts/render_visit_prep.py` via `code_interpreter`. Pass the data as JSON:

```bash
python /app/use-cases/clinician-visit-prep/skills/visit-prep-pack-pdf/scripts/render_visit_prep.py \
  --practitioner-name "Dr. Aniyah Solomon" \
  --practitioner-specialty "Internal Medicine, Adult Primary Care" \
  --clinic-date 2026-06-02 \
  --patients-json '<JSON array of patient records>' \
  --out /tmp/visit-prep-2026-06-02.pdf
```

3. **Confirm in chat**: "Visit-prep pack saved to `/tmp/visit-prep-<YYYY-MM-DD>.pdf` — N pages: cover + one per patient. Allergies in red, out-of-range labs flagged." Reference the path so **file-sharing** picks it up.

### Patients-JSON shape

The script expects:

```json
[
  {
    "patient": { "id": "PAT-100001", "mrn": "MRN-100001", "first_name": "Eleanor", "last_name": "Hsu", "date_of_birth": "1948-03-12", "sex": "F", "insurer": "...", "address_city": "Boston", "address_state": "MA" },
    "encounter": { "id": "ENC-200003", "start": "2026-06-02T10:00:00Z", "type": "Office Visit", "reason_text": "Follow-up: BP not at goal", "duration_minutes": 30 },
    "conditions": [{ "code": "I10", "display": "Essential hypertension", "onset": "2014", "status": "active" }],
    "medications": [{ "name": "Lisinopril 20 mg PO daily", "indication": "Hypertension", "since": "2014" }],
    "allergies": [{ "substance": "Penicillin", "severity": "moderate", "reaction": "rash" }],
    "observations": [{ "code": "BP", "value": "148/92", "unit": "mmHg", "effective_at": "2026-04-15", "interpretation": "above goal" }],
    "focus_notes": ["BP control — 148/92 above target", "LDL above post-MI goal"]
  },
  ...
]
```

`focus_notes` is your suggested-focus bullet list — synthesise these from the data + the **clinical-guidelines-reference** skill.

### Assets

- `assets/visit-prep-pack.html` — the Jinja-style HTML template (no Jinja, just `{{PLACEHOLDER}}` string substitution). Clinical white-and-teal theme; cover page; one page per patient.

### Constraints

- One page per patient (use `page-break-before` CSS); cover stays on page 1.
- Render severe (🔴) allergies above the problem list. Moderate (⚠️) inline.
- File size budget < 2 MB. Don't embed images other than the Olympus mark in the template.
- **Do not include real PHI** — fixture data only.
- The "Suggested focus" bullets should reference guideline section numbers when relevant (e.g. *"LDL 82 — above §3.1 target <70 post-MI"*).

### When NOT to use

- Single-patient brief — use **pre-visit-summary** and answer inline.
- Roster only (no per-patient depth) — use **daily-schedule** and answer inline.


<!-- skill-files -->
## Available Files

This skill directory contains the following files you can read with `read_file` using their absolute paths (prefix `/app/use-cases/clinician-visit-prep/skills/visit-prep-pack-pdf/`):

- `assets/visit-prep-pack.html`
- `scripts/render_visit_prep.py`
