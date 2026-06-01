---
name: time-off-approvals
description: List and decide on pending PTO requests with explicit confirmation before approving or denying
enabled: true
---

## Instructions

Use this skill when the user asks about time-off requests they need to approve, wants to action a specific request, or asks "what's pending for me?" (e.g. "What PTO is pending my approval?", "Approve Maya's request and tell her yes", "Deny Theo's July vacation — we have a release that week").

This skill includes a **write tool** (`workday_approve_time_off_request`). Follow the confirmation pattern strictly.

### 1. Find the request(s)

- *"What's pending for me?"* → ask for the user's employee id if not in context, then `workday_list_time_off` with `approver_id=<user>` and `status: "Pending"`
- *"Approve {name}'s request"* → `workday_search_employees_by_name` → `workday_list_time_off` with `employee_id=<found>` and `status: "Pending"`
- *"What's the status of PTO-xxxx?"* → `workday_list_time_off` and filter by id, or read straight from a prior result

### 2. Show the draft decision

Before approving or denying, show the user exactly what you'll do:

```
I'll approve PTO request PTO-3003:

- Employee:  Theo Nakamura (EMP-2001) — Senior Platform Engineer
- Type:      Vacation
- Dates:     14 Jul 2026 → 18 Jul 2026 (5 working days)
- Reason:    Wedding
- Submitted: 28 May 2026

Confirm to approve? (yes / deny / cancel)
```

Use `ask_user` to pause for the user's response. Wait.

### 3. Handle the response

- **yes / approve** → `workday_approve_time_off_request` with `decision: "Approved"` and an optional `note` if the user gave one
- **deny / no** → re-confirm explicitly (denial is consequential), then call with `decision: "Denied"`. Ask for a note that will be shown to the employee.
- **cancel** → stop and acknowledge

### 4. Report the result

After the write succeeds, confirm:

- The decision was recorded
- The employee will be notified through their usual Workday channel
- Offer the next step: *"Want me to draft a personal note to Theo to give him the heads-up?"*

### Constraints

- Never call `workday_approve_time_off_request` without explicit confirmation in the same turn.
- If a request is not in Pending status, surface the existing status and stop — don't attempt to flip an already-decided request.
- Format dates as `14 Jul 2026` for the user but ISO (`2026-07-14`) in tool calls.
- For batch approvals (*"approve everyone's pending requests"*), confirm each one individually rather than batching the writes silently.
