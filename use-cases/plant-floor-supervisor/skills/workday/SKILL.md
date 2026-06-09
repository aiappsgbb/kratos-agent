---
name: workday
description: Read the workday HCM surface — resolve `EMP-*` ids to people (display name, work email, manager, location, position), list direct reports, look up the org Frank reports into.
enabled: true
---

## Instructions

This is the **read interface** to `workday-mcp-server`. Use it whenever you have an `EMP-*` id and need a human name, an email address, a manager, or a location — and whenever Frank asks "who runs <X>?" or "who's Wes's boss?".

### Tool routing

| User intent | Tool |
|---|---|
| One employee with full detail (name, work_email, manager, location, position) | `workday_get_employee` |
| Find someone by name (e.g. "find Reggie Bellamy") | `workday_search_employees_by_name` |
| Who reports to Frank / Wes / anyone | `workday_list_employees_by_manager` |
| Position metadata | `workday_get_position` |
| Org chart context | `workday_get_organization`, `workday_list_organizations` |
| Today's shift roster — who's on Line 3? | `workday_list_shifts` |
| Who's OOO this week — coverage decisions | `workday_list_time_off` |

### Conventions

- **`work_email` is the canonical address** for any email Frank drafts. It matches `m365-graph` `mail` exactly.
- **Manager chain.** Frank's manager_id is `EMP-1031` (Wes). Wes's manager_id is `EMP-1030` (Beatrix Holloway, CPO) — for plant-ops escalation Wes is normally the ceiling; only escalate above on the rules in **plant-policy-reference** §4.
- **Plant cast.** Frank (`EMP-2201`) supervises Lucia (`EMP-2202`, Line 2) and Devon (`EMP-2203`, Line 3). Wes (`EMP-1031`) is the plant director. All four are based in Cleveland, OH.

### When NOT to use

- Looking up a vendor (V-*) — that's **sap-s4**
- Looking up a ticket-system user (USR-*) — that's **servicenow** (use `employee_id` to bridge)
- Reading someone's calendar / mail / OOO message → **m365-graph**
