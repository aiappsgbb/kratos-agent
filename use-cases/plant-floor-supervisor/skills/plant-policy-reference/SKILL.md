---
name: plant-policy-reference
description: The Olympus Cleveland-plant Standard Operating Procedure — alarm thresholds, escalation matrix, supplier quality-hold rules, OEE definitions, incident-brief template requirements. Cite the section number when answering.
enabled: true
---

## Instructions

Use this skill whenever Frank asks "is this allowed?", "when do I have to escalate?", "what does OEE actually include?", or any other rules-of-the-road question. The SOP lives as a static reference in this skill's `references/` directory — read it on demand and cite the section number in your answer.

### Available references

- `references/cleveland-plant-sop.md` — the full SOP. Sections:
  - §1 OEE definitions & targets (Availability × Performance × Quality)
  - §2 Alarm thresholds by equipment class (spindles, robots, conveyors, vision, induction furnaces)
  - §3 Downtime cause-code taxonomy (`VIB_ALARM`, `MATERIAL_HOLD_QA`, `CAL_DRIFT`, `PLANNED_MAINT`, etc.)
  - §4 Escalation matrix (who supervisor calls when, e.g. line >30 min stop, QA-blocked supplier shipment)
  - §5 Supplier quality holds and the "blocked vendor → halt incoming" rule
  - §6 Maintenance work order priorities and Plant Maintenance group SLA targets
  - §7 Incident brief template — what each PDF must contain and the sign-off step

### Usage

1. Read the SOP file at the start of any policy-relevant conversation (use `file_read` on `references/cleveland-plant-sop.md`).
2. When answering, **quote the relevant section** (e.g. *"Per §4.2, any line stop >30 min triggers a call to Wes and a written incident brief within 4 hours"*). Don't paraphrase rules.
3. When in doubt, prefer the stricter reading and flag for Wes.

### Common questions this skill answers

| Question | Section |
|---|---|
| "Is 4.5 mm/s the right vibration alarm for a precision spindle?" | §2.1 |
| "Do I have to escalate this to Wes if Line 3 is down for 90 min?" | §4.2 |
| "Northbridge is blocked — what do I do with the lots already on the floor?" | §5.3 |
| "What priority should I file the spindle work order at?" | §6.1 |
| "What goes in the morning incident brief?" | §7.1 |
| "How is OEE actually computed — do quality losses double-count downtime?" | §1.2 |

### Cross-skill handoffs

- **servicenow** (maintenance work order section) — §6 sets the priority guide; cite it on the draft.
- **incident-brief-pdf** — §7 defines the brief contents; the PDF builder follows that order.
- **m365-graph** (email section) — §4 escalation matrix tells you who to cc on the brief.
