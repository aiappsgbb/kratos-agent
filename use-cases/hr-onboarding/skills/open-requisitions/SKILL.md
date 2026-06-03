---
name: open-requisitions
description: List, filter, and assess open positions across the company — by org, manager, or how stale they are
enabled: true
---

## Instructions

Use this skill when the user asks about open requisitions, hiring pipeline, or wants to know which roles are slipping (e.g. "Show me all open reqs in Engineering", "Which positions have been open longest?", "What's the bench look like in Cleveland?").

### Tool to use

`workday_list_positions` with `status: "Open"`, plus optional filters:

- `org_id` — scope to one org (find via `workday_list_organizations`)
- `hiring_manager_id` — scope to one manager

### Format

Render as a table sorted by `open_since` ascending (oldest first):

| Position | Org | Level | Hiring manager | Open since | Days open | Target start |
|---|---|---|---|---|---|---|
| Staff Platform Engineer (POS-2004) | Platform Engineering | IC5 | Aisha Okonkwo | 12 Apr 2026 | 51 | 30 Jun 2026 |
| Solutions Engineer (POS-2103) | Field Sales — Americas | IC3 | Hiro Tanaka | 1 May 2026 | 32 | 15 Jun 2026 |

Resolve `org_id` to org name and `hiring_manager_id` to manager name (call `workday_get_organization` / `workday_get_employee`). Days open = days between `open_since` and today.

End with a summary line:

> **N open reqs, X slipping (>30 days open without filling).**

### Targeted patterns

- **"What's slipping?"** → filter the result client-side to `days open > 30` and lead with those
- **"Show me reqs in {org}"** → resolve org first, then filter
- **"Whose reqs are oldest?"** → group by hiring manager, sort each group by `open_since`

## Constraints

- Currency-free skill — no salary or budget data here, only counts and dates.
- If the result is empty, say so explicitly (e.g. *"No open requisitions in that org — well done."*).
- Always include the position id in parentheses.
