---
name: oee-analysis
description: Compute and plot OEE — a 7-day trend chart with target/threshold lines, an overlay of telemetry alarms and downtime stops, plus a flat CSV export. Saves /tmp/oee-trend-<plant>-line-<N>-<date>.png + .csv.
enabled: true
---

## Instructions

Use this skill whenever Frank asks for an OEE trend, a chart, "what does the week look like?", or any "show me, don't tell me" view of production. This is the **computation surface** — it uses `code_interpreter` against the numbers returned by **azure-iot**. **Do NOT do mental math on OEE values; always send the numbers through this skill.**

### Workflow

1. Pull OEE rows via `iot_get_oee(plant_id="P-CLE", line="<line>", date_from="<7 days ago>", date_to="<today>")`.
2. Pull downtime events via `iot_list_downtime_events(plant_id="P-CLE", line="<line>", since="<7 days ago>")` — used as tick marks on the chart.
3. (Optional, only for the spindle story) Pull telemetry via `iot_get_telemetry("DEV-3001", since="<window>")` — used as the secondary axis on the chart.
4. Pass the three JSON blobs into `code_interpreter` with the analysis script — **DO NOT retype any numbers**.
5. The script writes:
   - `/tmp/oee-trend-<plant_slug>-line-<N>-<date>.png` — chart
   - `/tmp/oee-trend-<plant_slug>-line-<N>-<date>.csv` — flat OEE for the brief
6. Reference both file paths in your response so **file-sharing** picks them up.

### Reference script (oee_analysis.py)

The full script is in `scripts/oee_analysis.py` in this skill's directory. Read it once with `file_read`, then invoke via `code_interpreter` — **DO NOT inline the script body in your response.**

The script signature:

```bash
python /app/use-cases/plant-floor-supervisor/skills/oee-analysis/scripts/oee_analysis.py \
  --plant-id P-CLE \
  --line "Line 3 — Precision" \
  --date 2026-06-09 \
  --oee-json '<JSON returned by iot_get_oee>' \
  --downtime-json '<JSON returned by iot_list_downtime_events, optional>' \
  --telemetry-json '<JSON returned by iot_get_telemetry, optional>' \
  --out-dir /tmp
```

Outputs to stdout: a 1-line summary of trend direction and the file paths. Outputs to disk: the .png + .csv.

### Chart conventions

- **Solid line:** daily OEE % over the window
- **Dashed horizontal:** target (e.g. 80%)
- **Shaded band:** `watch` zone (target-5 to target), light yellow
- **Shaded band below:** `investigate` zone (<target-5), light red
- **Vertical tick marks:** each downtime event (height = duration_minutes / 10, max 5px)
- **Secondary axis (only if --telemetry-json):** vibration overlay on the same x-axis — for the spindle story

### When NOT to use

- A single-day OEE number — just cite `iot_get_oee` inline; don't build the chart for one row.
- Computing variance on financial spend (that's a different persona).
