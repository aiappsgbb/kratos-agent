# Kratos use-case roadmap

> The plan for turning Kratos into the demo accelerator that Microsoft field SEs
> reach for when they need to show an enterprise customer what a custom AI agent
> looks like — across every industry, in days not weeks.

## Vision

One agent loop. N swappable MCP-backed skills. The accelerator pattern itself
doesn't compete with M365 Copilot, Copilot Studio, or any of the Cloud-for-X
solutions — it's the thing you grab when a customer says *"I want something
that looks like Copilot but talks to my systems, in my language, with my data."*
We can stand one up for them faster than they can finish their lunch.

## Principles

1. **Real system names always.** "Workday", not "HRIS". Brand recognition is half the demo.
2. **Fixture-backed mocks, not Faker.** Each MCP server ships a coherent fictional world with stable IDs.
3. **One use-case answers one boardroom question.** Not "explore the data."
4. **Every persona produces a tangible deliverable.** Brief, draft, report, ticket, contract redline. The wealth-management PDF is the bar.
5. **Workflows over Q&A.** Multi-step skill execution with H-I-T-L confirmations for write actions — not glorified chat.
6. **Skills stay per-use-case.** No shared skill packages; we accept duplication to keep Kratos' shape simple.
7. **Each use-case ships with working sample prompts.** Three `sampleQuestions` in frontmatter, all proven end-to-end against the fixtures.

## What's shipped

| Use-case | Vertical | MCP backing | Status |
|---|---|---|---|
| `generic` | horizontal utility | — (built-ins) | shipped |
| `sales-account-review` | sales | `salesforce-mcp-server` ✅ | shipped (fixture-backed) |
| `wealth-management` | FSI — wealth | — (skills only) | shipped (improvises — to migrate) |
| `retail-banking` | FSI — banking | `faker-mcp-server` | shipped (faker — to migrate) |
| `insurance` | FSI — insurance | — (skills only) | shipped (improvises — to migrate) |

The three faker/improvising personas will be **migrated** to fixture-backed MCPs as part of the roadmap (not retired). The existing skills + brand (Olympus National Bank etc) are kept.

---

## The 45 scenarios

Depth signal: 🔍 read-only briefing · ⚙️ multi-step workflow with writes + confirmations · 📄 produces a downloadable deliverable.

### Sales (1 — shipped)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 1 | **Sales Account Review** ✅ | Brief AE before customer call | `salesforce` | Account brief 📄 |

### Horizontal back-office (5)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 2 | **HR Onboarding Specialist** | Hire new joiner → create Workday record → file IT tickets → book orientation → draft welcome email | `workday` + `servicenow` + `m365-graph` | Onboarding checklist PDF ⚙️📄 |
| 3 | **IT Service Desk L1** | Triage access ticket → check Entra → reset → grant → notify → close | `servicenow` + `entra-stub` | Resolved ticket + audit log ⚙️ |
| 4 | **Procurement Buyer** | Vet vendor + raise PO with credit/sanctions/contract checks | `sap-ariba` + `credit-bureau` | Vendor packet + PO draft ⚙️📄 |
| 5 | **Finance Close Controller** | Q-end close: variance analysis + JE proposals + anomaly flags | `sap-s4` + `workday` + `concur` | Close summary PDF ⚙️📄 |
| 6 | **Expense Approval Manager** | Bulk approve/reject team expenses with policy reasoning | `concur` + `workday` | Approval batch ⚙️ |

### Financial Services (5)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 7 | **Retail Banking CSR** *(migrates `retail-banking`)* | Customer disputes charge → investigate → refund → cross-sell offer | `core-banking` + `salesforce` | Resolution + offer email ⚙️ |
| 8 | **Wealth Advisor Pre-Meeting** *(migrates `wealth-management`)* | Brief on client portfolio + risk + life events → reuse existing PDF report | `core-banking` + `market-data` | Wealth report PDF 📄 |
| 9 | **Mortgage Underwriter** | Loan app → credit + income + property check → decision memo | `los` + `credit-bureau` | Decision memo PDF ⚙️📄 |
| 10 | **Insurance Claims Adjuster** *(migrates `insurance`)* | FNOL → fraud signals → reserve → assign | `policy-claims` + `weather` | Claim file + adjuster notes ⚙️ |
| 11 | **AML Investigator** | Investigate suspicious activity alert → decide on SAR | `core-banking` + `sanctions-stub` | SAR decision packet ⚙️📄 |

