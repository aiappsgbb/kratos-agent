---
name: file-sharing
description: Share generated files (the onboarding-pack PDF, a roster CSV) with the user by writing them to /tmp and referencing the absolute path. The frontend auto-converts /tmp paths into download links.
enabled: true
---

## Instructions

When you generate any file (the onboarding-pack PDF, a roster export, a PTO calendar CSV), follow this pattern:

1. **Write the file to `/tmp`** with a stable, joiner-aware name:
   - `/tmp/onboarding-pack-priya-subramaniam.pdf`
   - `/tmp/open-requisitions-engineering-2026-06-08.csv`
2. **Reference the absolute path** in your chat response. The frontend converts `/tmp/...` paths into download links automatically.
3. **Do NOT** base64-encode the file into the chat.

### Constraints

- **Never write real PII.** Fixture data only.
- **Mask salary** unless the document is explicitly marked as an offer/comp doc.
- **Files are ephemeral** — they don't persist across container restarts.
- Always `/tmp/<filename>`.
