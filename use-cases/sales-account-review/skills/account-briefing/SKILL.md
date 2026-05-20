---
name: account-briefing
description: Produce a single-account briefing — snapshot, pipeline, contacts, recent activity, and risks — by stitching together multiple Salesforce tool calls
enabled: true
---

## Instructions

Use this skill when the user asks you to brief them on an account, prep them for a call, or summarise where things stand with a customer.

### 1. Resolve the account

- If the user gave a company name (not an id), call `salesforce_search_accounts_by_name` first.
- If multiple matches, ask the user to disambiguate.
- If exactly one match, use its `id` for the rest of the flow.

### 2. Gather the data (call in parallel where you can)

- `salesforce_get_account` → snapshot (tier, health, ARR, renewal, owner)
- `salesforce_list_opportunities` with `account_id` and `open_only: true` → pipeline
- `salesforce_list_contacts_by_account` → contact rolodex
- `salesforce_list_activities_by_account` with `limit: 5` → recent touches
- `salesforce_list_open_cases_by_account` → at-risk signals

### 3. Resolve user ids

Any `owner_user_id`, `csm_user_id`, `se_user_id` you plan to quote → resolve with `salesforce_get_user`. Never show raw `USR-xxx` ids to the user.

### 4. Format the response

```markdown
# {Account Name} — Briefing

## Snapshot
- **Tier**: Strategic · **Health**: 🟢 Green · **Industry**: Manufacturing
- **ARR committed**: $1,850,000 · **Renewal**: 2026-09-30
- **Owner**: Alex Rivera (AE) · **CSM**: Reese Patel · **SE**: Devon Park
- {one-line description}

## Pipeline (open)
| Opp | Stage | Amount | Close | Next step |
|---|---|---|---|---|
| OPP-1002 — Renewal FY26 | Proposal | $1,850,000 | 2026-09-30 | … |
| OPP-1001 — Analytics expansion | Negotiation | $420,000 | 2026-09-15 | … |

## Key contacts
- **Margaret Chen** — CFO (Economic Buyer, primary)
- **David Okafor** — VP Data & Analytics (Technical Buyer)
- **Priya Rao** — Director FP&A (Champion)

## Recent activity (last 5)
- 2026-05-18 · Call · Champion sync — Priya Rao confirmed CFO support
- 2026-05-14 · Email · Sent analytics proposal v2
- …

## Risks & opens
- {open cases, if any, with priority}
- {slipping close dates}
- {competitive flags from opportunity records}
- "No open risks." if nothing to flag.

## Suggested next steps
1. {concrete action tied to data, e.g. "Follow up on procurement red-lines — MSA sign target 6/15"}
2. …
```

## Constraints

- Lead with what matters — if the account is Red, surface that first, not the snapshot.
- Always include opportunity ids in parentheses when referencing them.
- Keep it on one screen — no preamble, no closing pleasantries.
