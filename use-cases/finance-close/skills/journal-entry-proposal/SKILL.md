---
name: journal-entry-proposal
description: Propose and post Journal Entries — accruals, reclasses, manuals — with strict two-step H-I-T-L confirmation.
enabled: true
---

## Instructions

Use this skill whenever the controller asks you to draft, propose, accrue, reclass, or post a journal entry (e.g. "Accrue the June Sentinel licence", "Reclass $92k consulting from HQ to Engineering", "Post JE-39001"). Writes here mutate the ledger so the gate is strict.

### Pattern

#### Step 1 — propose (creates Draft)

Build the proposed JE from the request, then call `sap_propose_journal_entry`. The tool validates:

- Debits == credits (balanced)
- Every `gl_account` exists in the chart
- Every `cost_centre` (when set) exists

If validation fails, surface the error verbatim, propose a fix, ask the user.

If validation succeeds, you get back a `Draft` JE with a new `JE-*` id.

#### Step 2 — show the Draft + ask to post

Render the Draft with full line detail:

```
I've created Draft JE-39001:

- Date:     1 June 2026 · Period 2026-06
- Type:     Accrual · Source FI · Currency USD
- Total:    $42,000 (debits == credits)

| # | GL                              | Cost Centre              | Debit    | Credit   | Memo                                                       |
|---|---------------------------------|--------------------------|---------:|---------:|------------------------------------------------------------|
| 1 | 6400 (Software & Subscriptions) | CC-0011 (Platform Eng)   | $42,000  | —        | Sentinel Observability — June licence accrual              |
| 2 | 2200 (Accrued Liabilities)      | —                        | —        | $42,000  | Accrued liability — vendor V-1102 (Sentinel) June 2026     |

Confirm to post? (yes / edit / no)
```

Use `ask_user`. **Wait.** Do not call `sap_post_journal_entry`.

#### Step 3 — execute on explicit "yes"

- **yes** → `sap_post_journal_entry` with the Draft id
- **edit X** → gather the correction, re-call `sap_propose_journal_entry`, show new Draft, re-confirm
- **no** → stop and acknowledge; the Draft stays Drafted (won't post)

#### Step 4 — report the receipt

After Post succeeds:

```
Posted: JE-39001 · period 2026-06 · $42,000 total · 2 lines · accrual.
```

Then offer the natural next step: "Want me to draft Hiroshi the variance commentary that references this accrual?" — handing off to the **variance-email** skill.

### Common patterns

- **Accrual** (vendor invoice expected but not yet received): debit the expense GL on the requesting cost centre, credit **GL 2200 (Accrued Liabilities)**. Don't search for the credit account — it's 2200. When the invoice lands, AP later debits 2200 and credits AP-Clearing 2100, but that's a separate workflow.
- **Reclass** (move expense from one cost centre to another): same GL on both lines; debit new CC, credit old CC.
- **Manual** (true one-off): flag `type=Manual` and double-confirm specifically — *"This will be flagged as Manual (no source doc). Confirm to post?"* — manuals attract audit scrutiny.

### Constraints

- **Never** call `sap_post_journal_entry` without explicit `yes` in the turn after showing the Draft.
- If the user gives an amount only, ask for: cost centre, expense GL, memo, source. Don't guess.
- Round-trip currency: render `$42,000`; pass `42000` to the tool.
- After posting, the JE id is the receipt — always include it in your confirmation line.

### Cross-skill handoffs

- **close-policy-reference** — if you're unsure whether an accrual is allowed inside the close cut-off, read the policy first; cite the rule in your draft summary.
- **variance-email** — after a successful post, offer to draft the commentary email that references the new JE.
- **close-pack-pdf** — newly posted JEs and pending Drafts must be reflected in the close pack; if the user has already generated one this turn, offer to refresh it.
