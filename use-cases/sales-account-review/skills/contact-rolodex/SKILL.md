---
name: contact-rolodex
description: Look up the contact map for an account — who's who, primary contact, roles (Economic Buyer / Champion / etc.)
enabled: true
---

## Instructions

Use this skill when the user asks "who are the contacts at X?", "who's the economic buyer at X?", or "who should I talk to about Y at X?".

### Tool to use

`salesforce_list_contacts_by_account` with `account_id`.

If the user gave a company name, resolve via `salesforce_search_accounts_by_name` first.

### Format

```markdown
# Contacts — {Account Name}

| Name | Title | Role | Primary | Email |
|---|---|---|---|---|
| Margaret Chen | CFO | Economic Buyer | ★ | m.chen@acme.example.com |
| David Okafor | VP, Data & Analytics | Technical Buyer | | d.okafor@acme.example.com |
| Priya Rao | Director, FP&A | Champion | | p.rao@acme.example.com |
```

Highlight the primary contact with a ★ in the Primary column.

### Targeted lookups

- **"Who's the economic buyer at X?"** → filter the result for `role == "Economic Buyer"` and lead with that one.
- **"Who's the champion at X?"** → same, for `role == "Champion"`.
- **"Who do I talk to about X?"** — pick by relevance:
  - Pricing / commercials → Economic Buyer
  - Integration / architecture → Technical Buyer
  - Day-to-day usage → End User
  - Internal selling → Champion

## Constraints

- Never expose contact phone numbers unless asked — emails are fine by default.
- If no contacts exist for the account, say so and suggest the AE add some.
