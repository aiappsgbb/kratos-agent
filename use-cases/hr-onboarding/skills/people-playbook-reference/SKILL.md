---
name: people-playbook-reference
description: The Olympus Industries People Playbook — onboarding cadence, probation criteria, equity-vesting timing, PTO accrual rules, manager-1:1 cadence, references to Beatrix on policy boundaries. Cite by section number when answering policy questions.
enabled: true
---

## Instructions

Use this skill whenever the user (Beatrix) asks "what's our policy on X?", "what's the rule for {benefit}?", or "is {action} allowed under the playbook?".

The reference text lives as a static markdown file in this skill's `references/` directory. Read it on demand and cite the section number in your answer.

### Available references

- `references/olympus-people-playbook.md` — the full Olympus People playbook. Sections:
  - §1 Onboarding cadence (day -7 → day 30)
  - §2 Probation period + exit criteria
  - §3 Equity grants — vesting + cliff
  - §4 PTO accrual + carry-over
  - §5 Manager 1:1 cadence
  - §6 Internal mobility + transfer rules
  - §7 Termination + offboarding
  - §8 Compensation review windows
  - §9 Data privacy + access boundaries (what HR specialists may / may not see)

### Usage

1. Read the playbook once at the start of any policy-relevant turn.
2. **Quote the relevant rule verbatim** with the section reference (e.g. *"Per §1.3, the M365 mailbox should be provisioned 5 business days before start; the laptop should arrive at the home address 2 business days before start"*).
3. **Frame as reference, not order.** "The playbook says X" — let Beatrix decide whether it applies.

### When the answer is "no"

If a request would violate §9 (data-access boundaries) or §3 (equity-grant rules around cliff timing), refuse and explain the policy citation. Don't propose a work-around that breaks the rule.

### Cross-skill handoffs

- **new-hire-onboarding** — before drafting a Pre-Hire record, confirm equity terms and salary band against §3 + §8.
- **onboarding-pack-pdf** — §1 defines the cadence sections the PDF must follow.

### Constraints

- Do not invent playbook citations. If a question is outside the 9 sections, say so directly: *"That's not in our People playbook — recommend asking the Total Rewards team or Legal."*
- Do not give legal advice (employment law varies by jurisdiction).


<!-- skill-files -->
## Available Files

This skill directory contains the following files you can read with `read_file` using their absolute paths (prefix `/app/use-cases/hr-onboarding/skills/people-playbook-reference/`):

- `references/olympus-people-playbook.md`
