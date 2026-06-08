---
name: m365-graph
description: Read the controller's Microsoft 365 surface — mailbox (for chase emails, vendor invoices, variance commentary), calendar (close timeline, post-mortems, OOO blocks), OneDrive / SharePoint files (variance workbooks, MSAs, close pack templates), and Teams chats.
enabled: true
---

## Instructions

This is the **read interface** to `m365-graph-mcp-server`. Use it to find the *context* around a finance-close item: did the cost-centre owner already draft variance commentary? Is the vendor's expected invoice already in our inbox? Is the variance workbook updated? Who's OOO?

### Read tool routing

| User intent | Tool |
|---|---|
| Look up a user (resolve `EMP-*` ↔ email ↔ display name, presence, OOO) | `m365_get_user`, `m365_get_user_presence` |
| List users in a department or under a manager | `m365_list_users` |
| Search a mailbox for a topic / sender / date range / flag / category | `m365_search_messages` |
| Read one message in full | `m365_get_message` |
| Read a whole conversation thread | `m365_get_thread` |
| What's on someone's calendar between dates | `m365_list_events` |
| One event with the full attendee response list | `m365_get_event` |
| Find common free slots for N attendees | `m365_find_meeting_times` |
| Search SharePoint / OneDrive files by name / content / site | `m365_search_files` |
| One file's full metadata (sharedWith, content summary) | `m365_get_file` |
| List a user's Teams chats / search across them | `m365_list_chats`, `m365_search_chat_messages` |

### Write tools live in other skills

- `m365_draft_message` + `m365_send_message` are owned by the **variance-email** skill (H-I-T-L gated).
- `m365_create_event` (booking a meeting, e.g. variance review with Hiroshi) is also gated — show the proposed invite and wait for explicit confirmation before calling.

### Cross-MCP recipe — find the commentary owner

When sap-s4 surfaces a cost-centre that needs investigate-level commentary:

1. `sap_get_cost_centre` → `owner_user_id` (an EMP-* id)
2. `workday_get_employee` → display name + email
3. `m365_get_user_presence` → are they OOO? If yes, read the OOO message for coverage
4. `m365_search_messages` mailbox=that-EMP, category="finance-close" or query=cost-centre-name → has variance commentary already been drafted?
5. `m365_get_thread` on the parent conversation → see the whole exchange so the controller doesn't ask twice

### When NOT to use

- Numbers / GL / JE / vendor → **sap-s4**
- Org structure / who reports to whom → **workday**
- Sending mail → **variance-email** (it owns the propose+confirm+send pair)
