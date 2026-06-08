---
name: workday
description: Read Workday HCM data — employees, positions, orgs, manager hierarchy. Used to resolve cost-centre owners and to figure out who covers whom.
enabled: true
---

## Instructions

This is the **read interface** to `workday-mcp-server`. Use it whenever the agent needs to attach a human name + reporting line to an `EMP-*` id surfaced by sap-s4 or m365-graph.

### Tool routing

| User intent | Tool |
|---|---|
| Look up an employee by id | `workday_get_employee` |
| Search by name substring | `workday_search_employees_by_name` |
| Direct reports of a manager | `workday_list_employees` with `manager_id=` |
| Position / requisition detail | `workday_get_position`, `workday_list_positions` |
| Org-chart navigation | `workday_list_organizations`, `workday_get_organization` |
| Time-off (PTO / leave) — used to detect missing commentary owners | `workday_list_time_off` |

### Conventions

- **`EMP-*` ids are the join key.** Sap-s4 cost centres carry `owner_user_id`; m365-graph users carry `employee_id`. Both point here. Always cite as `Aisha Okonkwo (EMP-1011)`.
- **Status matters.** Employees can be `Active`, `On Leave`, `Terminated`, `Pre-Hire`. If a cost-centre owner is `On Leave`, surface that in the variance review so the controller knows commentary won't come from them this cycle (and hand off to **m365-graph** to read the OOO message and see who's covering).
- Read-only. Writes (create employee, approve time-off) are not used in finance-close demos.

### When NOT to use

- Anything about money / accounts / vendors → **sap-s4**
- Email / calendar context → **m365-graph**
