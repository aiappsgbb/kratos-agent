"""Render the Olympus Plant Floor Incident Brief PDF via Playwright.

Reads:
  --data-json   JSON object — see the SKILL.md for the full shape
  --chart-path  Path to the OEE chart PNG (from oee-analysis)
  --plant-id    e.g. "P-CLE"
  --line        e.g. "Line 3 — Precision"
  --date        e.g. "2026-06-09"
  --out         Output PDF path

Writes the PDF to --out and prints the absolute path on stdout for the
file-sharing convention to pick up.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parent.parent / "assets" / "incident-brief.html"


def fmt_pct(x: float | int | None, signed: bool = False) -> str:
    if x is None or x == "":
        return "—"
    return f"{float(x):+.0f}%" if signed else f"{float(x):.0f}%"


def fmt_pp(x: float | int | None) -> str:
    if x is None or x == "":
        return "—"
    return f"{float(x):+.0f}pp"


def fmt_num(x: float | int | None, unit: str = "") -> str:
    if x is None or x == "":
        return "—"
    return f"{float(x):,.1f}{unit}".rstrip("0").rstrip(".") + (unit if unit and not f"{x}".endswith(unit) else "")


def fmt_dur(minutes: float | int | None) -> str:
    if minutes is None:
        return "—"
    m = int(minutes)
    if m < 60:
        return f"{m}m"
    return f"{m // 60}h {m % 60:02d}m"


def fmt_dt(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%a %d %b · %H:%M")
    except Exception:
        return iso


def render_html(data: dict, plant_id: str, line: str, date: str, chart_b64: str) -> str:
    template = HTML_PATH.read_text()

    headline = data.get("headline", f"{line} ({plant_id}) — incident brief {date}")
    kpis = data.get("kpis", {})
    device = data.get("device", {})
    po = data.get("production_order", {})
    supplier = data.get("supplier", {})
    downtime = data.get("downtime", []) or []
    recommendations = data.get("recommendations", []) or []
    signoff = data.get("signoff", {})
    narrative = data.get("narrative", "")

    def downtime_rows() -> str:
        if not downtime:
            return "<tr><td colspan='5'><em>None this period.</em></td></tr>"
        rows = []
        for ev in downtime:
            rows.append(
                "<tr>"
                f"<td>{ev.get('id','')}</td>"
                f"<td>{fmt_dt(ev.get('started_at'))}</td>"
                f"<td class='num'>{fmt_dur(ev.get('duration_minutes'))}</td>"
                f"<td><strong>{ev.get('cause_code','')}</strong>"
                f"{' — lot ' + ev['lot_id'] if ev.get('lot_id') else ''}</td>"
                f"<td>{ev.get('related_po_id','—')}</td>"
                "</tr>"
            )
        return "\n".join(rows)

    def recommendation_items() -> str:
        if not recommendations:
            return "<li><em>No recommendations this period.</em></li>"
        return "\n".join(f"<li>{r}</li>" for r in recommendations)

    def supplier_block() -> str:
        if not supplier:
            return "<p><em>No supplier signal this period.</em></p>"
        bits = []
        bits.append(f"<strong>{supplier.get('name','?')} ({supplier.get('id','?')})</strong>")
        if supplier.get("blocked_for_posting"):
            bits.append(
                f"<span class='flag-block'>QA BLOCKED</span> · "
                f"{supplier.get('block_reason','')}"
            )
        lots = supplier.get("rejected_lots") or []
        if lots:
            bits.append(f"Rejected lots: {', '.join(lots)}")
        return "<p>" + "<br>".join(bits) + "</p>"

    def device_block() -> str:
        if not device:
            return "<p><em>No device focus this period.</em></p>"
        bits = [
            f"<strong>{device.get('display_name', device.get('id','?'))}</strong>",
            f"{device.get('vendor','')} {device.get('model','')}",
            f"Status: <strong>{device.get('status','?')}</strong>",
        ]
        if device.get("status_note"):
            bits.append(f"<em>{device['status_note']}</em>")
        vib = device.get("latest_vibration_mm_s")
        thr = device.get("vibration_threshold_mm_s")
        if vib is not None and thr is not None:
            cls = "flag-block" if vib >= thr else "flag-ok"
            bits.append(
                f"Latest vibration: <span class='{cls}'>{vib} mm/s</span> "
                f"(threshold {thr} mm/s)"
            )
        return "<p>" + "<br>".join(bits) + "</p>"

    def po_block() -> str:
        if not po:
            return "<p><em>No production order in scope.</em></p>"
        return (
            f"<p><strong>{po.get('id','?')}</strong> · {po.get('material','')}<br>"
            f"Produced {po.get('qty_produced','?')} of {po.get('qty_ordered','?')} · "
            f"scrap {po.get('qty_scrap','?')} "
            f"(<strong>{fmt_pct(po.get('scrap_pct'))}</strong>) · "
            f"status <strong>{po.get('status','?')}</strong><br>"
            f"{po.get('issue','') or ''}</p>"
        )

    callouts = []
    if kpis.get("oee_pct") is not None:
        flag = ""
        vs = kpis.get("vs_target_pct")
        if vs is not None:
            flag = " — INVESTIGATE" if vs < -5 else " — WATCH" if vs < 0 else ""
        callouts.append(f"Today's OEE {fmt_pct(kpis.get('oee_pct'))} vs target {fmt_pct(kpis.get('target_oee_pct'))}{flag}")
    if kpis.get("wow_delta_pp") is not None and kpis["wow_delta_pp"] < 0:
        callouts.append(f"Down {fmt_pp(kpis['wow_delta_pp'])} week-on-week")
    if kpis.get("downtime_minutes_period"):
        callouts.append(f"{fmt_dur(kpis['downtime_minutes_period'])} of unplanned downtime this period")
    if supplier and supplier.get("blocked_for_posting"):
        callouts.append(f"Blocked-vendor exposure: {supplier.get('name','?')} ({supplier.get('id','?')})")

    return (
        template
        .replace("{{PLANT}}", plant_id)
        .replace("{{LINE}}", line)
        .replace("{{DATE}}", date)
        .replace("{{HEADLINE}}", headline)
        .replace("{{GENERATED_AT}}", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
        .replace("{{KPI_OEE}}", fmt_pct(kpis.get("oee_pct")))
        .replace("{{KPI_VS_TARGET}}", fmt_pct(kpis.get("vs_target_pct"), signed=True) if kpis.get("vs_target_pct") is not None else "—")
        .replace("{{KPI_WOW}}", fmt_pp(kpis.get("wow_delta_pp")))
        .replace("{{KPI_DOWNTIME}}", fmt_dur(kpis.get("downtime_minutes_period")))
        .replace("{{CHART_B64}}", chart_b64)
        .replace("{{CALLOUTS}}", "".join(f"<li>{c}</li>" for c in callouts) or "<li>No critical callouts this period.</li>")
        .replace("{{DOWNTIME_ROWS}}", downtime_rows())
        .replace("{{NARRATIVE}}", (narrative or "<em>No narrative recorded.</em>").replace("\n", "<br>"))
        .replace("{{SUPPLIER_BLOCK}}", supplier_block())
        .replace("{{DEVICE_BLOCK}}", device_block())
        .replace("{{PO_BLOCK}}", po_block())
        .replace("{{RECOMMENDATIONS}}", recommendation_items())
        .replace("{{SUPERVISOR_NAME}}", signoff.get("supervisor_name", "Plant Floor Supervisor"))
        .replace("{{SUPERVISOR_EMAIL}}", signoff.get("supervisor_email", ""))
        .replace("{{MANAGER_NAME}}", signoff.get("manager_name", "Director, Plant Operations"))
        .replace("{{MANAGER_EMAIL}}", signoff.get("manager_email", ""))
    )


async def html_to_pdf(html: str, out_path: Path) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()
        await page.set_content(html, wait_until="networkidle")
        await page.pdf(
            path=str(out_path),
            format="A4",
            margin={"top": "12mm", "bottom": "12mm", "left": "14mm", "right": "14mm"},
            print_background=True,
        )
        await browser.close()


def main() -> int:
    import asyncio

    p = argparse.ArgumentParser()
    p.add_argument("--plant-id", required=True)
    p.add_argument("--line", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--data-json", required=True)
    p.add_argument("--chart-path", default="")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    try:
        data = json.loads(args.data_json)
    except json.JSONDecodeError as e:
        print(f"error: --data-json invalid: {e}", file=sys.stderr)
        return 2

    chart_b64 = ""
    if args.chart_path:
        chart_path = Path(args.chart_path)
        if chart_path.exists():
            chart_b64 = base64.b64encode(chart_path.read_bytes()).decode("ascii")
        else:
            print(f"warning: chart {chart_path} not found; rendering without it", file=sys.stderr)

    html = render_html(data, args.plant_id, args.line, args.date, chart_b64)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        asyncio.run(html_to_pdf(html, out))
    except Exception as e:  # pragma: no cover — surface to the agent
        print(f"error: playwright PDF render failed: {e}", file=sys.stderr)
        html_out = out.with_suffix(".html")
        html_out.write_text(html)
        print(f"HTML fallback: {html_out}")
        return 1

    print(f"PDF: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
