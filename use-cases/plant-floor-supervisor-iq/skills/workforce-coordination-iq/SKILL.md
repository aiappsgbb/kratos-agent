---
name: workforce-coordination-iq
description: Look up synthetic Aster Works people and availability, then prepare or confirmation-gate simulated recovery meetings through Work IQ
enabled: true
---

## Instructions

Use this skill when the user asks who owns an area, who is available, or wants to coordinate a recovery review.

### Read-only lookup

1. Use `work_iq_search_people` to resolve people by name, role, skill, or plant.
2. Use `work_iq_get_person` for exact role and contact metadata.
3. Use `work_iq_find_availability` for the requested people and time window.
4. Clearly state that availability is synthetic and local to the demo.

### Simulated meeting workflow

1. Resolve attendees and find a mutually available slot.
2. Call `work_iq_prepare_meeting` with the exact title, attendee IDs, time, duration, and agenda.
3. Show the full proposal and ask for explicit confirmation.
4. Only after confirmation, call `work_iq_create_meeting` with the unchanged preparation and confirmation token.
5. Report the returned simulated receipt and repeat that no invitations, messages, rooms, or real calendar entries were created.

### Constraints

- Never call `work_iq_create_meeting` in the same turn as an unconfirmed user request.
- Never describe preparation as creation.
- If the user changes any field, prepare again and obtain a new confirmation.
- Do not use real M365 or send real messages.
