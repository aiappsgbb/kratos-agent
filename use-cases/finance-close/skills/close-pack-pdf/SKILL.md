---
name: close-pack-pdf
description: Build the downloadable close pack PDF — variance chart + JE queue + accruals + sign-off — per §8.1 of the close policy. Renders via the inline HTML template + Playwright.
enabled: true
---

## Instructions

Use this skill when the controller asks for "the close pack", "the PDF", "send it to Sofia", or any variation. This is the **deliverable** the persona exists to produce.

### Workflow

1. **Gather the data** by chaining other skills first:
   - Variance rows via `sap_get_variance_analysis` (period)
   - JE list via `sap_list_journal_entries` (period, all types)
   - Newly posted accruals — same call, filter `type=Accrual`
   - Cost-centre owners via cross-MCP join: `sap_get_cost_centre` → `workday_get_employee`
   - Vendor exceptions: any JE crediting `sanctioned=true` or `blocked=true` vendors

2. **Read the policy** via the **close-policy-reference** skill — the pack order is defined by §8.1 and must be followed exactly.

3. **Read the variance chart** that **variance-analysis** already generated at `/tmp/variance-<period>.png`. If it doesn't exist yet, generate it before continuing.

4. **Render** by invoking `scripts/render_close_pack.py` via `code_interpreter`. Pass the gathered data as a single JSON blob to keep the call short:

```bash
python /app/use-cases/finance-close/skills/close-pack-pdf/scripts/render_close_pack.py \
  --period 2026-05 \
  --data-json '<JSON with variance_rows, je_rows, accruals, vendor_exceptions, owners>' \
  --chart-path /tmp/variance-2026-05.png \
  --out /tmp/close-pack-2026-05.pdf
```

5. **Confirm in chat:** "Close pack saved to `/tmp/close-pack-2026-05.pdf` — N pages, includes chart, JE queue, M accruals, K vendor exceptions." Reference the path so the **file-sharing** convention picks it up for download.

6. **Offer the natural next step:** "Want me to draft Sofia the cover email?" — handoff to **variance-email**.

### Assets

- `assets/close-pack.html` — Jinja2 template, navy/gold theme matching the Olympus brand. Self-contained CSS, embeds chart as base64 PNG, generates sign-off blocks.
- `references/close-pack-spec.md` — what §8.1 expects, with section-by-section guidance and the per-row data shapes.

### Constraints

- **Always include the §8.1 sections in order.** Don't skip the Vendor Exceptions section even if empty — print "None this period." instead.
- The chart must be the one **variance-analysis** generated, not a re-render — keeps the PDF consistent with what the controller already saw in chat.
- File size budget: < 2 MB. If the chart pushes over, drop the chart to 100 DPI.
- **Do not auto-send.** Building the PDF is allowed; emailing it is a write and must go through **variance-email**.

### When NOT to use

- For a verbal summary of the close — answer inline, don't render a PDF.
- For interim numbers (close still open) — render with status "DRAFT — Day N of close" in the cover.
