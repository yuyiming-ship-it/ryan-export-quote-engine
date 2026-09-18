---
name: export-quote
description: Calculate and compare auditable vehicle export quotations, prepare customer-safe drafts and MOSS copy packages. Use for vehicle source, transport, funding, centralized procurement and export pricing requests.
---

# Export Quote

Use the configured `export_quote` MCP tools. Never calculate final money mentally or with an LLM.

1. Read the inquiry and call `normalize_request`. Preserve every source and keep unknown values absent rather than zero.
2. Gather missing vehicle configuration, quantity, delivery place, trade/payment terms, quote validity, vehicle price, transport legs, funding stages, FX, tax basis, payer, inclusions, allocation and profit target. Ask related missing items together.
3. Mark evidence `confirmed`, `estimated`, `pending`, `historical`, `expired` or `conflict`. An estimate needs its assumption. Do not use pending/conflicting/expired evidence for a live quote.
4. Call `validate_quote`; resolve every error. A `conditional` result must show assumptions and missing owners. Do not present it as confirmed.
5. Call `calculate_quote` for each option and `compare_quotes` only when transaction boundaries match. Do not force a ranking when delivery time or own advance is unknown.
6. Present the internal cost table and evidence first. After the user selects a plan, create the customer-safe draft and call `export_moss`.
7. Never expose procurement cost, funding policy, profit, split, internal sources or customer data in customer content. Never submit MOSS, change inventory or approve a rule.

Trade terms do not imply a fixed fee list. Use the actual named delivery place and stated inclusions. A settlement/contract price is an output and must not be added again as a cost.

If tools are unavailable, stop before stating a calculated quote and explain which MCP configuration is missing.