### Healthcare (4)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 12 | **Clinician Visit Prep** | Pre-visit brief: history + labs + open issues + last visit | `epic-fhir` + `m365-graph` | One-page visit prep 🔍📄 |
| 13 | **Prior Authorization Specialist** | Build PA packet with clinical evidence + cite payer policy | `epic-fhir` + `pubmed` + `payer-stub` | PA submission packet ⚙️📄 |
| 14 | **Care Coordinator Discharge** | Plan post-discharge: SNF + equipment + meds + family letter | `epic-fhir` + `skilled-nursing-stub` | Discharge plan PDF ⚙️📄 |
| 15 | **Pharma Medical Affairs** | Respond to physician unsolicited inquiry with cited literature | `pubmed` + `crm-stub` | Medical response letter ⚙️📄 |

### Manufacturing (3)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 16 | **Plant Floor Supervisor** | "Why did Line 3 miss yesterday's target?" → sensors + lot history + supplier check | `azure-iot` + `sap-s4` + `servicenow` | Incident brief + supplier action 🔍📄 |
| 17 | **Supply Chain Planner** | Re-route around port closure → impact analysis + customer comms | `sap-s4` + `sap-ariba` + `weather` | Reroute plan + customer notice ⚙️📄 |
| 18 | **Field Service Technician** | On-site diagnosis → parts order → close work order | `dynamics365` + `sap-s4` + `azure-iot` | Service report ⚙️📄 |

### Retail & CPG (3)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 19 | **Store Manager Morning Brief** | Yesterday's perf + today's staffing + shelf gaps → huddle agenda | `sap-retail` + `workday` + `azure-iot` | Store huddle agenda 🔍📄 |
| 20 | **Merchandiser** | Re-allocate stock across stores based on demand + weather | `sap-retail` + `weather` | Allocation plan ⚙️📄 |
| 21 | **CPG Brand Manager** | Launch new SKU: forecast + retail asks + media brief | `sap-retail` + `dynamics365` | Launch packet 📄 |

### Public Sector (3)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 22 | **Benefits Caseworker** | New applicant → eligibility check → decision letter | `dataverse` + `verification-stub` | Eligibility determination ⚙️📄 |
| 23 | **City 311 Dispatcher** | Citizen complaint → triage → route → SLA → schedule | `servicenow` + `gis` | Dispatched work order ⚙️ |
| 24 | **Tax Compliance Officer** | Audit risk score on filed return → exam plan | `dataverse` + `tax-stub` | Examination plan ⚙️📄 |

### Government & Defense (2)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 25 | **Defense Logistics Officer** | Stage equipment for deployment → check readiness + transport + customs | `defense-logistics-stub` + `m365-graph` | Movement order ⚙️📄 |
| 26 | **Intelligence Analyst Brief** | Synthesise OSINT + classified reports on a region → daily brief | `osint-stub` + `intel-archive-stub` | Daily brief PDF 🔍📄 |

### Energy & Utilities (2)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 27 | **Grid Storm Response** | Incoming storm → predict outages → dispatch crews + customer comms | `gis` + `weather` + `workday` | Dispatch plan + customer notice ⚙️📄 |
| 28 | **Oilfield Production Engineer** | Diagnose underperforming well → intervention recommendation | `azure-iot` + `sap-s4` | Intervention plan 🔍📄 |

### Telecom (2)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 29 | **Network Operations Triage** | Complaint cluster → correlate with network alarms → RCA + remediation | `servicenow` + `oss-stub` | Incident report 🔍📄 |
| 30 | **Telco Account Manager** | Enterprise renewal: usage + outages + competitive risk → renewal pitch | `salesforce` + `oss-stub` | Renewal pitch deck ⚙️📄 |

### Education (2)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 31 | **Student Success Advisor** | Identify at-risk students → intervention plan + outreach drafts | `sis-lms` + `m365-graph` | Intervention plan ⚙️📄 |
| 32 | **University Admissions Reviewer** | Score application against rubric → committee recommendation | `sis-lms` + `transcripts-stub` | Committee memo ⚙️📄 |

