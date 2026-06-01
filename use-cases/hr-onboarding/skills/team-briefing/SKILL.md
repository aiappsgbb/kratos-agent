---
name: team-briefing
description: Brief a manager on their team — direct reports, who's on leave, upcoming time-off, open requisitions
enabled: true
---

## Instructions

Use this skill when the user asks for a briefing on a manager's team, the state of an org unit, or wants to plan against team availability (e.g. "Brief me on Aisha's team", "What's the bench look like in Engineering?", "Who's out next month on the plant floor?").

### 1. Resolve the manager / org

- If the user gave a name → `workday_search_employees_by_name` then `workday_get_employee`
- If the user named an org (e.g. "Platform Engineering") → `workday_list_organizations` to find the id, then `workday_get_organization`

### 2. Pull the data (call in parallel where possible)

- `workday_list_employees_by_manager` with `manager_id` — direct reports
- `workday_list_time_off` with `approver_id=<manager>` — pending and recent requests they own
- `workday_list_positions` with `hiring_manager_id=<manager>` and `status: "Open"` — open reqs
- `workday_get_organization` for the cost-centre context

### 3. Format the briefing

```markdown
# {Manager Name} — Team Briefing

## Snapshot
- **Org**: Platform Engineering (ORG-011) · cost centre CC-0011
- **Manager**: Aisha Okonkwo (EMP-1011) — VP Platform Engineering
- **Direct reports**: 3 active, 1 on leave

## Team
| Employee | Title | Location | Status |
|---|---|---|---|
| Theo Nakamura (EMP-2001) | Senior Platform Engineer | San Francisco, CA | Active |
| Elena Morales (EMP-2002) | Senior Platform Engineer | Remote — Austin, TX | Active |
| Owen Brennan (EMP-2003) | Platform Engineer | San Francisco, CA | **On Leave** (returns 9 Aug) |

## Open requisitions
| Position | Level | Open since | Target start |
|---|---|---|---|
| Staff Platform Engineer (POS-2004) | IC5 | 12 Apr 2026 (51 days) | 30 Jun 2026 |

## Time off
| Employee | Type | Dates | Status |
|---|---|---|---|
| Theo Nakamura | Vacation | 14–18 Jul | **Pending** |
| Elena Morales | Vacation | 23 Jun – 3 Jul | Approved |
| Owen Brennan | Parental Leave | 10 May – 9 Aug | Approved |

## Watch-outs
- POS-2004 is slipping its target start by **15+ days** — flag if no shortlist yet
- Theo's PTO is pending your approval since 28 May
```

Always resolve `EMP-*` and `POS-*` ids to names/titles in the rendered table. Leave the ids in parentheses for traceability.

### Targeted variants

- **"Who's out next month?"** → focus on the time-off table, filter to date range, skip the open-reqs section
- **"What's slipping?"** → focus on open requisitions where `open_since` > 30 days ago
- **"Is this manager overloaded?"** → count direct reports + open reqs + pending approvals and surface as a single line

## Constraints

- Don't expose salaries unless the user explicitly asks.
- Order time-off chronologically by start_date.
- Open requisitions ordered by `open_since` ascending (oldest first).
- If the manager has zero direct reports, say so explicitly and suggest org-chart navigation as the next step.
