---
name: activity-timeline
description: Summarise recent activities (calls, meetings, emails) logged against an account
enabled: true
---

## Instructions

Use this skill when the user asks "what was our last touch with X?", "summarise recent activity on X", or wants context on where a conversation left off.

### Tool to use

`salesforce_list_activities_by_account` with `account_id` and optional `limit` (default 10).

If the user gave a company name, resolve via `salesforce_search_accounts_by_name` first.

### Format

Render newest-first as a compact timeline:

```markdown
# Recent activity — {Account Name}

- **2026-05-18 · Call** · Champion sync — Priya Rao  
  Confirmed CFO support; expects MSA sign by 6/15. *(Alex Rivera)*
- **2026-05-14 · Email** · Analytics proposal v2  
  Sent revised proposal with 3-yr pricing. Awaiting procurement red-lines. *(Alex Rivera)*
- **2026-05-08 · Meeting** · QBR with CFO + FP&A  
  CFO confirmed expansion budget approved. *(Alex Rivera)*
```

Resolve `owner_user_id` to a name via `salesforce_get_user` for each unique owner (cache the resolution within the response — don't call once per row).

### Targeted lookups

- **"Last touch with X"** → return only the most recent activity, formatted as a single bullet.
- **"What happened in the last 30 days with X?"** → fetch with `limit: 50`, filter client-side by date.

## Constraints

- Lead with the date, then the type, then the subject. The activity body comes second.
- Don't editorialise — the `summary` field is the source of truth; quote or paraphrase it tightly.
