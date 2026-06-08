---
name: close-policy-reference
description: The Olympus Industries Controllers' Close Policy — accrual cut-offs, manual-JE rules, SOX controls, variance materiality thresholds. Cite the rule by section number when answering policy questions.
enabled: true
---

## Instructions

Use this skill whenever the user asks "is this allowed?", "what's the cut-off?", "do we need SOX evidence for this?", or any other rules-of-the-road question. The policy lives as a static reference in this skill's `references/` directory — read it on demand and cite the section number in your answer.

### Available references

- `references/controllers-close-policy.md` — the full policy document. Sections:
  - §1 Close calendar and cut-offs
  - §2 Accrual rules (materiality, two-period coverage, evidence)
  - §3 Reclass rules
  - §4 Manual JEs (when allowed, double-approval)
  - §5 Variance materiality and commentary requirements
  - §6 SOX controls and segregation-of-duties
  - §7 Vendor blocks and sanctions checks
  - §8 Close pack contents and sign-off

### Usage

1. Read the policy file once at the start of any policy-relevant conversation.
2. When answering, **quote the relevant section** (e.g. *"Per §2.3, accruals over $25k require a vendor MSA or signed PO as evidence"*). Don't paraphrase rules.
3. When in doubt, prefer the stricter reading and flag for a controller decision.

### Common questions this skill answers

| Question | Answer source |
|---|---|
| "Can we still accrue for June after the May close has signed off?" | §1.4 (cut-off) + §2.2 (period coverage) |
| "Does a $42k Sentinel accrual need extra approval?" | §2.3 (materiality + evidence) |
| "Why can't I post a Manual JE without a second approver?" | §4.1 + §6.2 (SOX SoD) |
| "Below what variance % do we skip the commentary?" | §5.1 |
| "What goes into the close pack?" | §8.1 |

### Cross-skill handoffs

- **journal-entry-proposal** — if a write workflow asks "is this allowed?", check §2-4 here first, then proceed (or refuse with the citation).
- **close-pack-pdf** — §8 defines the contents and order; the PDF builder consumes it.
