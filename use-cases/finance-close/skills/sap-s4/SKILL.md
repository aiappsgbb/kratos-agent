---
name: sap-s4
description: Read SAP S/4HANA finance data — cost centres, GL accounts, variance analysis, journal entries, vendors, plants, materials, production orders.
enabled: true
---

## Instructions

This is the **read interface** to `sap-s4-mcp-server`. Every cost centre, GL code, JE id, vendor id, plant, or material the user mentions must be resolved through one of these tools before you answer. Never fabricate financial data.

### Tool routing

| User intent | Tool |
|---|---|
| List cost centres (optionally by org / owner / status) | `sap_list_cost_centres` |
| One cost centre with full detail (budget, owner_user_id) | `sap_get_cost_centre` |
| List GL accounts (filter by type Asset / Liability / Revenue / COGS / OpEx / Other) | `sap_list_gl_accounts` |
| **Variance analysis for a period** — debit GL × cost-centre with `normal` / `watch` / `investigate` flags | `sap_get_variance_analysis` |
| List journal entries — by period, status, type | `sap_list_journal_entries` |
| One JE with full line detail (Dr/Cr/CC/memo) | `sap_get_journal_entry` |
| Find a vendor by name substring | `sap_search_vendors_by_name` |
| One vendor with credit / sanctions / block detail | `sap_get_vendor` |
| Plants / materials / production orders (manufacturing demos) | `sap_list_plants`, `sap_list_materials`, `sap_list_production_orders`, `sap_get_production_order` |

### Conventions

- **Always cite ids in parentheses.** `Platform Engineering (CC-0011)`, `Software & Subscriptions (GL 6400)`, `JE-30099`, `Sentinel Observability Inc (V-1102)`.
- **Read-only.** Writes (`sap_propose_journal_entry`, `sap_post_journal_entry`) live in the **journal-entry-proposal** skill — they are H-I-T-L gated.
- **Cross-MCP joins.** Cost-centre `owner_user_id` is a workday `EMP-*` id — hand off to the **workday** skill to resolve to a human name. Vendor invoice expected? Hand off to **m365-graph** `m365_search_messages` to see if AR has emailed about it.

### Output

Prefer compact tables with column headers; lead numeric columns with the currency or the unit (`$`, `%`, `qty`). Don't dump raw JSON — synthesise.

### When NOT to use

- Anything about people / org structure → **workday**
- Anything about email / calendar / files / chats → **m365-graph**
- Anything that mutates the ledger → **journal-entry-proposal** (it owns the propose+post pair)
