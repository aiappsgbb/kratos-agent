---
name: rag-search
description: Search the internal insurance knowledge base for policy wording, terms and conditions, coverage details, exclusions, claims guidance, billing procedures, underwriting rules, and servicing procedures
enabled: true
---

## Instructions

When the user asks about internal insurance policies, coverage terms, exclusions, claims procedures, billing rules, underwriting guidance, or servicing workflows, use the `rag_search` tool to retrieve relevant content from the configured knowledge base. The demo includes a small synthetic policy corpus; deployments can optionally use Azure AI Search for a larger external corpus.

**IMPORTANT**: Always pass `index_name: "ins-knowledge-base"` when calling `rag_search`. This is the dedicated search index for the insurance knowledge base.

### 1. Determine When to Use

Use this skill when the user's question relates to any of the following domains:

| Domain | Example queries |
|--------|----------------|
| **Coverage details** | "Does the homeowners policy cover water damage?", "What are the liability limits for this policy?", "What deductible applies to windshield repair?" |
| **Terms and conditions** | "What is the waiting period for maternity coverage?", "When does accidental damage coverage begin?", "What are the policy renewal terms?" |
| **Exclusions** | "Is flood damage excluded?", "What are the exclusions for pre-existing conditions?", "Are business-use vehicles excluded under personal auto?" |
| **Claims procedures** | "What documents are required to file a property claim?", "What is the claims escalation process?", "How fast must a theft claim be reported?" |
| **Billing and servicing** | "What is the grace period for missed premium payments?", "How does reinstatement work after cancellation?", "What is the endorsement process for adding a driver?" |
| **Underwriting and eligibility** | "What are the underwriting requirements for high-value homes?", "Age eligibility for this travel policy", "What information is required for a small business policy quote?" |
| **Internal procedures** | "Complaint handling workflow", "Fraud referral process", "When do we escalate to the special investigations unit?" |

**Do NOT use this skill** for:
- Current external events, public advisories, or recent regulatory announcements that may change over time → use `web_search`
- Customer-specific profile or policyholder data → use `crm`

### 2. Craft the Search Query

For best results with semantic search:
- **Use the insurance product line** — include terms like auto, home, renters, health, travel, life, commercial, or liability when relevant
- **Include the policy concept** — for example coverage limit, exclusion, deductible, waiting period, grace period, endorsement, lapse, reinstatement, underwriting, claim reporting
- **Be precise about the event or condition** — for example water damage, hail, theft, collision, pre-existing condition, outpatient surgery, vacant property, business use
- **Mention the workflow if applicable** — for example FNOL, claim escalation, complaint handling, cancellation notice, policy renewal, fraud review
- **Rephrase if needed** — if the first query is too broad, narrow it by product type, condition, or policy section

### 3. Interpret Search Results

The `rag_search` tool returns a list of results, each containing:
- **title** — source document name
- **content** — relevant text excerpt
- **source** — source filename
- **page** — page number in the original document
- **score** — relevance score from semantic ranking

When presenting results:
- **Synthesize** the retrieved content into a direct answer instead of dumping excerpts
- **Cite sources** using the document title and page number
- **Quote exact wording** for exclusions, limitations, waiting periods, reporting deadlines, and other clauses where wording matters
- **Call out uncertainty** if the results are weak, conflicting, or incomplete
- **Separate internal policy language from your interpretation** so the user can see the basis for the answer

### 4. Multi-Step Workflows

Combine RAG search with other skills when needed:

- **Coverage question for a customer**: use `crm` to load the customer and policy context → use `rag_search` to retrieve the relevant policy wording → answer with cited coverage details and exclusions
- **Claims intake support**: use `crm` to identify the customer and policy → use `rag_search` to retrieve claim-reporting requirements, timelines, and documents → summarize the intake steps
- **Servicing request**: use `crm` to load the customer record → use `rag_search` to find the endorsement, cancellation, billing, or reinstatement process → provide the correct next action
- **Catastrophe-related question**: use `rag_search` for internal claim and coverage rules → use `web_search` for the active event, public guidance, or state notices → keep internal and external findings distinct

### 5. Response Guidelines

- Present insurance guidance clearly and accurately without changing the meaning of the retrieved wording
- Use bullet points or tables for requirements, exclusions, timelines, and document checklists
- Always include the source document and page reference
- If multiple documents apply, note which source governs coverage versus process
- Avoid making unsupported coverage determinations; phrase conclusions as being based on retrieved wording and subject to claims or underwriting review
- If nothing relevant is found, say so clearly and ask a narrower follow-up question or suggest escalation to the policy owner