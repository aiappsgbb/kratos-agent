---
name: pre-visit-summary
description: Build a deep pre-visit summary for one upcoming encounter — problem list, meds, labs, last visit, suggested focus
enabled: true
---

## Instructions

Use this skill when the user asks for a deep brief on one patient before a visit (e.g. "Pre-visit summary for Eleanor Hsu's BP follow-up", "Brief me on PAT-100001 for the 10am", "Give me everything I need before I see George").

### 1. Resolve the patient + encounter

- If the user named a patient → `epic_search_patients_by_name` → `epic_get_patient`
- If the user referenced an encounter or time → `epic_list_encounters_for_patient(patient_id, status: 'Booked')` to find it
- If neither → ask which patient

### 2. Fan out (in parallel)

For the patient:
- `epic_list_conditions(patient_id)` — active problem list
- `epic_list_medications(patient_id, status: 'active')` — current med list
- `epic_list_allergies(patient_id)` — allergies + intolerances
- `epic_list_encounters_for_patient(patient_id, status: 'Finished', limit: 3)` — last 3 visits
- `epic_list_observations(patient_id, limit: 20)` — recent labs + vitals

### 3. If the visit reason references a specific domain, drill in

The encounter `reason_text` usually hints at what to surface (e.g. "BP not at goal" → pull recent `BP` observations specifically via `epic_list_observations(patient_id, code: 'BP', limit: 5)`).

### 4. Consult the guidelines reference for the "Suggested focus" section

Before writing "Suggested focus", **always invoke the `clinical-guidelines-reference` skill** (read `references/chronic-conditions-quick-reference.md`). For any out-of-range value or chronic condition on the patient's problem list, cite the relevant section number and target in the focus bullet.

Examples:
- BP 148/92 with T2DM on the problem list → cite **§1.2 (NICE NG136)** for the <130/80 target.
- LDL 82 post-MI → cite **§3.1 (ACC/AHA 2024)** for the <70 mg/dL target.
- HbA1c 7.4 → cite **§2.1 (ADA 2026)** for the <7.0 target and **§2.3** for the SGLT-2 add-on indication if there's coexisting ASCVD or CKD.
- eGFR <60 + Metformin → cite **§4.2 (KDIGO 2024)** for the dose-adjustment threshold.

If no clinical guideline applies (e.g. pure wellness visit, paediatric well-child), skip this step.

### 5. Render

```markdown
# Pre-Visit Summary — Eleanor Hsu (PAT-100001, MRN-100001)
**F, age 78 (DOB 12 Mar 1948) · Insurer: Medicare + Blue Cross MA · PCP: Dr. Aniyah Solomon**

## Today's encounter
**10:00, 2 June 2026 — Office Visit (ENC-200003) — Adult Primary Care, Boston Main**
> Follow-up: BP not at goal on current regimen

## ⚠️ Allergies
- **Penicillin** — moderate (rash, 1998)

## Active problems
- Essential hypertension (I10) — onset 2014
- Type 2 diabetes mellitus (E11.9) — onset 2017
- ASCVD (I25.10) — onset Aug 2025 *(post-MI)*

## Active medications (5)
**Hypertension / cardiovascular:**
- Lisinopril 20 mg PO daily *(since 2014)*
- Metoprolol succinate 50 mg PO daily *(post-MI, since Aug 2025)*

**Diabetes:**
- Metformin 1000 mg PO BID *(since 2017)*

**Post-MI secondary prevention:**
- Atorvastatin 40 mg PO QHS *(since Aug 2025)*
- Aspirin 81 mg PO daily *(since Aug 2025)*

## Recent BP trend (last 5)
| Date | BP | Interpretation |
|---|---|---|
| 15 Apr 2026 | 148/92 mmHg | High (above goal) |

*(Only one BP reading on file in the last 12 months — note for the visit.)*

## Recent key labs
- **HbA1c 7.4%** (above goal <7.0) — 15 Apr 2026
- **LDL 82 mg/dL** (above post-MI target <70) — 15 Apr 2026
- **eGFR 67 mL/min/1.73m²** (mildly reduced) — 15 Apr 2026

## Last visit (15 Apr 2026, ENC-200001)
Annual physical with you, 45 min. Reason text: "Annual physical, follow-up on HTN + T2DM."

## Suggested focus for today
1. **BP control** — 148/92 from April with the current Lisinopril + Metoprolol regimen. Consider intensifying (add HCTZ, or increase metoprolol if HR allows) and re-checking in 4 weeks.
2. **Post-MI lipid target** — LDL 82 is above the <70 mg/dL post-MI goal. Atorvastatin 40 mg → consider 80 mg or add ezetimibe.
3. **A1C 7.4%** — drifting above goal. Discuss adherence; consider GLP-1 or SGLT-2 if not contraindicated.
4. **Renal** — eGFR 67 is mildly reduced; recheck at 6 months and dose-watch metformin if it drops below 45.
```

### Constraints

- **Never paraphrase lab values.** Use the exact value + unit from the tool.
- Surface severe allergies (🔴) *before* the problem list when they're severe enough to be life-threatening. Moderate (⚠️) inline.
- "Suggested focus" is clinical reasoning, not advice — frame it as questions/considerations, not orders. Always end with a reminder that the clinician decides.
- If the patient has fewer than 3 medications or no recent labs, render what's there and say so — don't pad.
