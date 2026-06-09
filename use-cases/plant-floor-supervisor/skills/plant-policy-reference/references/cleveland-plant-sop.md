# Olympus Industries — Cleveland Plant Standard Operating Procedure

**Document:** CLE-PLANT-SOP v3.4
**Effective:** 2025-09-15
**Owner:** Wesley Park, Director Plant Operations
**Applies to:** Plant Floor Supervisors, Production Line Operators, Plant Maintenance Group, QA Cleveland

---

## §1 OEE definitions & targets

### §1.1 The OEE identity

Overall Equipment Effectiveness for a line on a shift is:

> **OEE = Availability × Performance × Quality**

each as a fraction 0–1, reported as a percent.

- **Availability** = `run_time / planned_production_time`. Planned downtime (changeovers, scheduled maintenance) is excluded from the denominator.
- **Performance** = `(ideal_cycle_time × total_count) / run_time`. Captures micro-stops and slowdowns.
- **Quality** = `good_count / total_count`. Captures scrap and rework.

### §1.2 Loss accounting — single-count rule

Each loss is counted **once and only once**. A downtime event (e.g. spindle vibration alarm) is an Availability loss; the scrap it produces while limping is a Quality loss. Downtime that creates scrap does **not** double-count: the run-time during the alarm is already zero in the Availability term, so the scrap-during-alarm contributes only to Quality.

### §1.3 Targets

| Line | Target OEE | Watch zone | Investigate zone |
|---|---|---|---|
| All Cleveland lines | **80%** | 75-80% (`vs_target ≥ -5`) | <75% (`vs_target < -5`) |
| All Munich lines | **75%** | 70-75% | <70% |

`iot_get_oee` returns these as `flag` (`on_target` / `watch` / `investigate`) and `vs_target_pct` — use those values, don't recompute the bucket.

### §1.4 OEE windows

Shift OEE is computed over 8h; daily OEE is the rolled-up sum of three shifts. Use **daily** for trend analysis (the >24h question); use **shift** for hour-by-hour drill-in.

---

## §2 Alarm thresholds by equipment class

Threshold values are set in each device twin's `alarm_thresholds`. They are not policy values themselves — policy is **what to do when the threshold is crossed**. The configured numbers are the engineering tolerance baked in by the vendor; supervisors do not adjust them.

### §2.1 Precision spindles (e.g. Siemens SINAMICS S210 on Line 3)

- `vibration_rms_mm_s ≥ 4.5` — **VIB_ALARM**. Stop the spindle within one cycle; do not push through. A reading climbing toward 4.5 over hours (>0.3 mm/s gain) is **§4.3 watch-list material** — Frank must log it in the shift notes even before it breaches.
- `spindle_temp_c ≥ 70` — thermal alarm; pair with vibration for early-bearing-wear signal.
- `load_pct ≥ 95` — sustained overload; cycle-time miss likely.

### §2.2 Robotic arms (Lines 1 & 2)

- `motor_temp_c ≥ 75` — thermal alarm; pause for 10-min cool-down.
- `cycle_time_s > 1.15× nominal` for >10 cycles — drift; recalibrate.

### §2.3 Conveyors

- `motor_temp_c ≥ 65`; `speed_m_per_min < 0.8× nominal` — drive or belt slip.

### §2.4 Vision inspection (e.g. Line 2)

- `false_reject_pct ≥ 4.0%` — calibration drift, **CAL_DRIFT** cause code. Recalibrate against the gold reference set within the shift; if still >4% after recal, escalate per §4.

### §2.5 Induction furnaces (Munich)

- `bath_temp_c` outside 1400–1450 °C; `coolant_flow_l_min < 80`. Safety-critical — line stops automatically; supervisor logs the brief.

---

## §3 Downtime cause-code taxonomy

When a downtime event is captured by `azure-iot-mcp-server`, the supervisor (or the auto-tagger) sets one of these `cause_code` values. Custom strings are not allowed — pick the closest match.

| Code | Meaning | Typical follow-up |
|---|---|---|
| `VIB_ALARM` | Vibration threshold breached | §6 maintenance work order; spindle bearings prime suspect |
| `MATERIAL_HOLD_QA` | Lot rejected by QA on the line — bad material | Quarantine lot, notify QA; if vendor pattern, §5 |
| `CAL_DRIFT` | Sensor / vision system out of calibration | Recalibrate; if recurring, §6 maintenance |
| `PLANNED_MAINT` | Scheduled downtime (changeover, PM) | Excluded from Availability denominator |
| `OPERATOR_PAUSE` | Operator deliberately paused (safety check, bathroom break) | No follow-up |
| `MATERIAL_OUT` | Ran out of input material | Replenish; review safety_stock_qty in sap-s4 |
| `UTILITY_LOSS` | Plant utility (compressed air, power) | Facilities ticket, not §6 |

---

## §4 Escalation matrix

Use the most specific row that applies; if a stop matches more than one, follow the highest-severity row.

### §4.1 Single-line short stop (<15 min, no safety issue, no rework)

- Supervisor handles. No escalation.

### §4.2 Single-line significant stop (15–60 min)

- Verbal notification to Wes (Director, Plant Operations) within 30 min of stop start.
- Written shift-end note in the daily plant log.

### §4.3 Line stop >60 min, or trend-degradation (e.g. spindle vibration climbing 0.3+ mm/s over >12h)

- Email Wes within 4h of stop start with a brief (see §7).
- Log a maintenance work order with priority per §6.1.
- If the underlying cause is a supplier-quality issue, cc QA Cleveland lead (Anita Caraway, `EMP-2305`, `anita.caraway@olympus.example.com`).

