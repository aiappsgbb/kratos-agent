---
name: opportunity-pipeline
description: List and filter opportunities — by rep, stage, account, or close window — to answer pipeline-review questions
enabled: true
---

## Instructions

Use this skill when the user asks about their pipeline, their open deals, what's closing this quarter, or which deals are stuck in a stage.

### Tool to use

`salesforce_list_opportunities` — supports filters:
- `account_id` — scope to one account
- `stage` — Prospecting | Qualification | Proposal | Negotiation | Closed Won | Closed Lost
- `owner_user_id` — scope to one rep
- `open_only` — exclude closed deals

### Common patterns

- **"My pipeline"** → first ask the user for their rep id (or remember it), then `owner_user_id` + `open_only: true`.
- **"Closing this quarter"** → `open_only: true`, then filter the result client-side by `close_date` against the current quarter window.
- **"Stuck in Negotiation"** → `stage: "Negotiation"`, sort by `created_date` ascending, flag any older than 60 days.
- **"All deals for {company}"** → resolve account first via `salesforce_search_accounts_by_name`, then filter by `account_id`.

### Format

Always render as a table sorted by close_date ascending:

| Opp | Account | Stage | Amount | Probability | Close | Next step |
|---|---|---|---|---|---|---|
| OPP-1002 | Acme Corp | Proposal | $1,850,000 | 90% | 2026-09-30 | … |

End with a summary line: "**{N} open opps, ${sum} weighted pipeline.**" Weighted = sum of amount × probability.

Resolve `owner_user_id` to a name via `salesforce_get_user` if you're going to show the owner column.

## Constraints

- Currency: `$1,850,000` format, no decimals for whole dollars.
- Probability: render as `90%` (multiply by 100, no decimals).
- If the result is empty, say so explicitly — don't pad with "nothing found, but here are some other things…".
