---
name: file-sharing
description: Share generated files (PDFs, CSVs, charts) with the user by writing them to /tmp and referencing the absolute path. The frontend auto-converts /tmp paths into download links.
enabled: true
---

## Instructions

When you generate any file (a visit-prep PDF, a lab-trend chart PNG, a CSV export of a roster), follow this pattern:

1. **Write the file to `/tmp`** with a stable, date-aware name:
   - `/tmp/visit-prep-2026-06-02.pdf`
   - `/tmp/lab-trend-PAT-100006-A1C-eGFR.png`
   - `/tmp/schedule-2026-06-02.csv`
2. **Reference the absolute path** in your chat response. The frontend converts `/tmp/...` paths into download links automatically.
3. **Do NOT** base64-encode the file into the chat. Do NOT inline binary content.

### Common file types in clinician-visit-prep

- `visit-prep-<YYYY-MM-DD>.pdf` — the headline deliverable, produced by **visit-prep-pack-pdf**
- `lab-trend-<patient-id>-<labs>.png` — chart of one or more lab trends, produced by **lab-trend**
- `schedule-<YYYY-MM-DD>.csv` — roster export for handoff or audit

### Constraints

- **Never write real PHI**. All data here is simulated fixture data, but the convention is: never paste names + DOB + MRN + diagnoses outside the agent context if it could be confused for real PHI.
- **Files are ephemeral** — they don't persist across container restarts.
- **No `/etc`, no `/`, no relative paths.** Always `/tmp/<filename>`.
