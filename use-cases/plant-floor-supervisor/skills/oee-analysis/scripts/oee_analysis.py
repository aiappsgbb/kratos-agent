"""OEE trend + downtime overlay chart for a plant line.

Reads JSON dumps from `iot_get_oee` (+ optional downtime, telemetry) and writes:
  /tmp/oee-trend-<plant>-line-<N>-<date>.png  — chart
  /tmp/oee-trend-<plant>-line-<N>-<date>.csv  — flat OEE export

Usage from `code_interpreter`:
    python /app/use-cases/plant-floor-supervisor/skills/oee-analysis/scripts/oee_analysis.py \
      --plant-id P-CLE \
      --line "Line 3 — Precision" \
      --date 2026-06-09 \
      --oee-json '<JSON>' \
      [--downtime-json '<JSON>'] \
      [--telemetry-json '<JSON>'] \
      --out-dir /tmp
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.dates as mdates
import matplotlib.pyplot as plt


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "x"


def line_number(line_str: str) -> str:
    m = re.search(r"line\s*(\w+)", line_str.lower())
    return m.group(1) if m else slug(line_str)


def parse_iso(s: str) -> datetime:
    # Drop microseconds and use fromisoformat (handles offsets)
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def render(
    oee_rows: list[dict],
    downtime_events: list[dict],
    telemetry_readings: list[dict] | None,
    plant_id: str,
    line: str,
    date_str: str,
    out_dir: Path,
) -> tuple[Path, Path, str]:
    oee_rows = sorted(oee_rows, key=lambda r: r["date"])
    if not oee_rows:
        raise ValueError("oee-json contained no rows")

    plant_slug = slug(plant_id)
    line_num = line_number(line)
    chart_path = out_dir / f"oee-trend-{plant_slug}-line-{line_num}-{date_str}.png"
    csv_path = out_dir / f"oee-trend-{plant_slug}-line-{line_num}-{date_str}.csv"

    # ── CSV ────────────────────────────────────────────────────────────────
    fieldnames = [
        "date", "plant_id", "line",
        "availability_pct", "performance_pct", "quality_pct",
        "oee_pct", "target_oee_pct", "vs_target_pct", "flag",
        "units_produced", "units_target",
    ]
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in oee_rows:
            w.writerow(r)

    # ── Chart ──────────────────────────────────────────────────────────────
    dates = [datetime.fromisoformat(r["date"]) for r in oee_rows]
    oee_pcts = [r["oee_pct"] for r in oee_rows]
    target = oee_rows[-1].get("target_oee_pct") or 80.0

    has_telemetry = bool(telemetry_readings)
    fig_height = 5.5 if has_telemetry else 4.5
    fig, ax = plt.subplots(figsize=(11, fig_height))

    # Threshold bands
    ax.axhspan(target - 5, target,    facecolor="#fff3cd", alpha=0.5, zorder=0, label="_watch")
    ax.axhspan(0,          target - 5, facecolor="#fde2e2", alpha=0.5, zorder=0, label="_investigate")
    ax.axhline(target, linestyle="--", color="#2e7d32", linewidth=1.2,
               label=f"Target {target:.0f}%")

    # OEE line
    ax.plot(dates, oee_pcts, marker="o", color="#0b1f3a", linewidth=2,
            markersize=6, label="OEE %", zorder=5)
    for d, v in zip(dates, oee_pcts):
        ax.annotate(f"{v:.0f}%", xy=(d, v), xytext=(0, 7),
                    textcoords="offset points", ha="center",
                    fontsize=8, color="#0b1f3a")

    # Downtime tick marks at the bottom (one tick per event, on its day, height = duration)
    if downtime_events:
        for ev in downtime_events:
            try:
                d = parse_iso(ev["started_at"])
                dur_min = ev.get("duration_seconds", 0) / 60
                height = min(5, max(0.6, dur_min / 6))  # cap
                ax.axvline(d, ymin=0, ymax=height / 100, color="#c62828",
                           linewidth=1.3, alpha=0.7)
            except Exception:
                continue

    # Telemetry overlay on secondary axis
    if has_telemetry:
        ax2 = ax.twinx()
        t_ts = [parse_iso(r["timestamp"]) for r in telemetry_readings]
        # try a likely-relevant signal; vibration_rms_mm_s first, else first signal
        signal_key = None
        for r in telemetry_readings:
            if r["signals"].get("vibration_rms_mm_s") is not None:
                signal_key = "vibration_rms_mm_s"
                break
        if not signal_key and telemetry_readings:
            signal_key = next(iter(telemetry_readings[0]["signals"].keys()))
        if signal_key:
            t_vals = [r["signals"].get(signal_key) for r in telemetry_readings]
            ax2.plot(t_ts, t_vals, color="#1565c0", linewidth=1.2, alpha=0.85,
                     label=signal_key)
            ax2.set_ylabel(signal_key, color="#1565c0", fontsize=9)
            ax2.tick_params(axis="y", labelcolor="#1565c0")

    # Formatting
    ax.set_ylim(0, 100)
    ax.set_ylabel("OEE (%)", color="#0b1f3a")
    ax.set_title(f"{line} ({plant_id}) — 7-day OEE trend as of {date_str}",
                 fontsize=12, color="#0b1f3a")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d %b"))
    ax.xaxis.set_major_locator(mdates.DayLocator())
    fig.autofmt_xdate()
    ax.grid(True, axis="y", linestyle=":", alpha=0.5)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)

    fig.tight_layout()
    fig.savefig(chart_path, dpi=140)
    plt.close(fig)

    # ── Summary string ────────────────────────────────────────────────────
    first, last = oee_rows[0], oee_rows[-1]
    delta = last["oee_pct"] - first["oee_pct"]
    direction = "rose" if delta > 0 else ("fell" if delta < 0 else "stayed flat")
    summary = (
        f"{line} OEE {direction} from {first['oee_pct']:.0f}% on {first['date']} "
        f"to {last['oee_pct']:.0f}% on {last['date']} "
        f"({'+' if delta >= 0 else ''}{delta:.0f}pp). "
        f"Today {last['flag']} ({last.get('vs_target_pct', last['oee_pct'] - target):+.0f} vs target)."
    )
    return chart_path, csv_path, summary


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--plant-id", required=True)
    p.add_argument("--line", required=True)
    p.add_argument("--date", required=True, help="YYYY-MM-DD (the 'as of' date)")
    p.add_argument("--oee-json", required=True)
    p.add_argument("--downtime-json", default="")
    p.add_argument("--telemetry-json", default="")
    p.add_argument("--out-dir", default="/tmp")
    args = p.parse_args()

    def _load(s: str, key: str | None = None):
        if not s:
            return []
        try:
            data = json.loads(s)
        except json.JSONDecodeError as e:
            print(f"error: {key or 'json'} invalid: {e}", file=sys.stderr)
            sys.exit(2)
        if isinstance(data, dict) and key and key in data:
            return data[key]
        if isinstance(data, dict) and "readings" in data:
            return data["readings"]
        if isinstance(data, dict) and "events" in data:
            return data["events"]
        if isinstance(data, dict) and "oee" in data:
            return data["oee"]
        return data if isinstance(data, list) else []

    oee_rows = _load(args.oee_json, "oee")
    downtime = _load(args.downtime_json, "events")
    telemetry = _load(args.telemetry_json, "readings")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    chart, csv_p, summary = render(
        oee_rows, downtime, telemetry or None,
        args.plant_id, args.line, args.date, out_dir,
    )
    print(summary)
    print(f"Chart: {chart}")
    print(f"CSV:   {csv_p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
