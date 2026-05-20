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

1. **Real system names always.** "Workday", not "HRIS". Brand recognition is
   half the demo.
2. **Fixture-backed mocks, not Faker.** Each MCP server ships a coherent
   fictional world with stable IDs. The same employee `EMP-1247` shows up
   across HR, IT, and Finance demos because they all read from the same
   `workday-mcp-server` fixtures.
3. **Skills get composed, not duplicated.** A new use-case is mostly
   `SYSTEM_PROMPT.md` + an `.mcp.json` choosing which existing servers to
   wire in. New MCP servers are the only thing that costs real time.
4. **One use-case answers one boardroom question.** "Brief me before my 3pm
   call." "Why did the plant miss yesterday's target?" "Is this patient
   ready for discharge?" Not "explore the data."
5. **Every persona produces a deliverable.** Brief, draft, report,
   dashboard. The wealth-management PDF report is the bar.
6. **Each use-case ships with a working demo script.** Three sample prompts
   in the `sampleQuestions` frontmatter, all proven end-to-end against
   the fixtures — not aspirational.
7. **Cross-persona demos.** Fixtures are designed so a single client
   storyline can walk through 2–3 personas (Store Manager → HR Helpdesk →
   Finance Close) on the same fictional company.

## What's shipped

| Use-case | Vertical | MCP servers | Status |
|---|---|---|---|
| `generic` | horizontal | (built-ins) | shipped |
| `retail-banking` | FSI — banking | faker | shipped (faker-driven — flag for migration) |
| `wealth-management` | FSI — wealth | faker | shipped (faker-driven — flag for migration) |
| `insurance` | FSI — insurance | faker | shipped (faker-driven — flag for migration) |
| `sales-account-review` | horizontal — sales | salesforce | shipped (fixture-backed) |

## MCP server catalog

The expensive bit. Build these first and use-cases drop off the conveyor.

| Server | Domain | Reused by |
|---|---|---|
| `salesforce-mcp-server` ✅ | CRM | sales-account-review, customer-service |
| `workday-mcp-server` | HRIS + finance | hr-helpdesk, finance-close, manager-co-pilot |
| `servicenow-mcp-server` | ITSM + workflows | it-service-desk, customer-service, hr-helpdesk |
| `sap-s4-mcp-server` | ERP — finance & procurement | finance-close, procurement, plant-ops |
| `dynamics365-mcp-server` | CRM + field service | field-service-tech, marketing-ops |
| `m365-graph-mcp-server` | Email / calendar / files | every persona (universal context) |
| `github-mcp-server` | Code & PRs | devex-oncall |
| `datadog-mcp-server` | Observability | devex-oncall, sre-incident |
| `epic-fhir-mcp-server` | Healthcare records | patient-visit-prep, care-coordinator |
| `azure-iot-mcp-server` | Sensors / telemetry | plant-ops, energy-ops |
| `shopify-mcp-server` | E-commerce / retail | retail-store-manager |
| `dataverse-mcp-server` | Power Platform data | public-sector-caseworker |

10 net-new servers unlock 12+ use-cases. Each new server pays for itself ≥2×.

## Use-case roadmap

Three waves, ordered by leverage. Times below assume the
`salesforce-mcp-server` template — once you've built one, the next is faster.

### Wave 1 — horizontals every field SE needs

| Use-case | Persona | MCP servers | New work |
|---|---|---|---|
| HR Helpdesk | Employee self-service | workday + servicenow | both MCPs + 5 skills |
| IT Service Desk | L1 triage | servicenow + m365-graph | m365-graph MCP + 5 skills |
| Finance Close Assistant | Controller | sap-s4 + workday + m365-graph | sap-s4 MCP + 5 skills |
| Customer Service Agent | Contact-centre rep | servicenow + salesforce + kb-search | 5 skills (all MCPs exist) |

### Wave 2 — flagship verticals Microsoft sells hardest

