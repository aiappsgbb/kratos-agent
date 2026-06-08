---
name: variance-analysis
description: Compute month-end variance — driver decomposition (volume/price/mix/one-off heuristic), anomaly flags, and a matplotlib bar chart of variance % by cost centre saved to /tmp for download.
enabled: true
---

## Instructions

Use this skill whenever the controller asks for a variance review, a chart, or any "is this number reasonable?" sanity check. This is the **computation surface** — it uses `code_interpreter` against the numbers returned by **sap-s4**. Do NOT do mental math on financial figures; always send the numbers through this skill.

### Workflow

1. Pull the raw rows via `sap_get_variance_analysis` for the requested period.
2. Pass the resulting JSON into `code_interpreter` with the analysis script below — DO NOT retype the numbers.
3. The script emits:
   - A compact table per flag bucket (`investigate`, `watch`, `normal`)
   - A matplotlib bar chart saved to `/tmp/variance-<period>.png`
   - A CSV of the underlying data at `/tmp/variance-<period>.csv` for the close pack
4. Reference both file paths in your response so the **file-sharing** convention picks them up.

### Reference script (variance_analysis.py)

The full script is in `scripts/variance_analysis.py` in this skill's directory. Read it once with the file_read tool, then invoke it via `code_interpreter` — DO NOT inline the script body in your response.

The script signature:

```bash
python /app/use-cases/finance-close/skills/variance-analysis/scripts/variance_analysis.py \
  --period 2026-05 \
  --rows-json '<the JSON returned by sap_get_variance_analysis>' \
  --out-dir /tmp
```

Outputs to stdout: the per-bucket tables. Outputs to disk: `/tmp/variance-2026-05.png` and `/tmp/variance-2026-05.csv`.

### Driver decomposition heuristic

The script also classifies each `investigate` row with one of:

- **price** — `gl_account.type == "OpEx"` and prior-year run-rate close, but unit-rate moved (Sentinel-style licence uplift)
- **volume** — variance scales with a known cost-centre headcount / production-order change
- **one-off** — single JE >50% of the variance (manual / accrual / reclass), look up via `sap_list_journal_entries`
- **mix** — none of the above; flag for owner explanation

This is a **suggestion** to seed owner commentary, not a determination. Always present it as `Suggested driver: …` and let the human override.

### When NOT to use

- For a single number / single GL → just cite `sap_get_variance_analysis` inline; don't build the whole chart.
- For non-finance computation (e.g. parse an email body) → use `code_interpreter` directly without this skill.
