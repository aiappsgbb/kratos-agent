"""Variance analysis for a finance close — flag buckets + chart + CSV export.

Reads a JSON dump of `sap_get_variance_analysis` rows and writes:
  /tmp/variance-<period>.png   — bar chart of variance % by cost centre
  /tmp/variance-<period>.csv   — flat CSV for the close pack

Usage from `code_interpreter`:
    python /app/use-cases/finance-close/skills/variance-analysis/scripts/variance_analysis.py \
      --period 2026-05 \
      --rows-json '<JSON>' \
      --out-dir /tmp
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt


def driver_hint(row: dict) -> str:
    """One-line heuristic for an investigate-flagged row.

    Real driver decomposition is the human's job; this is a seed.
    """
    gl_type = (row.get("gl_type") or "").lower()
    pct = abs(row.get("variance_pct") or 0)
    if pct >= 20 and gl_type == "opex":
        return "price (unit-rate move)"
    if pct >= 20 and gl_type in {"cogs", "materials"}:
        return "volume / mix"
    if row.get("one_off_je_share_pct", 0) >= 50:
        return "one-off (single JE > 50% of variance)"
    return "mix — needs owner commentary"


def render(rows: list[dict], period: str, out_dir: Path) -> tuple[Path, Path]:
    rows = sorted(rows, key=lambda r: abs(r.get("variance_pct") or 0), reverse=True)

    chart_path = out_dir / f"variance-{period}.png"
    csv_path   = out_dir / f"variance-{period}.csv"

    # CSV
    fieldnames = [
        "cost_centre", "cost_centre_name", "gl_account", "gl_name",
        "ytd_actual_usd", "prior_year_usd", "variance_usd", "variance_pct",
        "flag", "suggested_driver",
    ]
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            r2 = dict(r)
            r2["suggested_driver"] = driver_hint(r)
            w.writerow(r2)

    # Chart — top-N by abs variance %
    top_n = rows[:12]
    labels = [f"{r.get('cost_centre','?')} · {r.get('gl_account','?')}" for r in top_n]
    pcts   = [r.get("variance_pct") or 0 for r in top_n]
    colors = ["#c62828" if abs(p) >= 20 else "#f9a825" if abs(p) >= 10 else "#2e7d32" for p in pcts]

    fig, ax = plt.subplots(figsize=(11, 6))
    bars = ax.barh(labels, pcts, color=colors)
    ax.axvline(0, color="#222", linewidth=0.7)
    ax.axvline(20, color="#c62828", linestyle=":", linewidth=0.7, alpha=0.5)
    ax.axvline(-20, color="#c62828", linestyle=":", linewidth=0.7, alpha=0.5)
    ax.set_xlabel("Variance vs prior year (%)")
    ax.set_title(f"Variance review — period {period}")
    ax.invert_yaxis()
    for bar, p in zip(bars, pcts):
        ax.text(p + (1 if p >= 0 else -1), bar.get_y() + bar.get_height() / 2,
                f"{p:+.1f}%", va="center", ha="left" if p >= 0 else "right", fontsize=8)
    fig.tight_layout()
    fig.savefig(chart_path, dpi=140)
    plt.close(fig)

    return chart_path, csv_path


def print_buckets(rows: list[dict]) -> None:
    by_flag: dict[str, list[dict]] = {"investigate": [], "watch": [], "normal": []}
    for r in rows:
        by_flag.setdefault(r.get("flag", "normal"), []).append(r)

    for flag in ("investigate", "watch", "normal"):
        items = by_flag.get(flag) or []
        if not items:
            continue
        print(f"\n== {flag.upper()} ({len(items)}) ==")
        print(f"{'cc':<10} {'gl':<10} {'gl_name':<28} {'var %':>8} {'$ var':>14}  driver hint")
        print("-" * 100)
        for r in sorted(items, key=lambda x: abs(x.get('variance_pct') or 0), reverse=True):
            print(
                f"{r.get('cost_centre','?'):<10} "
                f"{r.get('gl_account','?'):<10} "
                f"{(r.get('gl_name','') or '')[:28]:<28} "
                f"{(r.get('variance_pct') or 0):>+7.1f}% "
                f"${(r.get('variance_usd') or 0):>13,.0f}  "
                f"{driver_hint(r) if flag == 'investigate' else ''}"
            )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--period", required=True)
    p.add_argument("--rows-json", required=True, help="JSON array of variance rows")
    p.add_argument("--out-dir", default="/tmp")
    args = p.parse_args()

    try:
        rows = json.loads(args.rows_json)
    except json.JSONDecodeError as e:
        print(f"error: rows-json is not valid JSON: {e}", file=sys.stderr)
        return 2

    if isinstance(rows, dict) and "rows" in rows:
        rows = rows["rows"]
    if not isinstance(rows, list):
        print("error: rows-json must be a JSON array (or an object with .rows)", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    chart, csv_p = render(rows, args.period, out_dir)
    print_buckets(rows)
    print(f"\nChart: {chart}")
    print(f"CSV:   {csv_p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
