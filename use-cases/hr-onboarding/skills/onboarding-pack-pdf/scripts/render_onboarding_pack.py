"""Render the Olympus Industries onboarding pack PDF via Playwright."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parent.parent / "assets" / "onboarding-pack.html"


def _badge(state: str) -> str:
    s = (state or "").lower()
    if any(k in s for k in ("resolved", "closed", "complete", "done", "booked", "cleared", "ok")):
        return "<span class='badge ok'>✓ done</span>"
    if any(k in s for k in ("in progress", "pending", "scheduled", "target")):
        return "<span class='badge wip'>⏳ in flight</span>"
    if any(k in s for k in ("blocked", "missing", "outstanding")):
        return "<span class='badge blocked'>⛔ blocked</span>"
    return f"<span class='badge'>{state}</span>"


def _bool_badge(b: bool, true_label: str = "✓ yes", false_label: str = "✗ no") -> str:
    return f"<span class='badge {'ok' if b else 'blocked'}'>{true_label if b else false_label}</span>"


def render_html(args: argparse.Namespace, status: dict) -> str:
    template = HTML_PATH.read_text()
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    offer = status.get("offer", {}) or {}
    workday = status.get("workday", {}) or {}
    it_req = status.get("it_req", {}) or {}
    m365 = status.get("m365", {}) or {}
    notes = status.get("checklist_owner_notes", []) or []

    # Pre-hire phase rows
    prehire_rows = [
        ("Offer countersigned", offer.get("countersigned_on", "—"), _badge("done" if offer.get("countersigned_on") else "outstanding")),
        ("Background check", offer.get("background_check", "—"), _badge("done" if "clear" in (offer.get("background_check") or "").lower() else "outstanding")),
        ("Workday Pre-Hire", workday.get("state", "—"), _badge(workday.get("state", ""))),
        ("Salary band confirmed (§3 + §8)", "yes" if workday.get("salary_band_ok") else "needs review", _bool_badge(bool(workday.get("salary_band_ok")))),
    ]

    # Provisioning phase rows
    access_groups = ", ".join(it_req.get("access_groups", []) or []) or "—"
    provisioning_rows = [
        ("IT REQ ticket", it_req.get("id", "—"), _badge(it_req.get("state", ""))),
        ("Laptop shipped", it_req.get("laptop_eta", "—"), _badge("done" if it_req.get("laptop_eta") else "outstanding")),
        ("M365 mailbox (§1.3 target day -5)", "provisioned" if m365.get("mailbox_provisioned") else it_req.get("mailbox", "pending"), _bool_badge(bool(m365.get("mailbox_provisioned")))),
        ("Entra access groups", access_groups, _badge("done" if access_groups != "—" else "outstanding")),
    ]

    # Welcome phase rows
    welcome_rows = [
        ("Welcome email — manager (§1.4 day -2)", "pending" if not notes else "tracked", _badge("in flight")),
        ("Welcome email — People (§1.4 day -1)", "draft pending", _badge("in flight")),
        ("Day-1 1:1 booked (§1.5)", m365.get("welcome_1on1_when", "—"), _bool_badge(bool(m365.get("welcome_1on1_booked")))),
        ("Buddy assigned", "see notes" if notes else "outstanding", _badge("in flight" if notes else "outstanding")),
    ]

    def _row(label: str, value: str, badge: str) -> str:
        return f"<tr><td class='label'>{label}</td><td>{value}</td><td class='right'>{badge}</td></tr>"

    def _section(rows: list) -> str:
        return "".join(_row(*r) for r in rows)

    notes_html = "<ul>" + "".join(f"<li>{n}</li>" for n in notes) + "</ul>" if notes else "<p class='none'>No specific notes from owner.</p>"

    return (
        template
        .replace("{{JOINER_NAME}}", args.joiner_name)
        .replace("{{JOINER_TITLE}}", args.joiner_title)
        .replace("{{JOINER_START_DATE}}", args.joiner_start_date)
        .replace("{{HIRING_MANAGER}}", args.hiring_manager)
        .replace("{{REQUISITION}}", args.requisition)
        .replace("{{GENERATED_AT}}", generated_at)
        .replace("{{PREHIRE_ROWS}}", _section(prehire_rows))
        .replace("{{PROVISIONING_ROWS}}", _section(provisioning_rows))
        .replace("{{WELCOME_ROWS}}", _section(welcome_rows))
        .replace("{{NOTES}}", notes_html)
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
    p.add_argument("--joiner-name", required=True)
    p.add_argument("--joiner-title", required=True)
    p.add_argument("--joiner-start-date", required=True)
    p.add_argument("--hiring-manager", required=True)
    p.add_argument("--requisition", required=True)
    p.add_argument("--status-json", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    try:
        status = json.loads(args.status_json)
    except json.JSONDecodeError as e:
        print(f"error: --status-json invalid: {e}", file=sys.stderr)
        return 2
    if not isinstance(status, dict):
        print("error: --status-json must be a JSON object", file=sys.stderr)
        return 2

    html = render_html(args, status)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        asyncio.run(html_to_pdf(html, out))
    except Exception as e:
        print(f"error: playwright PDF render failed: {e}", file=sys.stderr)
        html_out = out.with_suffix(".html")
        html_out.write_text(html)
        print(f"HTML fallback: {html_out}")
        return 1

    print(f"PDF: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
