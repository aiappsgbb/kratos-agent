---
name: servicenow
description: ServiceNow surface — READ existing tickets/CMDB/KB/agents for plant-floor context AND a strict H-I-T-L workflow to log a maintenance work order against a piece of equipment.
enabled: true
---

## Instructions

This skill covers both reads and the **one** write workflow Frank uses on ServiceNow — logging a maintenance work order. They share an MCP but the H-I-T-L gate makes them very different tools.

## Section A — Reads (no confirmation needed)

| User intent | Tool |
|---|---|
| Open tickets on Frank's plant (Wi-Fi, equipment, network — anything `Cleveland` flagged) | `servicenow_list_tickets` with `assignment_group` or substring on title |
| One ticket with current state, assignment, callouts | `servicenow_get_ticket` |
| The work-note thread (audit trail) on a ticket | `servicenow_list_work_notes` |
| Resolve a CI to its owner_group (e.g. `CI-DEV-3001` → Plant Maintenance) | `servicenow_get_ci` |
| Find an agent (e.g. who's on shift in Plant Maintenance) | `servicenow_get_user` / `servicenow_search_users_by_name` |
| Knowledge base — vendor lockout procedure, spindle recalibration runbook | `servicenow_search_kb`, `servicenow_get_kb_article` |

### Read conventions

- Cite ids in parentheses: `INC-7004`, `CI-DEV-3001`, `AGT-401`.
- **Pre-existing context Frank already has open:** `INC-7004` — Cleveland Plant Line 3 Wi-Fi scanners (caller `USR-2201` = Frank). Mention it if it's relevant to the question.
- ServiceNow `USR-*` ids carry an `employee_id` that bridges back to workday's `EMP-*`. Use it to merge identities cleanly.

## Section B — Maintenance work order (H-I-T-L)

This is the **only** write tool Frank uses here. The intent is conceptually a **maintenance work order** even though the underlying call is `servicenow_create_incident` with `category="Maintenance"` — Olympus runs CMMS through the ServiceNow incident table.

### Pattern — strict three-step

#### Step 1 — gather

Before drafting, fetch from other skills:
- `azure-iot` `iot_get_device(...)` — equipment id, last alarm, status_note (becomes the description)
- `azure-iot` `iot_list_downtime_events(...)` — recent stops (the "evidence")
- `servicenow` `servicenow_get_ci("CI-DEV-<n>")` — confirms `owner_group` (assignment_group will be `Plant Maintenance`)
- `workday` `workday_get_employee("EMP-2201")` — Frank's record (caller info)

#### Step 2 — draft + ask

Render the proposed work order:

```
I'll log this maintenance work order:

- Caller:            Frank Delgado (USR-2201)
- Equipment (CI):    CI-DEV-3001 — Cleveland Plant — Line 3 Precision Spindle
- Title:             Vibration alarm + 4 micro-stops on Line 3 spindle (DEV-3001)
- Category:          Maintenance · Equipment
- Priority:          P2 — line is at 49% OEE, target 80%; >5 units/hour lost
- Assignment group:  Plant Maintenance (AGT-401 Reggie Bellamy on shift)
- CI status:         Degraded
- Description:
    Spindle vibration_rms_mm_s has been climbing for ~24h; crossed the
    4.5 mm/s alarm threshold around 22:00 yesterday and is now reading
    5.4 mm/s. Four micro-stops in the last 24h (DT-3001..DT-3004), two
    with rejected lots from Northbridge (V-1201, currently QA-blocked).
    Production order PO-9003 is at 20% scrap.
    Recommend: stop spindle for inspection, swap bearings, recalibrate.

Confirm to create? (yes / edit / no)
```

Use `ask_user`. **Wait.** Do not call `servicenow_create_incident`.

#### Step 3 — execute on explicit "yes"

- **yes** → `servicenow_create_incident` with the exact fields shown
- **edit X** → gather the correction, re-render the draft, re-confirm
- **no** → stop; acknowledge that nothing was created

#### Step 4 — receipt

```
Created: INC-7012 · CI-DEV-3001 · assigned Plant Maintenance (AGT-401 Reggie Bellamy)
```

Then offer the natural next step: *"Want me to draft Wes the cover email referencing INC-7012?"* — handoff to **m365-graph** email section.

### Constraints

- **Never** call `servicenow_create_incident` without an explicit `yes` after the rendered draft. No batching writes.
- **Always set `caller_id`** to `USR-2201` (Frank) when Frank is the originator.
- **Always set `assignment_group`** by looking up the CI's `owner_group` — don't guess.
- **Priority guide:** `P1` if line down + safety; `P2` if line below target with throughput loss; `P3` if monitoring; `P4` if cosmetic/planned.
- After creating, set a work note via `servicenow_add_work_note` only if Frank explicitly asks (separate confirmation).

## Section C — When NOT to use

- Sensor / OEE / device telemetry → **azure-iot** (not the CMDB)
- Production-order details / scrap rates / vendor QA blocks → **sap-s4**
- Drafting an email about the work order → **m365-graph** (email section)
- "Why is Wes's calendar full?" → **m365-graph** (read section)
