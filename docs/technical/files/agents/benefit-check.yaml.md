# `agents/benefit-check.yaml`

Source: [`agents/benefit-check.yaml`](../../../../agents/benefit-check.yaml)

> **Summary:** A declarative definition of `healthgen-benefit-check`, the specialist for member-specific coverage, finding care, availability, booking and referrals. It uses the HealthGen MCP tools and the plan-document index.

| | |
| --- | --- |
| Layer | Foundry agents |
| Local run | Not used (scripted in `foundry-local`) |
| Azure | **Real** prompt agent with incoming A2A enabled |
| Tools | MCP `healthgen` (11 allowed tools, `require_approval: never`), `azure_ai_search` (`${SEARCH_INDEX_NAME}`, semantic, top 4) |
| Data classification | PHI |

## What the instructions say

- Pass `session_ref` from `[turn-context]` to every tool, and never invent one. In the provider portal, talk about "the patient" and offer referrals, not bookings.
- When to use each tool, and the typical flows behind the prototype screens.
- Writes are **two-step**. Call `prepare_*`, then stop and ask the user to confirm in the card. Call `submit_*` only when the request says that `action_id` was confirmed.
- How to explain tool errors (`confirmation_required`, `slot_taken`, `upstream_unreachable`) without technical details.
- The shared envelope contract (`{{> envelope}}`).

## Why `require_approval: never`

Foundry's MCP approval flow would ask the *relay* to approve tool calls, without the user. Human approval is enforced instead by the review card and the broker and core checks, which the model cannot bypass. Read tools need no approval.

## How it's used in the real system

- **Who calls it:** only the triage agent, through the `a2a-benefit-check` connection.
- **Agent card:** the `a2a.agent_card` block (description and skills) is published at `…/endpoint/protocols/a2a/agentCard/v1.0`.
- **Adding a tool:** add it to `allowed_tools` and describe when to use it in the instructions.
