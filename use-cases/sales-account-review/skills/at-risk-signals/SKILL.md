---
name: at-risk-signals
description: Identify accounts that need attention — Red health, slipping renewals, open P1 cases, competitive losses
enabled: true
---

## Instructions

Use this skill when the user asks "which of my accounts are at risk?", "what should I worry about?", or "show me the red accounts".

### Strategy

This is a **multi-tool, multi-account** skill. You'll need to:

1. **Scope to the user's book**: ask for their `owner_user_id` if not already in context.
2. **Pull their accounts**: `salesforce_list_accounts` with `owner_user_id`.
3. **For each account, gather risk signals in parallel**:
   - The account record itself → health (Red / Yellow), renewal_date (within 90 days?)
   - `salesforce_list_open_cases_by_account` → any P1 cases?
   - `salesforce_list_opportunities` with `account_id` + `open_only: true` → renewal opp with low probability? close_date slipping?
4. **Score**:
   - **P0 (call today)**: Red health AND (open P1 OR renewal in <30 days with prob <50%)
   - **P1 (this week)**: Red health, OR open P1 case, OR renewal in <60 days with prob <70%
   - **P2 (this month)**: Yellow health with renewal in <120 days
   - Anything else: not flagged.

### Format

```markdown
# At-risk accounts — {AE name}'s book

## 🔴 Call today
- **Initech Software** (ACC-003) — Red health, 2 open P1s, renewal in 31 days at 25% probability  
  → CSM joint save call already on calendar 5/22. Confirm attendance.

## 🟡 This week
- **Globex Industries** (ACC-002) — Yellow health, new VP Eng starts 5/27, renewal in 56 days at 65%  
  → Schedule intro with Sara Lindqvist week of 6/02.

## 🟠 This month
- {…}

## ✅ All other accounts: healthy
```

### When to fail loudly

- If `owner_user_id` returns zero accounts, say so directly. Don't invent risk.
- If everything is green and healthy, say "No at-risk accounts in your book right now." — don't manufacture concern.

## Constraints

- Always include the account id in parens.
- The recommendation line (`→ …`) should be concrete and tied to data the tools returned — not generic advice.
- Order strictly: P0 → P1 → P2 → "all healthy".
