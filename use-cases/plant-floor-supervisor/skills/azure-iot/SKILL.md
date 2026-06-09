---
name: azure-iot
description: Read the plant-floor Azure IoT surface — device twins (spindles, conveyors, robotic arms, vision systems), time-series telemetry with pre-annotated alarms, downtime events with cause codes and lot ids, and per-line OEE rollups (Availability × Performance × Quality).
enabled: true
---

## Instructions

This is the **read interface** to `azure-iot-mcp-server`. This is **where every Line-N investigation starts** — OEE tells you which line is missing target; downtime events tell you which device and why; telemetry tells you the underlying signal.

### Tool routing

| User intent | Tool |
|---|---|
| List the equipment on the floor (filter by plant, line, status) | `iot_list_devices` |
| One device with full detail (vendor/model/firmware, alarm thresholds, status_note) | `iot_get_device` |
| Pull time-series readings for a device (vibration, temp, load, RPM, etc.) with pre-annotated `alarms` array | `iot_get_telemetry` |
| List downtime events with cause codes (`VIB_ALARM`, `MATERIAL_HOLD_QA`, `CAL_DRIFT`, `PLANNED_MAINT`), lot ids, and `related_po_id` for cross-MCP joins | `iot_list_downtime_events` |
| Per-line per-day OEE with `vs_target_pct` and `flag` (`on_target` / `watch` / `investigate`) | `iot_get_oee` |

### Investigation workflow — the canonical pattern

The IoT story is **OEE → downtime → telemetry → device twin**. Walk that order; don't query everything up-front.

1. **`iot_get_oee(plant_id="P-CLE")`** → which line is `investigate`? Look at the 7-day trend, not just today.
2. **`iot_list_downtime_events(plant_id="P-CLE", line="<that line>", since="<yesterday>")`** → what stopped it? Read the `cause_code`, `lot_id`, `related_po_id`.
3. **`iot_get_device("<the device named in the events>")`** → is the device twin in `Warning` / `Degraded`? Read the `status_note`.
4. **`iot_get_telemetry("<device>", since="<window>")`** → confirm the signal. The `alarms` array on each reading already lists the breaches — **don't re-derive thresholds in your head**.
5. **Hand off** — if a downtime event has a `related_po_id` or a Northbridge-style lot id, pivot to **sap-s4**; if you need to log a maintenance ticket, pivot to **servicenow**.

### Conventions

- **The `alarms` array is the source of truth on threshold breaches.** Quote it: *"vibration crossed 4.5 mm/s at 22:00 — reading was 4.7"*. Don't compute it.
- **Plant ids match sap-s4 verbatim.** `P-CLE` here = `P-CLE` there. Lines too (`Line 3 — Precision` is the same string).
- **Device ids `DEV-*` map to servicenow CMDB `CI-DEV-*`** by numeric suffix. DEV-3001 → CI-DEV-3001. The servicenow CI's `owner_group` is `Plant Maintenance` — that's the assignment group for the work order.
- **OEE flag wording is fixed** (`on_target` / `watch` / `investigate`) — use those words; don't invent synonyms.
- **Time windows.** All timestamps are ISO-8601 with offset (Cleveland `-04:00`, Munich `+02:00`). When Frank says "last shift" assume the prior 8 h ending at the current time.

### Output

Prefer compact tables — one row per device, one row per downtime event, one row per day for OEE. Lead each row with the id, the metric, and the flag.

### When NOT to use

- Production orders / materials / vendors → **sap-s4**
- Logging a maintenance ticket against the device → **servicenow** (maintenance work order section)
- Charting the OEE trend / computing aggregates → **oee-analysis** (don't ask `code_interpreter` to retype numbers — pipe them through that skill)
