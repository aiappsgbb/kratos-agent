---
name: incident-brief-pdf
description: Build the downloadable incident brief PDF — cover + KPI strip + OEE chart + downtime timeline + root-cause narrative + supplier/material signals + recommended actions + sign-off, per SOP §7.1. Renders via the inline HTML template + Playwright.
enabled: true
---

## Instructions

Use this skill when Frank asks for "the brief", "the PDF", "send it to Wes", or any variation. This is the **deliverable** the persona exists to produce, and per SOP §7 it is **required** for any §4.3-or-above escalation.

### Workflow

1. **Gather the data** by chaining other skills first:
   - OEE 7-day trend via `iot_get_oee` (plant, line, date_from=7d-ago)
   - Downtime events via `iot_list_downtime_events` (plant, line, since=7d-ago)
   - Device twin via `iot_get_device` (the equipment in the headline)
   - Telemetry window via `iot_get_telemetry` (the spindle, last 72h)
   - Production order via `sap_get_production_order` (the `related_po_id` from downtime)
   - Vendor via `sap_get_vendor` (the supplier blamed in the PO, with `blocked_for_posting` flag)
   - Supervisor + manager via `workday_get_employee` (Frank + Wes, for sign-off block)

2. **Read the policy** via the **plant-policy-reference** skill — §7.1 defines the contents and order; do not deviate.

3. **Read the chart** that **oee-analysis** already generated at `/tmp/oee-trend-<plant>-line-<N>-<date>.png`. If it doesn't exist yet, generate it before continuing.

4. **Render** by invoking `scripts/render_incident_brief.py` via `code_interpreter`. Pass the gathered data as a single JSON blob:

```bash
python /app/use-cases/plant-floor-supervisor/skills/incident-brief-pdf/scripts/render_incident_brief.py \
  --plant-id P-CLE \
  --line "Line 3 — Precision" \
  --date 2026-06-09 \
  --data-json '<JSON with headline, kpis, downtime, narrative, supplier, recommendations, signoff>' \
  --chart-path /tmp/oee-trend-p-cle-line-3-2026-06-09.png \
  --out /tmp/line-3-incident-brief-2026-06-09.pdf
```

5. **Confirm in chat:** "Incident brief saved to `/tmp/line-3-incident-brief-2026-06-09.pdf` — N pages, includes OEE chart, M downtime events, root-cause narrative, K recommended actions." Reference the path so **file-sharing** picks it up.

6. **Offer the natural next step:** "Want me to log the maintenance work order against DEV-3001 and draft Wes the cover email?" — handoff to **servicenow** (work order) + **m365-graph** (email). Do NOT auto-start writes.

### Assets

- `assets/incident-brief.html` — HTML template, navy/gold Olympus theme. Self-contained CSS, embeds the chart as base64 PNG, generates the §7 sections in order.

### data-json shape (what `render_incident_brief.py` expects)

```json
{
  "headline": "Line 3 Precision Spindle — vibration alarm + 4 micro-stops",
  "kpis": {
    "oee_pct": 49, "target_oee_pct": 80, "vs_target_pct": -31,
    "wow_delta_pp": -10, "downtime_minutes_period": 142
  },
  "downtime": [
    {"id": "DT-3004", "started_at": "...", "duration_minutes": 28,
     "cause_code": "VIB_ALARM", "lot_id": null, "related_po_id": "PO-9003"},
    "..."
  ],
  "device": {
    "id": "DEV-3001", "display_name": "CLE-L3-SPINDLE-01",
    "vendor": "Siemens", "model": "SINAMICS S210",
    "status": "Warning", "status_note": "...",
    "latest_vibration_mm_s": 5.4, "vibration_threshold_mm_s": 4.5
  },
  "production_order": {
    "id": "PO-9003", "material": "MAT-201 — Model A",
    "qty_produced": 120, "qty_ordered": 150, "qty_scrap": 30, "scrap_pct": 20.0,
    "status": "Issue", "issue": "..."
  },
  "supplier": {
    "id": "V-1201", "name": "Northbridge",
    "blocked_for_posting": true, "block_reason": "Quality hold pending QA dispute (May 2026)",
    "rejected_lots": ["Q-NB-44193", "Q-NB-44197"]
  },
  "narrative": "Two-paragraph free-text narrative …",
  "recommendations": [
    "Log P2 maintenance work order against CI-DEV-3001 with Plant Maintenance",
    "Quarantine remaining Northbridge lots on the floor (per SOP §5.3)",
    "Reassign Devon to Line 1 backfill until spindle is inspected",
    "Escalate to QA Cleveland lead (cc on brief, per §4.3)"
  ],
  "signoff": {
    "supervisor_name": "Frank Delgado", "supervisor_email": "frank.delgado@…",
    "manager_name":   "Wesley Park",    "manager_email":   "wesley.park@…"
  }
}
```

### Constraints

- **Always include all §7.1 sections in order.** If a section has nothing to report (e.g. no supplier signal), print "None this period" — do not skip the heading.
- The chart must be the one **oee-analysis** generated, not a re-render — keeps the PDF consistent with what Frank already saw in chat.
- File size budget: < 2 MB. If the chart pushes over, drop to 100 DPI.
- **Do not auto-send.** Building the PDF is allowed; emailing it is a write and must go through **m365-graph** (email section).

### When NOT to use

- For a verbal summary of what's happening on the floor — answer inline, don't render a PDF.
- For interim numbers (line still running, no §4.3 trigger) — answer inline.
- Per SOP §7 a brief is only required for §4.3 or above — don't generate one for a 5-minute stop.
