---
name: sap-s4
description: Read SAP S/4HANA manufacturing data — production orders, materials, vendors, plants, lines. Pivot here once the IoT signal names a `related_po_id` to find the order, the material, and the (possibly QA-blocked) vendor.
enabled: true
---

## Instructions

This is the **read interface** to `sap-s4-mcp-server` for plant-floor work. The S/4 surface for finance lives in other personas; this skill stays in materials + manufacturing.

Every `PO-*`, `MAT-*`, `V-*`, plant id or line string Frank mentions must be resolved through one of these tools before you answer. **Never fabricate production data.**

### Tool routing

| User intent | Tool |
|---|---|
| List plants / which lines does Cleveland run | `sap_list_plants` |
| List production orders (filter by plant, line, status) | `sap_list_production_orders` |
| One production order with full detail (qty_ordered / produced / scrap, status, issue text, vendor blame) | `sap_get_production_order` |
| Materials master — what is MAT-201, what's its stock, who's the preferred vendor | `sap_list_materials` |
| Find a vendor by name | `sap_search_vendors_by_name` |
| One vendor with the **quality-block** signal (`blocked_for_posting`, `block_reason`) — this is the headline for the Northbridge story | `sap_get_vendor` |

### Conventions

- **Always cite ids in parentheses.** `Cleveland Line 3 — Precision (P-CLE)`, `Model A (MAT-201)`, `PO-9003`, `Northbridge (V-1201)`.
- **Read-only.** This persona doesn't post journal entries or material movements. If Frank ever asks to "release the PO" or "post receipt", refuse politely and offer to log a maintenance / quality work order via `servicenow` instead.
- **Cross-MCP joins.**
  - A `production_order.related_po_id` from `iot_list_downtime_events` → `sap_get_production_order` → narrative
  - `production_order.issue` text that names a vendor → `sap_search_vendors_by_name` → `sap_get_vendor` → check `blocked_for_posting` / `block_reason`
  - A `material.preferred_vendor` → `sap_get_vendor` → the same QA-block check

### Output

Lead with the metric Frank cares about — `produced 120 / 150 · scrap 20% · status Issue` — and then the cause if you have it. Don't dump raw JSON.

### When NOT to use

- Devices, telemetry, downtime, OEE → **azure-iot**
- Who reports to whom / who is the QA director → **workday**
- Logging a maintenance work order → **servicenow** (maintenance work order section)
- Emailing the manager → **m365-graph** (email section)
