# Olympus Industries — Controllers' Close Policy

> Version 2026.1 — effective 2026-01-01. Owner: Office of the Controller, Hiroshi Tanaka (EMP-1021). Reviewed annually. Supersedes 2025.2.

This policy governs the month-end and quarter-end close process for all Olympus Industries entities reporting into the consolidated US-GAAP general ledger in SAP S/4HANA. It is binding on all cost-centre owners, finance business partners, and the Controllers' team.

## §1. Close calendar and cut-offs

**§1.1.** The monthly close is a **5-business-day close** running from the first business day of month+1 through the fifth.

**§1.2.** The published close calendar lives in the Finance SharePoint at `/finance/close/<period>/<period>-close-timeline.xlsx`. Each cost-centre owner must check the calendar by the Friday before close begins.

**§1.3.** Standard close cadence:

| Day | Activity | Owner |
|-----|----------|-------|
| Day 1 | Close kickoff. Variance dashboard refreshed. Owners notified. | Controllership |
| Day 2 | Accrual cutoff at 17:00 Cleveland time. | Controllership + cost-centre owners |
| Day 3 | All JEs posted. Variance commentary submitted in the workbook. | Cost-centre owners |
| Day 4 | Reviewer pass. Adjustments / re-postings. | Controllership |
| Day 5 | Books closed. Close pack delivered to CFO. | Controllers' team |

**§1.4.** **Accrual cut-off.** No new accruals for the closing period may be created after Day 2 17:00 Cleveland. Late accruals are deferred to the next period unless approved by the CFO under §2.5.

**§1.5.** Quarter-end adds Day 6 (consolidation + intercompany), Day 7 (review with CFO), and Day 8 (board pre-read pack).

## §2. Accrual rules

**§2.1.** Accruals are recorded as: **Dr** the relevant expense GL on the requesting cost centre; **Cr** GL 2200 (Accrued Liabilities). When the vendor invoice subsequently arrives, AP debits 2200 and credits 2100 (AP Clearing) to release the accrual.

**§2.2.** The accrual must cover only services rendered or goods received **in the period being closed**. Accruals for future periods are not permitted.

**§2.3.** **Materiality and evidence.** Accruals require supporting evidence proportional to amount:

| Amount | Evidence required |
|---|---|
| $0 – $4,999 | Cost-centre owner's email or chat confirmation |
| $5,000 – $24,999 | Vendor email / PO reference / prior-invoice precedent |
| $25,000 – $99,999 | Active vendor MSA, signed PO, or documented prior-quarter run-rate |
| $100,000+ | All of the above + Controllership review before posting |

**§2.4.** Reversing accruals **must** be flagged as `auto_reverse: true` so they reverse on day 1 of the following period.

**§2.5.** **Late-accrual exception.** After §1.4 cut-off, the CFO may approve an accrual via signed email to the Controller for items materially affecting the period's reported result (typically >$500k). Approval thread must be attached to the JE.

## §3. Reclass rules

**§3.1.** Reclasses use the **same GL** on both legs, with debit on the receiving cost centre and credit on the originating cost centre. Cross-GL reclasses require a Manual JE (see §4).

**§3.2.** Reclasses are permitted up to Day 4 (reviewer pass) but require both originating and receiving cost-centre owner sign-off (chat confirmation acceptable) when the amount exceeds $10,000.

## §4. Manual journal entries

**§4.1.** A Manual JE (`type: Manual`) is any JE that is not an accrual, reclass, payroll, depreciation, intercompany, or system-generated FX adjustment. Manuals attract audit scrutiny and require:

- A clear source-document reference in the memo field
- Second-approver sign-off when the amount exceeds $10,000 (SOX SoD per §6.2)
- A note in the close-pack JE-queue section explaining the necessity

**§4.2.** Round-number Manual JEs over $250,000 are escalated to the External Audit liaison for the quarter.

**§4.3.** If you find yourself drafting a third Manual JE in a period for the same cost-centre or GL combination, raise it with Controllership — there is likely a systemic issue (interface, allocation rule, or unposted feeder).

## §5. Variance materiality and commentary

**§5.1.** Commentary thresholds vs prior-year YTD (these thresholds also drive the `normal` / `watch` / `investigate` flag from `sap_get_variance_analysis`):

| Variance | Flag | Commentary required? |
|---|---|---|
| ≤ ±5% | normal | No |
| ±5% – ±20% | watch | At Controllership discretion |
| > ±20% | investigate | **Mandatory** before Day 3 EOD |

**§5.2.** Commentary must cover: **driver** (volume / price / mix / one-off), **outlook** (expected to continue / one-off catch-up / remediation in flight), **action** (none / forecast adjustment / remediation plan).

**§5.3.** Cost-centre owners who are out of office during close must designate a delegate via Workday `time_off.coverage_user_id` or Outlook OOO message. Variance commentary from the delegate is acceptable.

## §6. SOX controls

**§6.1.** Every JE write is captured in the audit log (JE id, period, user, timestamp, amount, lines) and exported nightly to the SOX vault.

**§6.2.** **Segregation of duties.** No single user may both (a) propose a Manual JE over $10,000 *and* (b) post the same JE. Two-step ("4-eyes") approval is required. The H-I-T-L confirmation pattern in `journal-entry-proposal` enforces this at the agent level — the agent proposes (Draft), the human approves and triggers the Post.

**§6.3.** All variance commentary is retained for 7 years per Sarbanes-Oxley retention policy.

## §7. Vendor blocks and sanctions

**§7.1.** No JE may credit a vendor flagged as `sanctioned: true` or `blocked: true` in the vendor master without:

- A documented exception from the General Counsel's office
- Notification to Treasury within 24h

**§7.2.** When proposing an accrual for a vendor, the agent must call `sap_get_vendor` and surface the sanctioned/blocked status before showing the Draft.

## §8. Close pack contents and sign-off

**§8.1.** The close pack PDF, delivered to the CFO on Day 5 (and to the Board pre-read folder on Day 12 for quarter-end), contains in order:

1. **Cover** — period, currency, version, prepared-by, sign-off block
2. **Executive summary** — top 3 variance call-outs, total accruals booked, JE queue health
3. **Variance review** — full bar chart of variance % by cost centre with the threshold lines from §5.1, plus a table of every `investigate`-flagged row with owner commentary
4. **JE queue** — every JE posted in the period, grouped by type (Accrual / Reclass / Manual / Other), with a "Manuals review" callout
5. **Accruals** — every Day 1–2 accrual with vendor, evidence reference, and auto-reverse flag
6. **Vendor exceptions** — any §7.1 exceptions used in the period
7. **Sign-off** — Controller, CFO

**§8.2.** Sign-off blocks are dated and named. The PDF is filed to `/finance/close/<period>/<period>-close-pack.pdf` and a copy is emailed to the CFO and the Audit Committee Chair.

---

*Questions: Hiroshi Tanaka (EMP-1021), Director, Controllership.*
