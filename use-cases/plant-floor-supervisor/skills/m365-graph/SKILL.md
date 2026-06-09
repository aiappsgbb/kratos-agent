---
name: m365-graph
description: Microsoft 365 surface — READ Frank's mailbox / Wes's calendar / OneDrive (shift reports, SOPs) AND a strict H-I-T-L workflow to draft and send an email (e.g. brief Wes on the morning incident).
enabled: true
---

## Instructions

This skill covers both reads and the email H-I-T-L. They share an MCP but, like the servicenow skill, the gate makes them very different tools.

## Section A — Reads (no confirmation needed)

| User intent | Tool |
|---|---|
| Resolve `EMP-*` ↔ display name ↔ email, presence, OOO | `m365_get_user`, `m365_get_user_presence` |
| List people in Plant Operations / under Wes | `m365_list_users` |
| Search Frank's mailbox (recent shift reports, supplier notes, QA threads) | `m365_search_messages` |
| Read one message in full | `m365_get_message` |
| Read a whole thread | `m365_get_thread` |
| What's on Wes's calendar — is he free for a quick brief? | `m365_list_events`, `m365_get_event` |
| Find a free 15-min slot for Frank + Wes + Lucia | `m365_find_meeting_times` |
| Search SharePoint / OneDrive (SOPs, OEE workbooks, supplier MSAs) | `m365_search_files`, `m365_get_file` |
| Frank's Teams chats with the shift / with Wes | `m365_list_chats`, `m365_search_chat_messages` |

### Read conventions

- The m365 user record carries `presence` and `ooo_message` — check these before suggesting "I'll email Wes" if Wes is OOO; cite the OOO message and propose the coverage person.
- Frank's `mail` is `frank.delgado@olympus.example.com`; Wes's is `wesley.park@olympus.example.com`. These match `workday.work_email` exactly.
- **Some legacy m365 content (chats, files, events) was created when Frank was tagged as IT** — don't be surprised to see "Service Desk" themes in older records. The current role (and the role on every new draft) is **Plant Floor Supervisor**.

## Section B — Email (H-I-T-L)

### Pattern — strict three-step

#### Step 1 — propose the draft

Build the email body from the situation. Lead with the metric; include the CI / INC / PO ids; keep it short. **Never** send unsolicited tone.

```
I'll draft this email to Wes:

- To:       Wesley Park (wesley.park@olympus.example.com)
- Cc:       (none)
- Subject:  Line 3 incident this morning — DEV-3001 spindle, INC-7012 logged
- Body:
    Wes,

    Two-hour update on Line 3:

    • OEE 49% vs target 80% — declining all week (81 → 49 across 7 days).
    • Spindle DEV-3001 vibration climbed 1.8 → 5.4 mm/s in the last 24h
      and crossed the 4.5 alarm. Four micro-stops (DT-3001..DT-3004).
    • PO-9003 is at 20% scrap on Model A. Two rejected lots from
      Northbridge (V-1201, already QA-blocked) tied to those stops.
    • Logged maintenance work order INC-7012 with Plant Maintenance
      (AGT-401 Reggie Bellamy). Brief is at /tmp/line-3-incident-brief-
      2026-06-09.pdf if you want the chart.

    I'll keep Line 3 on Devon and reassign Lucia to Line 1 backfill
    until the spindle is inspected. Calling QA on the Northbridge lots.

    Frank

Confirm to send? (yes / edit / no)
```

Then call `m365_draft_message` so the Draft id exists in the mailbox, and `ask_user`. **Wait.** Do not call `m365_send_message`.

#### Step 2 — execute on explicit "yes"

- **yes** → `m365_send_message` with the Draft id
- **edit body / edit subject / cc Aisha** → revise, re-confirm
- **no** → stop; the Draft stays in Drafts folder, won't send

#### Step 3 — receipt

```
Sent: MSG-30041 · to wesley.park@olympus.example.com · Subject: Line 3 incident this morning…
```

### Constraints

- **Never** call `m365_send_message` without an explicit `yes` after the rendered draft. No batching sends.
- **Never** send to external addresses (anything not `@olympus.example.com`) without surfacing that as a flag and re-confirming.
- **Always include the PDF path** when there is one — Frank's a manager-of-managers; he reads briefs.
- **Tone:** Frank's voice is direct and operational. No "I hope this email finds you well". Bullet → metric → action.

## Section C — When NOT to use

- Numbers / OEE / telemetry → **azure-iot** (no need to read it from email)
- Production order / vendor / material → **sap-s4**
- Logging a maintenance ticket → **servicenow** (maintenance work order section)
- Building the brief PDF that the email links to → **incident-brief-pdf**
