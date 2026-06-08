---
name: onboarding-pack-pdf
description: Build the downloadable onboarding-pack PDF for a new joiner — cover with offer summary, day -7 → day 30 cadence with status per item (Workday Pre-Hire, IT REQ state, M365 mailbox, welcome 1:1 booked), and a manager checklist for week-1. Renders via the inline HTML template + Playwright.
enabled: true
---

## Instructions

Use this skill when the user (Beatrix) asks for "the onboarding pack", "the PDF", "print the packet for {joiner}", or any variation. This is the **deliverable** the persona exists to produce.

### Workflow

1. **Gather the data** by chaining other skills first:
   - Workday Pre-Hire record: `workday_get_employee` (or `workday_get_position` for the open position if the Pre-Hire isn't created yet)
   - Hiring manager: from the position's `hiring_manager_id` → `workday_get_employee`
   - IT REQ state: `servicenow_list_tickets` filtered by the joiner's name or REQ id
   - M365 mailbox: `m365_get_user(joiner_email)` — present or pending
   - Manager's day-0 calendar: `m365_list_events` to confirm the welcome 1:1 is booked
2. **Read the playbook** via the **people-playbook-reference** skill — the cadence in §1 is what the PDF must follow.
3. **Render** by invoking `scripts/render_onboarding_pack.py` via `code_interpreter`:

```bash
python /app/use-cases/hr-onboarding/skills/onboarding-pack-pdf/scripts/render_onboarding_pack.py \
  --joiner-name "Priya Subramaniam" \
  --joiner-title "Senior Site Reliability Engineer" \
  --joiner-start-date 2026-06-22 \
  --hiring-manager "Aisha Okonkwo (EMP-1011)" \
  --requisition "REQ-2009 · POS-2103" \
  --status-json '<JSON object — see below>' \
  --out /tmp/onboarding-pack-priya-subramaniam.pdf
```

4. **Confirm in chat**: "Onboarding pack saved to `/tmp/onboarding-pack-{joiner}.pdf` — N pages: cover, cadence with status, manager checklist." Reference the path so **file-sharing** picks it up.

### Status-JSON shape

The script expects:

```json
{
  "offer": { "countersigned_on": "2026-05-29", "background_check": "Cleared 2026-06-01" },
  "workday": { "state": "Pre-Hire created", "employee_id": "EMP-9001 (assigned day 1)", "salary_band_ok": true },
  "it_req": { "id": "REQ-2009", "state": "In Progress", "laptop_eta": "2026-06-20", "mailbox": "pending (target day -5)", "access_groups": ["eng-platform", "github-org", "vpn-corp"] },
  "m365": { "mailbox_provisioned": false, "welcome_1on1_booked": true, "welcome_1on1_when": "Mon 22 Jun 10:00 ET" },
  "checklist_owner_notes": ["Buddy not yet assigned — Aisha to nominate by day -3", "Welcome email from Beatrix queued for day -1"]
}
```

### Assets

- `assets/onboarding-pack.html` — clinical-cream theme (warm but professional). Cover + cadence table + checklist + manager-week-1 section.

### Constraints

- **Do not include salary or equity values in the PDF.** Per §9.2, the People specialist may know them but they don't belong on a document the manager / new joiner will see.
- **§1 cadence is the source of truth for section order.** Render in the day -14 → day 30 order from the playbook.
- File size budget < 2 MB.
- Do not auto-send by email. PDF only; mailing is a separate workflow.

### When NOT to use

- Status check on a single item (e.g. "is the laptop ETA on track?") — answer inline via **servicenow**.
- Workday Pre-Hire creation itself — that's **new-hire-onboarding** (the write skill).


<!-- skill-files -->
## Available Files

This skill directory contains the following files you can read with `read_file` using their absolute paths (prefix `/app/use-cases/hr-onboarding/skills/onboarding-pack-pdf/`):

- `assets/onboarding-pack.html`
- `scripts/render_onboarding_pack.py`
