"""Render the Olympus Health visit-prep pack PDF via Playwright.

Reads:
  --practitioner-name       e.g. "Dr. Aniyah Solomon"
  --practitioner-specialty  e.g. "Internal Medicine, Adult Primary Care"
  --clinic-date             ISO date "YYYY-MM-DD"
  --patients-json           JSON array of patient records (see SKILL.md for shape)
  --out                     Output PDF path

Writes the PDF to --out and prints the absolute path on stdout for the
file-sharing convention to pick up.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parent.parent / "assets" / "visit-prep-pack.html"


def _age_at(dob_iso: str, on: date) -> int:
    dob = date.fromisoformat(dob_iso)
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def _fmt_dob(dob_iso: str, on: date) -> str:
    dob = date.fromisoformat(dob_iso)
    return f"{dob.strftime('%-d %b %Y')} (age {_age_at(dob_iso, on)})"


def _time(iso: str) -> str:
    # accept "2026-06-02T10:00:00Z" or "2026-06-02T10:00:00"
    iso = iso.replace("Z", "")
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%H:%M")
    except Exception:
        return iso[11:16]


def _allergy_block(allergies: list[dict]) -> str:
    if not allergies:
        return '<div class="allergies none">Allergies: <em>none on file</em></div>'
    rows = []
    for a in allergies:
        sev = (a.get("severity") or "").lower()
        if sev in {"severe", "anaphylaxis", "life-threatening"}:
            icon = "🔴"
            cls = "severe"
        elif sev in {"moderate", "mild"}:
            icon = "⚠️"
            cls = "moderate"
        else:
            icon = "ℹ️"
            cls = "info"
        rows.append(
            f'<li class="allergy {cls}">{icon} <strong>{a.get("substance","?")}</strong> '
            f'— {a.get("severity","unknown")}'
            f'{" (" + a.get("reaction") + ")" if a.get("reaction") else ""}</li>'
        )
    return f'<ul class="allergies">{"".join(rows)}</ul>'


def _conditions_block(conditions: list[dict]) -> str:
    active = [c for c in conditions if (c.get("status") or "").lower() == "active"]
    if not active:
        return "<p><em>No active problems.</em></p>"
    rows = []
    for c in active:
        rows.append(
            f'<li><strong>{c.get("display","?")}</strong>'
            f'{" (" + c.get("code","") + ")" if c.get("code") else ""}'
            f'{" — since " + c.get("onset","") if c.get("onset") else ""}'
            "</li>"
        )
    return f'<ul class="problems">{"".join(rows)}</ul>'


def _meds_block(meds: list[dict]) -> str:
    if not meds:
        return "<p><em>No active medications.</em></p>"
    by_ind: dict[str, list[str]] = {}
    for m in meds:
        ind = m.get("indication") or "Other"
        line = f'{m.get("name","?")}'
        if m.get("since"):
            line += f' <span class="meta">since {m["since"]}</span>'
        by_ind.setdefault(ind, []).append(line)
    out = []
    for ind, lines in by_ind.items():
        out.append(f'<h4>{ind}</h4><ul>{"".join("<li>" + l + "</li>" for l in lines)}</ul>')
    return "".join(out)


def _obs_block(observations: list[dict]) -> str:
    if not observations:
        return "<p><em>No recent observations on file.</em></p>"
    rows = []
    for o in observations[:10]:
        interp = (o.get("interpretation") or "").lower()
        cls = "ooo" if any(k in interp for k in ("above", "below", "high", "low", "stage", "abnormal")) else ""
        rows.append(
            f"<tr class='{cls}'>"
            f"<td>{o.get('effective_at','?')[:10]}</td>"
            f"<td>{o.get('code','?')}</td>"
            f"<td class='num'>{o.get('value','?')} {o.get('unit','')}</td>"
            f"<td>{o.get('interpretation','')}</td>"
            f"</tr>"
        )
    return (
        "<table class='obs'><thead><tr><th>Date</th><th>Code</th><th>Value</th><th>Interpretation</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _focus_block(notes: list[str]) -> str:
    if not notes:
        return "<p><em>No specific focus notes — standard wellness review.</em></p>"
    return "<ol>" + "".join(f"<li>{n}</li>" for n in notes) + "</ol>"


def _roster_row(p: dict, on: date) -> str:
    patient = p.get("patient", {})
    enc = p.get("encounter", {})
    name = f"{patient.get('first_name','?')} {patient.get('last_name','?')}"
    dob = patient.get("date_of_birth", "")
    sev_allergies = [a for a in p.get("allergies", []) if (a.get("severity") or "").lower() in {"severe","anaphylaxis","life-threatening"}]
    badge = "🔴" if sev_allergies else ""
    return (
        f"<tr>"
        f"<td class='time'>{_time(enc.get('start',''))}</td>"
        f"<td><strong>{name}</strong> {badge}<br>"
        f"<span class='meta'>{patient.get('id','')} · {_fmt_dob(dob, on) if dob else '?'} · {patient.get('sex','')}</span></td>"
        f"<td>{enc.get('type','?')}<br><span class='meta'>{(enc.get('reason_text') or '—')}</span></td>"
        f"</tr>"
    )


def _patient_page(p: dict, on: date) -> str:
    patient = p.get("patient", {})
    enc = p.get("encounter", {})
    name = f"{patient.get('first_name','?')} {patient.get('last_name','?')}"
    dob = patient.get("date_of_birth", "")
    return (
        f"<section class='patient-page'>"
        f"<h2>{name} <span class='pid'>{patient.get('id','')} · {patient.get('mrn','')}</span></h2>"
        f"<p class='hdr-line'>"
        f"{patient.get('sex','?')} · {_fmt_dob(dob, on) if dob else '?'} · "
        f"{patient.get('insurer','?')} · "
        f"{patient.get('address_city','')}, {patient.get('address_state','')}"
        f"</p>"
        f"<div class='today'><strong>Today, {_time(enc.get('start',''))}:</strong> "
        f"{enc.get('type','?')} ({enc.get('duration_minutes','?')} min) — "
        f"<em>{enc.get('reason_text') or 'No specific reason text on file'}</em></div>"
        f"<h3>Allergies</h3>{_allergy_block(p.get('allergies', []))}"
        f"<h3>Active problems</h3>{_conditions_block(p.get('conditions', []))}"
        f"<h3>Active medications</h3>{_meds_block(p.get('medications', []))}"
        f"<h3>Recent labs &amp; vitals</h3>{_obs_block(p.get('observations', []))}"
        f"<h3>Suggested focus</h3>{_focus_block(p.get('focus_notes', []))}"
        f"</section>"
    )


def render_html(args: argparse.Namespace, patients: list[dict]) -> str:
    template = HTML_PATH.read_text()
    on = date.fromisoformat(args.clinic_date)
    clinic_date_human = on.strftime("%A %-d %B %Y")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    roster = "".join(_roster_row(p, on) for p in patients) or "<tr><td colspan='3'><em>No booked patients.</em></td></tr>"
    pages = "".join(_patient_page(p, on) for p in patients)
    callouts = []
    severe_count = sum(1 for p in patients for a in p.get("allergies", []) if (a.get("severity") or "").lower() in {"severe","anaphylaxis","life-threatening"})
    if severe_count:
        callouts.append(f"{severe_count} patient(s) today with severe / life-threatening allergies — flagged 🔴")
    ooo_count = sum(1 for p in patients for o in p.get("observations", []) if "above" in (o.get("interpretation") or "").lower() or "below" in (o.get("interpretation") or "").lower())
    if ooo_count:
        callouts.append(f"{ooo_count} recent out-of-range lab values across the panel — see per-patient pages")
    return (
        template
        .replace("{{PRACTITIONER_NAME}}", args.practitioner_name)
        .replace("{{PRACTITIONER_SPECIALTY}}", args.practitioner_specialty)
        .replace("{{CLINIC_DATE_HUMAN}}", clinic_date_human)
        .replace("{{CLINIC_DATE_ISO}}", args.clinic_date)
        .replace("{{GENERATED_AT}}", generated_at)
        .replace("{{PATIENT_COUNT}}", str(len(patients)))
        .replace("{{ROSTER_ROWS}}", roster)
        .replace("{{PATIENT_PAGES}}", pages)
        .replace("{{CALLOUTS}}", "".join(f"<li>{c}</li>" for c in callouts) or "<li>No critical callouts.</li>")
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
    p.add_argument("--practitioner-name", required=True)
    p.add_argument("--practitioner-specialty", required=True)
    p.add_argument("--clinic-date", required=True)
    p.add_argument("--patients-json", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    try:
        patients = json.loads(args.patients_json)
    except json.JSONDecodeError as e:
        print(f"error: --patients-json invalid: {e}", file=sys.stderr)
        return 2

    if not isinstance(patients, list):
        print("error: --patients-json must be a JSON array", file=sys.stderr)
        return 2

    html = render_html(args, patients)
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
