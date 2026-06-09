---
name: servicenow
description: Read the IT-provisioning ticket(s) backing a new-joiner's onboarding — laptop kit, account creation, access groups. Used to surface "is IT ready for Priya's first day?"
enabled: true
---

## Instructions

This is the **read interface** to `servicenow-mcp-server` for HR Onboarding. Use it when you need to know the IT side of a joiner's setup: is the laptop ordered, is the M365 mailbox provisioned, are the Entra access groups assigned.

### Tool routing

| User intent | Tool |
|---|---|
| "Is there an IT ticket for {joiner}?" | `servicenow_list_tickets` with `assignment_group: "IT Provisioning"` + caller filter |
| One ticket in detail (state, last note, ETA) | `servicenow_get_ticket` |
| Conversation history on a REQ | `servicenow_list_work_notes` |
| Resolve a USR-* to a person | `servicenow_get_user` (look at `employee_id` to thread back to workday `EMP-*`) |

### Conventions

- REQ-* prefix for service requests (provisioning), INC-* for incidents.
- IT-Provisioning REQs typically have the manager or HR specialist as `caller_id`, not the new joiner (the joiner doesn't have an account yet on day 1).
- Surface ticket state as: `New / In Progress / Awaiting User / On Hold / Resolved / Closed`. Anything not Resolved/Closed is "still outstanding" for onboarding readiness purposes.

### When NOT to use

- Anything touching the employee record itself → **workday**.
- Welcome mail / calendar / OOO → **m365-graph**.
- Triaging or acting on a non-onboarding IT ticket — that's the `it-service-desk` persona, not us.