| Use-case | Vertical | MCP servers | New work |
|---|---|---|---|
| Patient Visit Prep | Healthcare | epic-fhir + m365-graph | epic-fhir MCP + 5 skills |
| Plant Operations Co-pilot | Manufacturing | sap-s4 + azure-iot + servicenow | azure-iot MCP + 5 skills |
| Retail Store Manager | Retail | shopify + workday + m365-graph | shopify MCP + 5 skills |

### Wave 3 — strategic fill-ins

| Use-case | Vertical | MCP servers | New work |
|---|---|---|---|
| Public Sector Caseworker | Gov | dataverse + servicenow + kb | dataverse MCP + 5 skills |
| DevEx On-call | Horizontal (tech) | github + datadog | both MCPs + 5 skills |
| Field Service Technician | Field service | dynamics365 + sap-s4 + azure-iot | dynamics365 MCP + 5 skills |
| Marketing Campaign Ops | Horizontal | dynamics365 + m365-graph | 5 skills (MCPs exist) |

## Execution rhythm

The first use-case (`sales-account-review` + `salesforce-mcp-server`) was
built in **one session**. Calibrate the rest against that:

| Work | Time |
|---|---|
| New MCP server (≈10 tools, curated fixtures) | half a day |
| New use-case riding on existing MCPs (system prompt + 5 SKILL.md + `.mcp.json`) | a couple of hours |
| Use-case that needs a brand-new MCP server | half a day plus the couple of hours |

Translation: **Wave 1 is roughly a week.** Wave 2 adds another. Wave 3 is mostly
filling in use-cases on top of MCPs that already exist.

Recommended order:

1. `workday-mcp-server` + `servicenow-mcp-server` (half a day each).
2. `hr-helpdesk` and `it-service-desk` use-cases back-to-back on top of them.
3. `sap-s4-mcp-server` + `finance-close-assistant`.
4. Review with the field. Confirm priorities for Wave 2.

## Anti-patterns to avoid

- **Faker-driven use-cases.** Existing FSI personas (retail-banking,
  wealth-management, insurance) work for visual demos but fail under
  scripted scenarios because the data drifts every call. New use-cases
  must be fixture-backed; the FSI three should be migrated when bandwidth
  allows.
- **Vertical-specific UI tweaks.** Differentiation comes from skills + MCPs +
  system prompt, not from forking the chat surface. Keep the frontend generic.
- **Replicating Microsoft's actual Copilots.** Kratos is the *accelerator*
  that customers and partners use to build their own. It should look
  inspired by Copilot, not derivative of any specific Copilot SKU.
- **Skills that improvise data.** A SKILL.md that says "use Faker to invent
  it" is a hint the wrong MCP coverage is in place. Add a real-named MCP
  instead.
- **Use-cases without a demo script.** If you can't write three
  `sampleQuestions` that work end-to-end against the fixtures, the
  use-case isn't ready.

## How to add a new use-case

1. **Pick the MCP servers it needs.** If they all exist, skip to step 3.
2. **Add the missing MCP server(s)** under `mocks/packages/` — copy
   `salesforce-mcp-server` as the template. See [`mocks/README.md`](../mocks/README.md).
3. **Create `use-cases/<name>/`** with `SYSTEM_PROMPT.md`, `.mcp.json`,
   `apm.yml`, and `skills/<skill-name>/SKILL.md` for each skill. Each
   SKILL.md names the specific MCP tools to call.
4. **Add a row to "What's shipped"** above.
5. **Test end-to-end locally** via `./run-local.sh` + the frontend, hitting
   each `sampleQuestions` prompt.
6. **Open a PR** with a screenshot of the agent driving the new use-case.

## Open questions

- Who is the primary user — Microsoft field SE giving live demos, or
  solution architect building customer POCs? Answer shapes how scripted
  vs. extensible each use-case should be.
- Should the faker-driven FSI personas be migrated, retired, or left
  alone? They have brand value (Olympus National Bank, etc.) but the
  data model is incoherent across calls.
- Where does Copilot Studio fit? Could Kratos publish skills *as* Copilot
  Studio plugins so the same MCP investment serves both?