### Professional Services (2)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 33 | **Engagement Manager** | Project status: time + budget + risks + open invoices → exec update | `workday` + `salesforce` + `m365-graph` | Status update PDF 🔍📄 |
| 34 | **Legal Counsel Contract Review** | Compare contract vs playbook → redline + risk summary | `ironclad-stub` + `m365-graph` | Redlined contract + summary ⚙️📄 |

### Media & Entertainment (2)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 35 | **Newsroom Editor** | Story queue + breaking-news triage → publish-or-hold decisions | `newsroom-cms-stub` + `social-listening-stub` | Editor's daily plan 🔍📄 |
| 36 | **Streaming Content Programmer** | Slot upcoming releases against audience cohorts | `content-catalog-stub` + `audience-stub` | Programming grid ⚙️📄 |

### Transport & Logistics (2)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 37 | **Airline Operations Controller** | Weather + crew + aircraft → reaccommodate disrupted passengers | `flight-ops-stub` + `weather` + `crew-stub` | Disruption plan ⚙️📄 |
| 38 | **Fleet Logistics Dispatcher** | Plan routes for tomorrow's shipments → assign drivers + cost-out | `tms-stub` + `weather` + `workday` | Dispatch board ⚙️📄 |

### Hospitality (2)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 39 | **Hotel Revenue Manager** | Tomorrow's pricing across rate codes → with forecast + comp set | `opera-pms-stub` + `rate-shop-stub` | Pricing plan ⚙️📄 |
| 40 | **Restaurant Operations Manager** | Tomorrow's prep: forecast + staffing + supply ordering | `pos-stub` + `workday` + `supplier-stub` | Daily prep plan ⚙️📄 |

### Life Sciences R&D (2)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 41 | **Clinical Trial Matcher** | Patient candidate → screen against active trials → outreach packet | `epic-fhir` + `clinicaltrials-stub` | Match packet ⚙️📄 |
| 42 | **Drug Discovery Researcher** | Compound + target → literature + safety + assay history | `pubmed` + `chembl-stub` + `assay-stub` | Research brief 🔍📄 |

### Real Estate (1)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 43 | **Commercial Leasing Agent** | Match tenant brief to portfolio → tour plan + comps | `costar-stub` + `crm-stub` | Tour packet + comps ⚙️📄 |

### Agriculture (1)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 44 | **Precision Ag Advisor** | Field-by-field treatment plan based on yield + weather + soil | `johndeere-stub` + `weather` + `soil-stub` | Application plan ⚙️📄 |

### Nonprofit (1)

| # | Persona | Workflow | MCPs | Deliverable |
|---|---|---|---|---|
| 45 | **Major Gifts Officer** | Brief on prospect: giving history + wealth signals + interests → ask plan | `raisers-edge-stub` + `wealth-screening-stub` | Donor brief 🔍📄 |

---

## MCP server catalog

18 production-grade MCPs + ~35 lighter stubs unlock all 45 use-cases. "Stub" means a small ~2-hour, single-purpose helper (e.g. `weather.get_forecast(zip)`); production-grade means full Salesforce-style coverage (~10 tools, coherent fixtures across 5–10 entities).

### Production-grade MCPs (~half day each)

| Server | Powers use-cases |
|---|---|
| `salesforce-mcp-server` ✅ | 1, 7, 30, 33 |
| `workday-mcp-server` | 2, 5, 6, 19, 27, 33, 38, 40 |
| `servicenow-mcp-server` | 2, 3, 16, 23, 29 |
| `m365-graph-mcp-server` | 2, 12, 25, 31, 33, 34 |
| `sap-s4-mcp-server` | 5, 16, 17, 18, 28 |
| `sap-ariba-mcp-server` | 4, 17 |
| `concur-mcp-server` | 5, 6 |
| `azure-iot-mcp-server` | 16, 18, 19, 28 |
| `epic-fhir-mcp-server` | 12, 13, 14, 41 |
| `core-banking-mcp-server` | 7, 8, 11 |
| `sap-retail-mcp-server` | 19, 20, 21 |
| `dynamics365-mcp-server` | 18, 21 |
| `gis-mcp-server` | 23, 27 |
| `dataverse-mcp-server` | 22, 24 |
| `los-mcp-server` | 9 |
| `policy-claims-mcp-server` | 10 |
| `sis-lms-mcp-server` | 31, 32 |
| `pubmed-mcp-server` | 13, 15, 42 |

### Lighter stubs (~2 hours each)

