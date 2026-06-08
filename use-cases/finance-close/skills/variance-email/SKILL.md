---
name: variance-email
description: Draft variance commentary / accrual notice as an Outlook email and send only after explicit user confirmation. Uses `m365_draft_message` then `m365_send_message`.
enabled: true
---

## Instructions

Use this skill whenever the user asks you to email Hiroshi/Sofia/an owner about a variance, accrual, or close-pack item. Like the JE write workflow, this is two-step (Draft → confirm → Send).

### Pattern

#### Step 1 — gather the recipient

Resolve the recipient from a name to a mail address:

- `Hiroshi` → `workday_search_employees_by_name` → `work_email`, or
- `the CC-0011 owner` → `sap_get_cost_centre` → `owner_user_id` → `workday_get_employee` → `work_email`

If the recipient is OOO, surface that via `m365_get_user_presence`, read the OOO message for coverage, and ask the user whether to re-route.

#### Step 2 — draft (creates Draft in sender's Drafts folder)

Build a complete draft including:

- Clear subject (`May close — CC-0011 variance commentary` / `Accrual posted: JE-39001 Sentinel June licence`)
- Greeting + one-paragraph context (cost centre, period, amount)
- The numeric body — *cite GL codes and JE ids* exactly as they came back from sap-s4
- One sentence on next step / action requested
- Sign-off as the controller (the user)

Then call `m365_draft_message` with `from=<controller's EMP id>`. The Draft id comes back as `MSG-39XXX`.

#### Step 3 — show the Draft + ask to send

Render the Draft in chat (`From`, `To`, `Cc`, `Subject`, body). Use `ask_user`. **Wait.**

#### Step 4 — execute on explicit "yes"

- **yes** → `m365_send_message` with the Draft id
- **edit X** → re-draft with the correction, re-show, re-confirm
- **no** → stop; the Draft stays in Drafts folder

#### Step 5 — report the receipt

After Send succeeds:

```
Sent: MSG-39001 · "May close — CC-0011 variance commentary" · to hiroshi.tanaka@olympus.example.com
```

### Common templates

- **Variance commentary reply** — answers the chase from Hiroshi. Reference the cost centre, gives driver/outlook/action per close policy §5.2, mentions any planned accrual.
- **Accrual notice** — informs Hiroshi (and optionally Sofia) of a posted accrual, cites JE id, vendor, amount, evidence reference per §2.3.
- **Close pack cover** — sends the generated PDF (the agent says "PDF attached" but in this mock there's no actual attachment; the controller sends the PDF separately).

### Constraints

- **Never** call `m365_send_message` without explicit `yes` in the turn after showing the Draft.
- **Never** send mail to a sanctioned vendor or a blocked counterparty (cross-check with `sap_get_vendor` when relevant).
- Mailing list addresses are fine for FYIs; one-to-one for actions.
- Always include the conversation context — if you can find the parent thread via `m365_get_thread`, set `reply_to_message_id` so the reply threads properly.

### Cross-skill handoffs

- After **journal-entry-proposal** Posts a JE, this skill drafts the natural notice email.
- After **close-pack-pdf** renders, this skill drafts the cover email to Sofia.
