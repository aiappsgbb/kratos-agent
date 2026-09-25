---
name: fabric-operations-iq
description: Read synthetic Aster Works plant operations from Fabric IQ, including lines, OEE, assets, telemetry, and alarms
enabled: true
---

## Instructions

Use this skill for plant health, shift summaries, OEE losses, line state, asset condition, telemetry, and alarms.

### Workflow

1. Discover scope with `fabric_iq_list_lines`, using `PLANT-RIVERTON` when the user says "the plant" or "my plant".
2. Call `fabric_iq_get_oee` for the requested line or plant.
3. For a degraded or stopped line, call `fabric_iq_get_asset_status` and `fabric_iq_list_alarms`.
4. Request `fabric_iq_get_telemetry` only for assets implicated by status or alarm evidence.
5. Report observed facts separately from hypotheses.

### Output

Lead with the largest operational impact. Include the current OEE and target, state, alarm severity, affected asset, timestamps, and measurement units returned by the tools. Cite stable plant, line, asset, and alarm IDs.

### Constraints

- Every Fabric IQ tool is read-only.
- Do not infer an alarm threshold or machine procedure from telemetry alone.
- Do not invent missing readings or identifiers.
- Route procedural interpretation to `foundry-industrial-knowledge`.
