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

---

## Principles

1. **Real system names always.** "Workday", not "HRIS". Brand recognition is half the demo.
2. **Fixture-backed mocks, not Faker.** Each MCP server ships a coherent fictional world with stable IDs.
3. **One use-case answers one boardroom question.** Not "explore the data."
4. **Every persona produces a tangible deliverable.** Brief, draft, report, ticket, contract redline. The `wealth-management` PDF is the bar — see [The quality bar](#the-quality-bar).
5. **Workflows over Q&A.** Multi-step skill execution with H-I-T-L confirmations for write actions — not glorified chat.
6. **Heterogeneous skill mix.** A persona is *not* "one MCP + read tools + ask_user". Every persona blends at least three skill *kinds* (MCP-calls, RAG search, code interpreter / data analysis, PDF / file output, email drafts, web search). See [The quality bar](#the-quality-bar).
7. **Skills are mini-products, not prompts.** A SKILL.md is the instruction — but production skills also carry `references/`, `scripts/`, and `assets/` where they help. See [Skill anatomy](#skill-anatomy).
8. **Skills stay per-use-case.** No shared skill packages; we accept duplication to keep Kratos' shape simple.
9. **Sample prompts are proven, not aspirational.** Three `sampleQuestions` in frontmatter, all run end-to-end against the fixtures before the PR opens.

---

## The quality bar

The reference implementations are `use-cases/wealth-management/`, `use-cases/insurance/`, and `use-cases/retail-banking/`. Any new persona must match the depth and shape of these, not the thinner pattern of the early MCP-pairing PRs (#5, #7, #8, #9, #10). See [Audit](#audit-what-shipped-vs-the-bar) for the gap.

### What "the bar" means concretely

A persona that meets the bar has **all** of the following:

| Dimension | What it looks like on `wealth-management` |
|---|---|
| **Skill kinds** | 10 distinct skills mixing `crm` (data lookup), `portfolio-review` (computed analysis), `rag-search` (FINMA / KYC docs), `pdf-wealth-report` (deliverable), `web-search` (market data), `code-interpreter`, `data-analysis`, `email-draft`, `document-summary`, `file-sharing` |
| **Skill routing in SYSTEM_PROMPT.md** | Explicit table mapping *user intent* → *skill to call*. Not "use skills when relevant" — a routing matrix. |
| **Skill depth** | SKILL.md files average 80–200 lines. Pipeline diagrams, code snippets, JSON schemas, fallback strategies. |
| **Assets shipped with skills** | `references/` for RAG-style content (compliance.md, css-reference.md), `scripts/` for working code (generate-pdf.js, generate-charts.js), `assets/` for templates (portfolio-review.html) |
| **Real deliverable** | A polished PDF with KPI cards, SVG charts, navy/gold theme, compliance footer. Not "the agent said the right thing." |
| **Fallback / branching logic** | Skills cope when an upstream is missing — e.g. `claims-mgmt` prefers ARGUS MCP for doc extraction, falls back to native Vision LLM if ARGUS is unreachable |
| **Cross-skill orchestration** | One skill explicitly hands off to another (e.g. `portfolio-review` writes `/tmp/portfolio_analysis.json` for `pdf-wealth-report` to consume) |
| **Tested sample prompts** | Every `sampleQuestion` runs end-to-end against the fixtures and produces a sensible answer with the expected tool calls |

### Skill anatomy

```
use-cases/<persona>/skills/<skill-name>/
├── SKILL.md                    # required: instruction + routing + examples
├── references/                 # optional: RAG-style content the skill cites
│   ├── compliance.md
│   └── css-reference.md
├── scripts/                    # optional: working code the skill executes
│   ├── generate-pdf.js
│   └── generate-charts.js
└── assets/                     # optional: templates / themes / boilerplate
    ├── portfolio-review.html
    └── market-outlook.html
```

A SKILL.md must contain:
- YAML frontmatter (`name`, `description`, `enabled: true`)
- **When to use** — concrete trigger conditions (and when NOT to use)
- **Workflow / pipeline** — step-by-step what the skill does, including parallel branches and fallbacks
- **Inputs / outputs** — what data shapes the skill expects and produces
- **Worked examples** — code snippets, command lines, or worked rendering of the output
- **Cross-skill handoffs** — if the skill produces or consumes another skill's output, name the file path / shape

### Skill-mix requirement

Every persona must mix at least **3 skill kinds** from this list:

| Kind | Examples |
|---|---|
| **MCP call** (system-of-record lookup) | `salesforce-mcp-server`, `epic-fhir-mcp-server`, `sap-s4-mcp-server`, `core-banking-mcp-server` |
| **RAG search** (cite internal docs) | `rag-search` against an Azure AI Search index of policy / clinical / regulatory content |
| **Code interpreter** (real computation) | `code-interpreter` for loan amortisation, portfolio returns, fraud scoring, dosage calc |
| **Data analysis** (computed insight + charts) | `data-analysis` for trend analysis, cohort segmentation, anomaly detection |
| **Web search** (live external data) | `web-search` for market data, weather, regulatory announcements |
| **Document / PDF output** (the deliverable) | `pdf-wealth-report`, `document-summary`, `pptx-summary-deck`, contract redline |
| **Email draft** (human-in-the-loop comms) | `email-draft` for client letters, escalations, customer notices |
| **File sharing** (export) | `file-sharing` for handing the deliverable back to the user |

A persona built from "MCP reads + MCP writes + ask_user" alone is **one** kind, not three. It doesn't meet the bar.

### Validation checklist

Before opening a PR for a new use-case, demonstrate:

- [ ] Every `sampleQuestion` runs end-to-end against the live stack and produces a non-trivial answer
- [ ] The deliverable (PDF / packet / brief / draft) renders correctly and downloads cleanly via `file-sharing`
- [ ] At least one write workflow shows the agent draft → ask_user → execute → report
- [ ] At least one fallback branch is exercised (e.g. external service unreachable, no documents attached)
- [ ] Skills are routed via the SYSTEM_PROMPT.md table — not implicit "use what feels right"
- [ ] Cross-MCP / cross-skill joins are demonstrated where the persona claims them
- [ ] Evals — 5+ scenarios covering happy path, missing data, write-confirmation gate, refusal cases

---

## Audit: what shipped vs the bar

Since this roadmap was first written, five use-cases shipped that exhibit the thin shape. They're functional, but they don't earn the "differentiated demo" the roadmap promised. To be redone, not retired:

| Use-case | PR | Skills | Skill kinds | Deliverable | Verdict |
|---|---|---|---|---|---|
| `sales-account-review` | #5 | 5 | 1 (MCP only) | Inline brief, no PDF | **THIN** — was the pattern intro; acceptable as v1, needs PDF brief, web-search for company news, email-draft for outreach |
| `hr-onboarding` | #7 | 4 | 1 (MCP only) | Inline checklist | **THIN** — needs RAG over HR policy docs, PDF onboarding packet, email-draft for welcome notes, m365-graph for calendar invites |
| `it-service-desk` | #8 | 4 | 1 (MCP only) | Inline ticket update | **THIN** — needs KB RAG search, code-interpreter for log triage, email-draft for user comms |
| `retail-banking-csr` | #9 | 6 | 1 (MCP only) | Inline resolution note | **THIN** — *and* duplicates existing `retail-banking` (same bank, two doors). Either merge or rename to `retail-banking-internal`. Needs RAG over policy / dispute-rules docs, code-interpreter for fee calc, email-draft for customer notice, PDF resolution summary |
| `clinician-visit-prep` | #10 | 4 | 1 (MCP only) | Inline visit summary | **THIN** — needs RAG over clinical guidelines, PDF visit-prep doc, code-interpreter for lab-trend analysis, m365-graph for calendar context |

PR #11 (`finance-close`) was closed before merge for the same reason; will be redone to the bar as part of the rework wave.

**Reference implementations (the bar):**

| Use-case | Skills | Skill kinds | Deliverable |
|---|---|---|---|
| `wealth-management` | 10 | crm + portfolio-review + rag-search + code-interp + pdf + web + data-analysis + email + doc-summary + file-share | Polished PDF with KPI cards + SVG charts + compliance footer |
| `insurance` | 9 | crm + rag-search + claims-mgmt (pipeline w/ ARGUS fallback) + code-interp + data-analysis + web-search + email + doc-summary + file-share | Claim file + adjuster notes + cited policy wording |
| `retail-banking` | 13 | account-lookup + card-services + customer-profile + faq RAG + loan-calc (real amortisation) + product-catalog + transaction-history + code-interp + data-analysis + doc-summary + email + web + file-share | Loan schedule CSV, drafted complaint email |

---

## What's shipped

| Use-case | Vertical | MCP backing | Status |
|---|---|---|---|
| `generic` | horizontal utility | — (built-ins) | shipped — bar |
| `wealth-management` | FSI — wealth | — (skills only, fixture in CRM) | shipped — **bar** |
| `insurance` | FSI — insurance | — (skills only, fixture in CRM) | shipped — **bar** |
| `retail-banking` | FSI — banking | `faker-mcp-server` (data only) | shipped — **bar** on skills, faker on data (migrate data to `core-banking-mcp-server` without redoing skills) |
| `sales-account-review` | sales | `salesforce-mcp-server` ✅ | shipped — **thin**, redo |
| `hr-onboarding` | horizontal | `workday-mcp-server` ✅ | shipped — **thin**, redo |
| `it-service-desk` | horizontal | `servicenow-mcp-server` ✅ | shipped — **thin**, redo |
| `retail-banking-csr` | FSI — banking | `core-banking-mcp-server` ✅ | shipped — **thin** + duplicates `retail-banking`, merge or rename |
| `clinician-visit-prep` | healthcare | `epic-fhir-mcp-server` ✅ | shipped — **thin**, redo |

The MCP servers themselves (`salesforce`, `workday`, `servicenow`, `core-banking`, `epic-fhir`) are useful work — their fixtures are coherent and the tools are well-shaped. The personas built on top of them are what need depth.

---

## The 45 scenarios

Depth signal: 🔍 read-only briefing · ⚙️ multi-step workflow with writes + confirmations · 📄 produces a downloadable deliverable.

**Skill mix column** lists the *kinds* of skills the persona must exercise (not specific skill names — those are designed during build). Every persona must show **≥3 distinct kinds**.

### Sales (1 — shipped, thin)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 1 | **Sales Account Review** ⚠️ | Brief AE before customer call | `salesforce` | MCP + web + PDF + email | Account brief PDF + outreach draft 📄 |

### Horizontal back-office (5)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 2 | **HR Onboarding Specialist** ⚠️ | Hire new joiner → create Workday record → file IT tickets → book orientation → draft welcome email | `workday` + `servicenow` + `m365-graph` | MCP + RAG (HR policy) + PDF + email | Onboarding packet PDF + welcome email ⚙️📄 |
| 3 | **IT Service Desk L1** ⚠️ | Triage access ticket → check Entra → reset → grant → notify → close | `servicenow` + `entra-stub` | MCP + RAG (KB) + code-interp (log triage) + email | Resolved ticket + audit log + user notice ⚙️ |
| 4 | **Procurement Buyer** | Vet vendor + raise PO with credit/sanctions/contract checks | `sap-ariba` + `credit-bureau` | MCP + web (sanctions) + PDF + email | Vendor packet PDF + PO draft ⚙️📄 |
| 5 | **Finance Close Controller** | Q-end close: variance analysis + JE proposals + anomaly flags | `sap-s4` + `workday` + `concur` | MCP + data-analysis + PDF + email | Close summary PDF with charts ⚙️📄 |
| 6 | **Expense Approval Manager** | Bulk approve/reject team expenses with policy reasoning | `concur` + `workday` | MCP + RAG (policy) + data-analysis + email | Approval batch + policy-citation notes ⚙️ |

### Financial Services (5)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 7 | **Retail Banking CSR** ⚠️ *(merge with or rename vs `retail-banking`)* | Customer disputes charge → investigate → refund → cross-sell offer | `core-banking` + `salesforce` | MCP + RAG (dispute rules) + code-interp (fee calc) + PDF + email | Resolution summary PDF + offer email ⚙️📄 |
| 8 | **Wealth Advisor Pre-Meeting** *(migrates `wealth-management` data to MCP)* | Brief on client portfolio + risk + life events → reuse existing PDF report | `core-banking` + `market-data` | MCP + portfolio-review + PDF + web + email | Wealth report PDF 📄 |
| 9 | **Mortgage Underwriter** | Loan app → credit + income + property check → decision memo | `los` + `credit-bureau` | MCP + code-interp (DTI/LTV) + RAG (underwriting policy) + PDF | Decision memo PDF ⚙️📄 |
| 10 | **Insurance Claims Adjuster** *(migrates `insurance` data to MCP)* | FNOL → fraud signals → reserve → assign | `policy-claims` + `weather` | MCP + RAG (policy wording) + code-interp (fraud score) + email + file-share | Claim file + adjuster notes + cited wording ⚙️ |
| 11 | **AML Investigator** | Investigate suspicious activity alert → decide on SAR | `core-banking` + `sanctions-stub` | MCP + RAG (typology library) + data-analysis + PDF | SAR decision packet PDF ⚙️📄 |

### Healthcare (4)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 12 | **Clinician Visit Prep** ⚠️ | Pre-visit brief: history + labs + open issues + last visit | `epic-fhir` + `m365-graph` | MCP + RAG (guidelines) + code-interp (lab trend) + PDF | One-page visit-prep PDF 🔍📄 |
| 13 | **Prior Authorization Specialist** | Build PA packet with clinical evidence + cite payer policy | `epic-fhir` + `pubmed` + `payer-stub` | MCP + RAG (payer policy) + web (clinical lit) + PDF + email | PA submission packet PDF ⚙️📄 |
| 14 | **Care Coordinator Discharge** | Plan post-discharge: SNF + equipment + meds + family letter | `epic-fhir` + `skilled-nursing-stub` | MCP + RAG (discharge protocols) + PDF + email | Discharge plan PDF + family letter ⚙️📄 |
| 15 | **Pharma Medical Affairs** | Respond to physician unsolicited inquiry with cited literature | `pubmed` + `crm-stub` | MCP + web (PubMed) + RAG (label / promo policy) + PDF | Medical response letter PDF ⚙️📄 |

### Manufacturing (3)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 16 | **Plant Floor Supervisor** | "Why did Line 3 miss yesterday's target?" → sensors + lot history + supplier check | `azure-iot` + `sap-s4` + `servicenow` | MCP (cross-system) + data-analysis (sensor anomalies) + PDF + email | Incident brief PDF + supplier action 🔍📄 |
| 17 | **Supply Chain Planner** | Re-route around port closure → impact analysis + customer comms | `sap-s4` + `sap-ariba` + `weather` | MCP + web + data-analysis + email + PDF | Reroute plan PDF + customer notices ⚙️📄 |
| 18 | **Field Service Technician** | On-site diagnosis → parts order → close work order | `dynamics365` + `sap-s4` + `azure-iot` | MCP + RAG (service manuals) + code-interp (parts compatibility) + PDF | Service report PDF ⚙️📄 |

### Retail & CPG (3)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 19 | **Store Manager Morning Brief** | Yesterday's perf + today's staffing + shelf gaps → huddle agenda | `sap-retail` + `workday` + `azure-iot` | MCP + data-analysis + PDF | Store huddle agenda PDF 🔍📄 |
| 20 | **Merchandiser** | Re-allocate stock across stores based on demand + weather | `sap-retail` + `weather` | MCP + data-analysis + web + PDF | Allocation plan PDF ⚙️📄 |
| 21 | **CPG Brand Manager** | Launch new SKU: forecast + retail asks + media brief | `sap-retail` + `dynamics365` | MCP + data-analysis + PDF + pptx | Launch packet (PDF + deck) 📄 |

### Public Sector (3)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 22 | **Benefits Caseworker** | New applicant → eligibility check → decision letter | `dataverse` + `verification-stub` | MCP + RAG (eligibility rules) + PDF + email | Eligibility determination PDF ⚙️📄 |
| 23 | **City 311 Dispatcher** | Citizen complaint → triage → route → SLA → schedule | `servicenow` + `gis` | MCP + data-analysis + email | Dispatched work order + resident notice ⚙️ |
| 24 | **Tax Compliance Officer** | Audit risk score on filed return → exam plan | `dataverse` + `tax-stub` | MCP + RAG (tax code) + code-interp + PDF | Examination plan PDF ⚙️📄 |

### Government & Defense (2)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 25 | **Defense Logistics Officer** | Stage equipment for deployment → check readiness + transport + customs | `defense-logistics-stub` + `m365-graph` | MCP + RAG (regs) + data-analysis + PDF | Movement order PDF ⚙️📄 |
| 26 | **Intelligence Analyst Brief** | Synthesise OSINT + classified reports on a region → daily brief | `osint-stub` + `intel-archive-stub` | MCP + RAG + web + PDF | Daily brief PDF 🔍📄 |

### Energy & Utilities (2)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 27 | **Grid Storm Response** | Incoming storm → predict outages → dispatch crews + customer comms | `gis` + `weather` + `workday` | MCP + web + data-analysis + email | Dispatch plan + customer notices ⚙️📄 |
| 28 | **Oilfield Production Engineer** | Diagnose underperforming well → intervention recommendation | `azure-iot` + `sap-s4` | MCP + data-analysis + RAG (engineering refs) + PDF | Intervention plan PDF 🔍📄 |

### Telecom (2)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 29 | **Network Operations Triage** | Complaint cluster → correlate with network alarms → RCA + remediation | `servicenow` + `oss-stub` | MCP + data-analysis + RAG (runbooks) + PDF | Incident report PDF 🔍📄 |
| 30 | **Telco Account Manager** | Enterprise renewal: usage + outages + competitive risk → renewal pitch | `salesforce` + `oss-stub` | MCP + data-analysis + web + pptx + email | Renewal pitch deck ⚙️📄 |

### Education (2)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 31 | **Student Success Advisor** | Identify at-risk students → intervention plan + outreach drafts | `sis-lms` + `m365-graph` | MCP + data-analysis + RAG (policy) + email + PDF | Intervention plan PDF + outreach drafts ⚙️📄 |
| 32 | **University Admissions Reviewer** | Score application against rubric → committee recommendation | `sis-lms` + `transcripts-stub` | MCP + RAG (rubric) + doc-summary + PDF | Committee memo PDF ⚙️📄 |

### Professional Services (2)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 33 | **Engagement Manager** | Project status: time + budget + risks + open invoices → exec update | `workday` + `salesforce` + `m365-graph` | MCP (cross-system) + data-analysis + PDF + email | Status update PDF 🔍📄 |
| 34 | **Legal Counsel Contract Review** | Compare contract vs playbook → redline + risk summary | `ironclad-stub` + `m365-graph` | MCP + RAG (playbook) + doc-summary (redline) + email | Redlined contract + risk summary ⚙️📄 |

### Media & Entertainment (2)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 35 | **Newsroom Editor** | Story queue + breaking-news triage → publish-or-hold decisions | `newsroom-cms-stub` + `social-listening-stub` | MCP + web + data-analysis + email | Editor's daily plan 🔍📄 |
| 36 | **Streaming Content Programmer** | Slot upcoming releases against audience cohorts | `content-catalog-stub` + `audience-stub` | MCP + data-analysis + pptx | Programming grid + pitch deck ⚙️📄 |

### Transport & Logistics (2)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 37 | **Airline Operations Controller** | Weather + crew + aircraft → reaccommodate disrupted passengers | `flight-ops-stub` + `weather` + `crew-stub` | MCP + web + data-analysis + email | Disruption plan + passenger notices ⚙️📄 |
| 38 | **Fleet Logistics Dispatcher** | Plan routes for tomorrow's shipments → assign drivers + cost-out | `tms-stub` + `weather` + `workday` | MCP + web + data-analysis + PDF | Dispatch board PDF ⚙️📄 |

### Hospitality (2)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 39 | **Hotel Revenue Manager** | Tomorrow's pricing across rate codes → with forecast + comp set | `opera-pms-stub` + `rate-shop-stub` | MCP + web + data-analysis + PDF | Pricing plan PDF ⚙️📄 |
| 40 | **Restaurant Operations Manager** | Tomorrow's prep: forecast + staffing + supply ordering | `pos-stub` + `workday` + `supplier-stub` | MCP + data-analysis + email | Daily prep plan + supplier order ⚙️📄 |

### Life Sciences R&D (2)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 41 | **Clinical Trial Matcher** | Patient candidate → screen against active trials → outreach packet | `epic-fhir` + `clinicaltrials-stub` | MCP + RAG (protocols) + PDF + email | Match packet PDF ⚙️📄 |
| 42 | **Drug Discovery Researcher** | Compound + target → literature + safety + assay history | `pubmed` + `chembl-stub` + `assay-stub` | MCP + web + RAG + data-analysis + PDF | Research brief PDF 🔍📄 |

### Real Estate (1)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 43 | **Commercial Leasing Agent** | Match tenant brief to portfolio → tour plan + comps | `costar-stub` + `crm-stub` | MCP + web + data-analysis + PDF | Tour packet + comps PDF ⚙️📄 |

### Agriculture (1)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 44 | **Precision Ag Advisor** | Field-by-field treatment plan based on yield + weather + soil | `johndeere-stub` + `weather` + `soil-stub` | MCP + web + data-analysis + PDF | Application plan PDF ⚙️📄 |

### Nonprofit (1)

| # | Persona | Workflow | MCPs | Skill mix | Deliverable |
|---|---|---|---|---|---|
| 45 | **Major Gifts Officer** | Brief on prospect: giving history + wealth signals + interests → ask plan | `raisers-edge-stub` + `wealth-screening-stub` | MCP + web + RAG (giving guidance) + PDF | Donor brief PDF 🔍📄 |

⚠️ = shipped thin, needs rework against the bar before being demoable.

---

## MCP server catalog

18 production-grade MCPs + ~35 lighter stubs unlock all 45 use-cases. "Stub" means a small ~2-hour, single-purpose helper (e.g. `weather.get_forecast(zip)`); production-grade means full Salesforce-style coverage (~10 tools, coherent fixtures across 5–10 entities).

### Production-grade MCPs

| Server | Status | Powers use-cases |
|---|---|---|
| `salesforce-mcp-server` | ✅ shipped | 1, 7, 30, 33 |
| `workday-mcp-server` | ✅ shipped | 2, 5, 6, 19, 27, 33, 38, 40 |
| `servicenow-mcp-server` | ✅ shipped | 2, 3, 16, 23, 29 |
| `core-banking-mcp-server` | ✅ shipped | 7, 8, 11 |
| `epic-fhir-mcp-server` | ✅ shipped | 12, 13, 14, 41 |
| `m365-graph-mcp-server` | — | 2, 12, 25, 31, 33, 34 |
| `sap-s4-mcp-server` | (PR #11 closed; redo) | 5, 16, 17, 18, 28 |
| `sap-ariba-mcp-server` | — | 4, 17 |
| `concur-mcp-server` | — | 5, 6 |
| `azure-iot-mcp-server` | — | 16, 18, 19, 28 |
| `sap-retail-mcp-server` | — | 19, 20, 21 |
| `dynamics365-mcp-server` | — | 18, 21 |
| `gis-mcp-server` | — | 23, 27 |
| `dataverse-mcp-server` | — | 22, 24 |
| `los-mcp-server` | — | 9 |
| `policy-claims-mcp-server` | — | 10 |
| `sis-lms-mcp-server` | — | 31, 32 |
| `pubmed-mcp-server` | — | 13, 15, 42 |

### Lighter stubs

`credit-bureau`, `weather`, `market-data`, `entra`, `payer`, `verification`, `skilled-nursing`, `oss`, `sanctions`, `tax`, `defense-logistics`, `osint`, `intel-archive`, `transcripts`, `ironclad`, `newsroom-cms`, `social-listening`, `content-catalog`, `audience`, `flight-ops`, `crew`, `tms`, `opera-pms`, `rate-shop`, `pos`, `supplier`, `clinicaltrials`, `chembl`, `assay`, `costar`, `crm`, `johndeere`, `soil`, `raisers-edge`, `wealth-screening`.

### Reuse multiplier

The top 4 production MCPs alone (`workday`, `servicenow`, `m365-graph`, `sap-s4`) power 18 of 45 use-cases. Every production MCP pays back at least twice. The stubs are cheap glue, not the cost driver.

---

## Phasing

**Phase 0 — bar set + first MCPs shipped.** Reference implementations (`wealth-management`, `insurance`, `retail-banking`) live; 5 MCPs (`salesforce`, `workday`, `servicenow`, `core-banking`, `epic-fhir`) shipped.

**Phase 1 — Rework wave. Bring the five thin personas to the bar.** No new personas until this is done.

1. `sales-account-review` — add web-search (company news), PDF account-brief deliverable, email-draft for outreach
2. `hr-onboarding` — add RAG over HR policy docs, PDF onboarding packet, email-draft for welcome notes, integrate m365-graph for calendar invites
3. `it-service-desk` — add KB RAG search, code-interpreter for log triage, email-draft for user comms
4. `retail-banking-csr` — resolve overlap with `retail-banking` (merge or rename); add RAG over policy / dispute rules, code-interpreter for fee calc, email-draft for customer notice, PDF resolution summary
5. `clinician-visit-prep` — add RAG over clinical guidelines, PDF visit-prep doc, code-interpreter for lab-trend analysis, integrate m365-graph for calendar
6. `finance-close` (was PR #11) — rebuild against the bar before reopening: add data-analysis with charts, RAG over close-process policy, PDF close summary, email-draft for variance commentary

Builds the missing dependency: `m365-graph-mcp-server` (unlocks 6 use-cases — front-load it).

**Phase 2 — fill horizontals.** Once the rework wave is shipped, build #4 Procurement, #6 Expense Approval. All ride on existing MCPs + `sap-ariba`, `concur`, `entra-stub`, `credit-bureau`.

**Phase 3 — deepen verticals already opened.** Add 2nd–3rd persona per vertical using existing MCPs: #8, #9, #10, #11 (FSI), #13, #14, #15 (healthcare), #17, #18 (manufacturing), #20, #21 (retail), #33, #34 (proserv).

**Phase 4 — open remaining verticals.** Public sector (#22, #23, #24), gov-defense (#25, #26), energy (#27, #28), telecom (#29, #30), education (#31, #32), media (#35, #36), transport (#37, #38), hospitality (#39, #40), life sciences (#41, #42), real estate (#43), agriculture (#44), nonprofit (#45).

**Phase 5 — quality pass.** Tighten sample prompts so every persona has 3 proven demo scripts; confirm every use-case has a 📄 deliverable that downloads cleanly.

Within each phase, order follows MCP dependency: build the server, then drop in the use-case.

---

## How to add a new use-case

1. **Pick the MCP servers it needs.** If they all exist, skip to step 3.
2. **Add the missing MCP server(s)** under `mocks/packages/` — copy `salesforce-mcp-server` as the template. See [`mocks/README.md`](../mocks/README.md). Confirm fixture coherence with existing MCPs via stable IDs.
3. **Create `use-cases/<name>/`** with `SYSTEM_PROMPT.md` (including a **skill routing table**), `.mcp.json`, `apm.yml`, and `skills/<skill-name>/` for each skill. **Match the bar:** each skill is a directory with SKILL.md + optional `references/`, `scripts/`, `assets/`. Mix at least 3 skill kinds (see [Skill-mix requirement](#skill-mix-requirement)).
4. **Create the deliverable.** PDF / packet / brief / draft. Test it renders + downloads via `file-sharing`.
5. **Add evals.** 5+ scenarios covering happy path, missing data, write-confirmation gate, refusal cases.
6. **Add a row to "What's shipped"** and tick the matching row in "The 45 scenarios".
7. **Run the validation checklist** in [The quality bar](#the-quality-bar) end-to-end against the live local stack.
8. **Open a PR.** Include screenshots of the deliverable and a transcript of one sample prompt running end-to-end.

---

## Anti-patterns

- **Monoculture skill mix.** Persona built from "MCP reads + MCP writes + ask_user" alone. Does not meet the skill-mix requirement.
- **No deliverable.** If the agent doesn't produce something downloadable / shareable, the demo has no payoff moment. Inline chat tables don't count.
- **Thin SKILL.md.** A 30-line prompt is not a skill. See [Skill anatomy](#skill-anatomy) — production skills carry pipeline logic, fallbacks, code snippets, and reference content.
- **Faker-driven new use-cases.** Existing ones (`retail-banking` data layer) are being migrated, not extended. No new persona ships against Faker.
- **Overlapping personas.** `retail-banking` and `retail-banking-csr` both ground in "Olympus National Bank" with no audience distinction — viewer can't tell them apart. New personas must own a clear audience + system + workflow that no existing persona covers.
- **Skipping `sampleQuestions`.** Aspirational prompts are worse than no prompts. Every persona ships with three proven scripts.
- **Vertical-specific UI tweaks.** Differentiation comes from skills + MCPs + system prompt. Frontend stays generic.
- **Replicating Microsoft's actual Copilots.** Kratos is the accelerator that *customers and partners* use to build their own.
- **Shipping without end-to-end validation.** Build → docker compose up → run every sample question against the live stack → confirm the deliverable renders. Then PR.