### §4.4 Multi-line stop OR safety event OR any furnace alarm (Munich)

- Phone call to Wes **and** the on-call plant manager (rota in the daily log).
- COO Priya Raghavan (`EMP-1040`) is informed only if a customer commitment is at risk — escalation through Wes, not direct.

### §4.5 Quality-blocked supplier (per §5)

- Notify Wes, QA Cleveland lead, and the Procurement category lead **before** the next shift starts.

---

## §5 Supplier quality holds — the "blocked vendor → halt incoming" rule

### §5.1 Background

When a vendor in `sap-s4` carries `blocked_for_posting=true` with a quality-related `block_reason`, all incoming receipt against that vendor is paused. The block is set by AP/Quality, not by the supervisor.

### §5.2 Northbridge (V-1201) — the current open case

`V-1201 (Northbridge)` has been `blocked_for_posting=true` since May 2026 with the reason *"Quality hold pending QA dispute"*. Lots already on the floor before the hold (lot-ids like `Q-NB-44193`, `Q-NB-44197`) are **not** automatically quarantined — they're at the supervisor's discretion per §5.3.

### §5.3 What to do with already-received blocked-vendor lots

- **Default rule:** do not feed a blocked-vendor lot into a precision line (Line 3). Feed it to assembly lines (Lines 1, 2) only with QA sign-off.
- **If the lot is already loaded and the line is running:** finish the lot, scrap any defective output, log the lot id + scrap qty in the next maintenance work order.
- **If the lot is causing repeated stops** (e.g. >2 `MATERIAL_HOLD_QA` events on the same lot in 24h): stop the line, quarantine the lot, raise a QA-Cleveland ticket via `servicenow`.

### §5.4 New incoming shipments

These should already be blocked at receiving by AP, but if a shipment somehow lands on the floor with a blocked vendor stamp, refuse it and notify QA Cleveland immediately.

---

## §6 Maintenance work orders — priorities & SLAs

### §6.1 Priority guide

| Priority | Trigger | Plant Maintenance SLA (response → resolve) |
|---|---|---|
| **P1** | Line is down with safety concern, or multi-line stop | 15 min → 4h |
| **P2** | Line is below target with >5 units/hour lost, OR equipment in §2 alarm + production impact | 1h → 24h |
| **P3** | Equipment showing pre-alarm trend (e.g. §4.3 watch), no immediate production loss | 4h → 5 days |
| **P4** | Cosmetic, planned, or "next PM window" | next PM cycle |

### §6.2 The Plant Maintenance group

- Group: `Plant Maintenance` (servicenow `assignment_group`)
- Lead on day shift: `AGT-401` Reggie Bellamy
- Always assign to the group, not the individual — Reggie's team rotates the queue.

### §6.3 Required fields on every work order

- `caller_id` (the supervisor — Frank: `USR-2201`)
- `ci_id` (the equipment — e.g. `CI-DEV-3001` for the Line 3 spindle)
- `category="Maintenance"`, `subcategory="Equipment"` (or `"Calibration"`, `"Lubrication"`, `"Bearings"` if known)
- `priority` per §6.1
- `description` citing the alarm / cause code / downtime event ids (`DT-*`) — Plant Maintenance triages on the description

### §6.4 What NOT to put through Plant Maintenance

- Utility / facilities issues (Wi-Fi, power, HVAC) → existing IT or Facilities groups (e.g. INC-7004 went to Network for the Wi-Fi).
- Personnel scheduling → workday, not a ticket.

---

## §7 Incident brief template

Required whenever §4.3 or above is triggered. The supervisor builds the brief via the `incident-brief-pdf` skill; the structure below is fixed.

### §7.1 Required contents (in order)

1. **Cover** — plant + line + date + supervisor name; one-line headline ("Line 3 Precision Spindle — vibration alarm + 4 micro-stops").
2. **KPI strip** — today's OEE %, vs target, week-over-week delta, total downtime this period.
3. **OEE trend chart** — 7-day OEE with target line and threshold zones, sourced from `oee-analysis`.
4. **Downtime timeline** — each `DT-*` event with start/end, duration, cause code, lot id (if any), related PO id (if any).
5. **Root-cause narrative** — what we know, what we suspect, evidence cited by id. Be explicit about uncertainty.
6. **Material / supplier signals** — any rejected lots, any blocked-vendor exposure (per §5), any open PO at risk.
7. **Recommended actions** — maintenance work order to be logged, escalation per §4, supplier notifications.
8. **Sign-off** — supervisor name + manager (Wes Park) name + date; printed but not signed in the PDF (signed on print).

### §7.2 Distribution

- Email to Wes (always)
- Cc: QA Cleveland lead if §5 applies; Plant Maintenance lead if §6 work order is in flight; Lucia/Devon if their line is affected.
- Store the PDF in OneDrive under `Plant Operations / Cleveland / Incidents / <yyyy-mm-dd>`.

---

## §8 Glossary

- **CC-0031** — Cleveland Plant cost centre, owned by Wes Park (`EMP-1031`). Variance against this CC is the controller's concern; supervisor only references it on briefs.
- **DEV-3001** — The Siemens SINAMICS S210 Precision Spindle on Line 3. Star of every spindle conversation in 2026.
- **PO-9003** — Production order for MAT-201 Model A on Line 3. The supplier-attribution story.
- **V-1201 Northbridge** — the QA-blocked supplier per §5.2.
