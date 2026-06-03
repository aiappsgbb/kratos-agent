---
name: new-hire-onboarding
description: Drive the new-hire onboarding workflow — find the right open position, draft the pre-hire record, confirm with the user, and create the Workday employee
enabled: true
---

## Instructions

Use this skill whenever the user asks to onboard, hire, or start the new-joiner process for someone (e.g. "Onboard Sarah Park starting Monday", "Hire a new SE for Aisha's team", "Set up a new contractor in London").

This is a **multi-step write workflow**. Follow the steps in order and confirm with the user before any tool that mutates Workday.

### 1. Gather the basics

You need:

- **Name** (first + last, plus preferred name if different)
- **Role / position** — either a position id (e.g. `POS-2004`) or a job title + hiring manager so you can find one
- **Hiring manager** — name or employee id
- **Hire date** — ISO date the employee starts
- **Location** — work location (e.g. `Remote — Seattle, WA` or `San Francisco, CA`)
- **Personal email** — required for pre-hire outreach
- **Salary** — annual USD figure (the manager / People partner usually has this)

If the user only gave a job title and a manager, **find the open position first**:

1. Resolve the manager name via `workday_search_employees_by_name` → `workday_get_employee`
2. Call `workday_list_positions` with `hiring_manager_id` and `status: "Open"`
3. If exactly one match, propose it; if multiple, list them and ask the user which

If anything is missing, **ask the user once** with a clear list of what you still need.

### 2. Draft the pre-hire record

Show the user a draft of exactly what you'll create. Format:

```
I'll create a Pre-Hire record in Workday with these details:

- Name:           Sarah Park
- Position:       Staff Platform Engineer (POS-2004) — IC5, Platform Engineering
- Manager:        Aisha Okonkwo (EMP-1011)
- Hire date:      15 June 2026
- Location:       Remote — Seattle, WA
- Personal email: sarah.park@example.com
- Annual salary:  $215,000

This will mark POS-2004 as Filled and start Sarah's pre-hire record.
Confirm to proceed? (yes / no / adjust)
```

Then use `ask_user` to pause for confirmation. Wait for the response.

### 3. Handle the response

- **yes / confirm / go** → call `workday_create_employee` with the exact values shown
- **adjust / change X** → gather the correction, re-show the draft, re-confirm
- **no / cancel** → stop. Acknowledge and ask if there's anything else

### 4. Report the result

After the write succeeds:

- Confirm the new employee id (e.g. `EMP-9001`) and that the position is now Filled
- Surface their work_email (`sarah.park@olympus.example.com`) — this is what IT will provision against
- Propose next steps the user might want, framed as questions they can answer:
  - *"Would you like me to draft a welcome email to send to Sarah's personal address?"*
  - *"Should I generate the onboarding checklist PDF for the People team and the manager?"*
  - *"Want me to brief you on Aisha's existing team so you can introduce Sarah in context?"*

### 5. If the write fails

The tool returns `error: "position_not_open"` or `not_found` errors. Surface the error verbatim, explain in plain English (e.g. *"That position is already filled by Theo Nakamura — did you mean POS-2103 instead?"*), and walk back to step 1 or 2 as appropriate.

## Constraints

- Never call `workday_create_employee` without explicit user confirmation in the same turn.
- Currency is USD unless the user says otherwise; show it as `$215,000`, no decimals.
- Dates: ISO in tool calls (`2026-06-15`), human-readable in messages (`15 June 2026`).
- If the user gave only a first name, ask for the last name rather than guessing.
