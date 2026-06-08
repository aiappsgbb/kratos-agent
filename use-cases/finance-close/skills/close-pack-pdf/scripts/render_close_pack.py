"""Render the Olympus close-pack PDF via Playwright.

Reads:
  --data-json   JSON object with: variance_rows, je_rows, accruals,
                vendor_exceptions, owners (cost_centre -> {name, email})
  --chart-path  Path to the variance chart PNG (from variance-analysis)
  --period      e.g. "2026-05"
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

HTML_PATH = Path(__file__).resolve().parent.parent / "assets" / "close-pack.html"


def fmt_money(x: float | int | None) -> str:
    if x is None or x == "":
        return "—"
    n = float(x)
    sign = "-" if n < 0 else ""
    return f"{sign}${abs(n):,.0f}"


def fmt_pct(x: float | int | None) -> str:
    if x is None or x == "":
        return "—"
    return f"{float(x):+.1f}%"


def render_html(data: dict, period: str, chart_b64: str) -> str:
    template = HTML_PATH.read_text()

    # Top-3 callouts: largest abs variance, largest absolute $ variance, biggest "investigate"
    variance_rows = sorted(
        data.get("variance_rows", []),
        key=lambda r: abs(r.get("variance_pct") or 0),
        reverse=True,
    )
    investigate = [r for r in variance_rows if r.get("flag") == "investigate"]

    callouts = []
    if investigate:
        top = investigate[0]
        callouts.append(
            f"{top.get('cost_centre','?')} · {top.get('gl_name','?')} {fmt_pct(top.get('variance_pct'))} "
            f"({fmt_money(top.get('variance_usd'))})"
        )
    accruals = data.get("accruals", [])
    if accruals:
        total = sum(float(a.get("amount_usd") or 0) for a in accruals)
        callouts.append(f"{len(accruals)} accruals booked, total {fmt_money(total)}")
    je_rows = data.get("je_rows", [])
    manuals = [j for j in je_rows if j.get("type") == "Manual"]
    if manuals:
        callouts.append(f"{len(manuals)} Manual JEs — review per policy §4.1")

    def variance_table_rows() -> str:
        out = []
        owners = data.get("owners", {})
        for r in (i for i in variance_rows if i.get("flag") == "investigate"):
            cc = r.get("cost_centre", "")
            owner = owners.get(cc, {})
            owner_html = (
                f"{owner.get('name','—')}" + (f" <small>({owner.get('email','')})</small>" if owner.get("email") else "")
                if owner else "—"
            )
            commentary = r.get("commentary") or "<em class='missing'>missing</em>"
            out.append(
                f"<tr>"
                f"<td>{cc}</td>"
                f"<td>{r.get('gl_account','')} {r.get('gl_name','')}</td>"
                f"<td class='num'>{fmt_pct(r.get('variance_pct'))}</td>"
                f"<td class='num'>{fmt_money(r.get('variance_usd'))}</td>"
                f"<td>{owner_html}</td>"
                f"<td>{commentary}</td>"
                f"</tr>"
            )
        return "\n".join(out) or "<tr><td colspan='6'><em>No investigate-flagged rows this period.</em></td></tr>"

    def je_table_rows() -> str:
        out = []
        for j in je_rows:
            out.append(
                f"<tr>"
                f"<td>{j.get('id','')}</td>"
                f"<td>{j.get('type','')}</td>"
                f"<td>{j.get('status','')}</td>"
                f"<td class='num'>{fmt_money(j.get('total_usd'))}</td>"
                f"<td>{(j.get('memo') or '')[:80]}</td>"
                f"</tr>"
            )
        return "\n".join(out) or "<tr><td colspan='5'><em>No journal entries in period.</em></td></tr>"

    def accrual_rows() -> str:
        if not accruals:
            return "<tr><td colspan='5'><em>No accruals booked this period.</em></td></tr>"
        return "\n".join(
            f"<tr>"
            f"<td>{a.get('je_id','')}</td>"
            f"<td>{a.get('vendor','')}</td>"
            f"<td class='num'>{fmt_money(a.get('amount_usd'))}</td>"
            f"<td>{a.get('evidence_reference','—')}</td>"
            f"<td>{'reversing' if a.get('auto_reverse') else 'fixed'}</td>"
            f"</tr>"
            for a in accruals
        )

    def exception_rows() -> str:
        excs = data.get("vendor_exceptions", [])
        if not excs:
            return "<tr><td colspan='4'><em>None this period.</em></td></tr>"
        return "\n".join(
            f"<tr><td>{e.get('vendor_id','')}</td><td>{e.get('vendor_name','')}</td>"
            f"<td>{e.get('reason','')}</td><td>{e.get('approver','')}</td></tr>"
            for e in excs
        )

    return (
        template
        .replace("{{PERIOD}}", period)
        .replace("{{GENERATED_AT}}", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
        .replace("{{CHART_B64}}", chart_b64)
        .replace("{{CALLOUTS}}", "".join(f"<li>{c}</li>" for c in callouts) or "<li>No critical callouts this period.</li>")
        .replace("{{VARIANCE_ROWS}}", variance_table_rows())
        .replace("{{JE_ROWS}}", je_table_rows())
        .replace("{{ACCRUAL_ROWS}}", accrual_rows())
        .replace("{{EXCEPTION_ROWS}}", exception_rows())
        .replace("{{JE_COUNT}}", str(len(je_rows)))
        .replace("{{ACCRUAL_COUNT}}", str(len(accruals)))
        .replace("{{INVESTIGATE_COUNT}}", str(len(investigate)))
        .replace("{{MANUAL_COUNT}}", str(len(manuals)))
        .replace("{{PREPARED_BY}}", data.get("prepared_by", "Kratos Finance Close Co-pilot"))
    )


async def html_to_pdf(html: str, out_path: Path) -> None:
    """Render HTML to PDF via Playwright (headless Chromium)."""
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
    p.add_argument("--period", required=True)
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

    html = render_html(data, args.period, chart_b64)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        asyncio.run(html_to_pdf(html, out))
    except Exception as e:  # pragma: no cover — surface the error to the agent
        print(f"error: playwright PDF render failed: {e}", file=sys.stderr)
        # Fallback: write the HTML so the user gets something
        html_out = out.with_suffix(".html")
        html_out.write_text(html)
        print(f"HTML fallback: {html_out}")
        return 1

    print(f"PDF: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
