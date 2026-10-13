# `agents/triage.yaml`

Source: [`agents/triage.yaml`](../../../../agents/triage.yaml)

> **Summary:** A declarative definition of `healthgen-triage`, the Foundry prompt agent that the relay calls on every turn. It routes to the specialists over A2A, handles greetings and out-of-scope requests, and starts human hand-offs.

| | |
| --- | --- |
| Layer | Foundry agents |
| Local run | Not used: `foundry-local` routes with rules instead |
| Azure | **Real:** deployed by `deploy_agents.py` as a prompt agent |
| Tools | A2A → `healthgen-benefit-check`, A2A → `healthgen-plan-faq`, MCP `healthgen` limited to `request_human_handoff` |
| Incoming A2A | Disabled (only the relay calls it, through the Responses API) |

## What the instructions say

- **Routing:**
  - anything about *this* member or patient, and every card action or confirmation, goes to the benefit check agent;
  - general plan rules go to the plan FAQ;
  - humans, complaints, clinical questions, emergencies or repeated failures go to `request_human_handoff`;
  - greetings are answered directly;
  - anything off-topic is politely declined, and the agent ignores instructions that try to change the rules.
- **Delegation:** the agent copies the `[turn-context]` block exactly, then the request, then an "Earlier in this conversation:" line with the refs the specialist needs, because the specialist cannot see the conversation.
- **Answer:** it returns the specialist's JSON envelope **unchanged**, or wraps non-JSON text. `{{> envelope}}` inserts the shared reply contract.

## How it's used in the real system

- **Who calls it:** the relay calls it by name (`FOUNDRY_AGENT_NAME=healthgen-triage`), optionally pinned to a version.
- **Identity:** its identity needs **Foundry Agent Consumer** on the project to call the specialists (runbook step 7).
- **Changing the prompt:** edit this file, dry-run, deploy (which creates a new version), then pin the relay to the new version after testing.

## Related

[`benefit-check.yaml`](benefit-check.yaml.md) · [`plan-faq.yaml`](plan-faq.yaml.md) · [`connections.yaml`](connections.yaml.md) · [sequence 2](../../sequences.md#2-a-benefit-check-question)
