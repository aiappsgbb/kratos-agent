---
name: m365-graph
description: Read the M365 surface for an onboarding flow — does the joiner have a mailbox yet, what's the manager's calendar look like for booking a day-1 1:1, has Beatrix already emailed the joiner. Read-only here — drafting/sending lives elsewhere.
enabled: true
---

## Instructions

This is the **read interface** to `m365-graph-mcp-server` for HR Onboarding. Use it to enrich onboarding briefings with mailbox + calendar context.

### Tool routing

| User intent | Tool |
|---|---|
| Does this joiner have an M365 user record yet? | `m365_get_user` |
| What's the manager's calendar on the joiner's first day? | `m365_list_events` with the manager's mailbox + the joiner's start date |
| Find a 30-min slot for the welcome 1:1 | `m365_find_meeting_times` |
| Has Beatrix already emailed the joiner / manager? | `m365_search_messages` |
| Read the full onboarding thread | `m365_get_thread` |

### Write tools live in this MCP but the HR persona doesn't own them

`m365_draft_message`, `m365_send_message`, `m365_create_event` are H-I-T-L write tools. **In this persona, surface the proposed action and let the user explicitly request it.** Drafting a welcome email or booking the welcome 1:1 is appropriate; auto-sending is not.

### Conventions

- The joiner's M365 `userPrincipalName` may not exist on day -7 — that's expected (IT provisioning hasn't run yet). Say so directly: *"No M365 user record yet — REQ-* for the kit is still In Progress."*
- The manager's calendar should be the source of truth for booking day-1 1:1 — don't suggest a slot without checking.

### When NOT to use

- Workday employee record → **workday**.
- IT provisioning ticket state → **servicenow**.