`credit-bureau`, `weather`, `market-data`, `entra`, `payer`, `verification`, `skilled-nursing`, `oss`, `sanctions`, `tax`, `defense-logistics`, `osint`, `intel-archive`, `transcripts`, `ironclad`, `newsroom-cms`, `social-listening`, `content-catalog`, `audience`, `flight-ops`, `crew`, `tms`, `opera-pms`, `rate-shop`, `pos`, `supplier`, `clinicaltrials`, `chembl`, `assay`, `costar`, `crm`, `johndeere`, `soil`, `raisers-edge`, `wealth-screening`.

### Reuse multiplier

The top 4 production MCPs alone (`workday`, `servicenow`, `m365-graph`, `sap-s4`) power 18 of 45 use-cases. Every production MCP pays back at least twice. The stubs are cheap glue, not the cost driver.

---

## Phasing

**Phase 0 — shipped.** `sales-account-review`.

**Phase 1 — 5 flagships across 5 verticals.** Validates the MCP pattern under different shapes, gives field SEs immediate vertical coverage:
- #2 HR Onboarding (horizontal back-office)
- #7 Retail Banking CSR (FSI + migrates existing)
- #12 Clinician Visit Prep (healthcare)
- #16 Plant Supervisor (manufacturing)
- #19 Store Manager (retail)

Builds 5 production MCPs (`workday`, `servicenow`, `m365-graph`, `core-banking`, `epic-fhir`, `azure-iot`, `sap-s4`, `sap-retail`) + a handful of stubs.

**Phase 2 — fill horizontals.** #3 IT Desk, #4 Procurement, #5 Finance Close, #6 Expense. All ride on Phase 1 MCPs + `sap-ariba`, `concur`, `entra-stub`, `credit-bureau`.

**Phase 3 — deepen verticals already opened.** Add 2nd–3rd persona per vertical using existing MCPs: #8, #9, #10, #11 (FSI), #13, #14, #15 (healthcare), #17, #18 (manufacturing), #20, #21 (retail), #33, #34 (proserv).

**Phase 4 — open remaining verticals.** Public sector (#22, #23, #24), gov-defense (#25, #26), energy (#27, #28), telecom (#29, #30), education (#31, #32), media (#35, #36), transport (#37, #38), hospitality (#39, #40), life sciences (#41, #42), real estate (#43), agriculture (#44), nonprofit (#45).

**Phase 5 — quality pass.** Tighten sample prompts so every persona has 3 proven demo scripts; confirm every use-case has a 📄 deliverable that downloads cleanly.

Within each phase, order follows MCP dependency: build the server, then drop in the use-case (~2 hours each on existing MCPs, ~half-day with a new one).

---

## How to add a new use-case

1. **Pick the MCP servers it needs.** If they all exist, skip to step 3.
2. **Add the missing MCP server(s)** under `mocks/packages/` — copy `salesforce-mcp-server` as the template. See [`mocks/README.md`](../mocks/README.md).
3. **Create `use-cases/<name>/`** with `SYSTEM_PROMPT.md`, `.mcp.json`, `apm.yml`, and `skills/<skill-name>/SKILL.md` for each skill. Each SKILL.md names the specific MCP tools to call.
4. **Add a row to "What's shipped"** above and tick the matching row in "The 45 scenarios".
5. **Test end-to-end locally** via `./run-local.sh` + the frontend, hitting each `sampleQuestions` prompt.
6. **Open a PR.**

---

## Anti-patterns

- **Faker-driven new use-cases.** Existing ones (`retail-banking`, `insurance`, `wealth-management`) are being migrated, not extended. No new persona ships against Faker.
- **Use-cases without a write workflow.** Read-only briefings are fine for some personas (#1, #12, #16, #19) but the demo set leans toward ⚙️ workflows so we tell the "agent that does things" story, not "glorified chat bot".
- **Use-cases without a deliverable.** If the agent doesn't produce something downloadable / shareable, the demo has no payoff moment.
- **Skipping `sampleQuestions`.** Aspirational prompts are worse than no prompts. Every persona ships with three proven scripts.
- **Vertical-specific UI tweaks.** Differentiation comes from skills + MCPs + system prompt. Frontend stays generic.
- **Replicating Microsoft's actual Copilots.** Kratos is the accelerator that *customers and partners* use to build their own.
