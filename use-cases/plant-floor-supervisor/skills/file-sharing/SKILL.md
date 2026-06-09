---
name: file-sharing
description: Share generated files (PDFs, charts, CSVs) with Frank by writing them to /tmp and referencing the absolute path. The frontend auto-converts /tmp paths into download links.
enabled: true
---

## Instructions

When you generate any file Frank needs (incident brief PDF, OEE trend chart, downtime CSV), follow this pattern:

1. **Write the file to `/tmp`** with a stable, date-aware name:
   - `/tmp/line-3-incident-brief-2026-06-09.pdf`
   - `/tmp/oee-trend-cleveland-line-3-2026-06-09.png`
   - `/tmp/oee-trend-cleveland-line-3-2026-06-09.csv`
   - `/tmp/downtime-cleveland-2026-06-09.csv`
2. **Reference the absolute path** in your chat response. The frontend converts `/tmp/...` paths into download links automatically.
3. **Do NOT** base64-encode the file into the chat. Do NOT inline binary content. Do NOT print large CSVs in chat — print the path.

### Naming convention

`<topic>-<scope>-<yyyy-mm-dd>.<ext>` — e.g. `incident-brief` + `line-3` + date + pdf. Stable across re-renders so a "regenerate" doesn't pile up files.

### Common file types in plant-floor-supervisor

- `line-<N>-incident-brief-<date>.pdf` — the headline deliverable per SOP §7
- `oee-trend-<plant>-line-<N>-<date>.png` — chart from **oee-analysis**
- `oee-trend-<plant>-line-<N>-<date>.csv` — flat export for the OneDrive log
- `downtime-<plant>-<date>.csv` — `DT-*` events flat file
- `telemetry-<device>-<date>.csv` — raw readings for engineering review

### Constraints

- **Files are ephemeral** — they don't persist across container restarts.
- **No `/etc`, no `/`, no relative paths.** Always `/tmp/<filename>`.
- **Don't put PII in filenames.** Filenames are visible in chat history; use plant / line / date, not employee names.
