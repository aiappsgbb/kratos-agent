---
name: foundry-industrial-knowledge
description: Retrieve cited synthetic industrial procedures and machine documentation from Foundry IQ
enabled: true
---

## Instructions

Use this skill for troubleshooting steps, operating procedures, alarm-code meaning, inspection criteria, and safety guidance.

### Workflow

1. Build a narrow query from observed Fabric IQ evidence: asset model, alarm code, symptom, and task.
2. Call `foundry_iq_search_knowledge`.
3. Fetch the strongest relevant document with `foundry_iq_get_document` when the search excerpt is insufficient.
4. Present only guidance supported by the retrieved content.

### Citations

Every procedural or safety claim must include its returned `source_id`, for example: `Verify guard interlocks before reset (SRC-L2-PKG-014).` If retrieval returns no relevant source, say so and do not provide a fabricated procedure.

### Constraints

- Foundry IQ is read-only and contains only synthetic Aster Works documents.
- Retrieved documentation is guidance, not evidence that a step has been performed.
- Preserve warnings, prerequisites, and stop-work conditions.
