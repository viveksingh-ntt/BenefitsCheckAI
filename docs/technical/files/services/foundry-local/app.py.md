# `services/foundry-local/app.py`

Source: [`services/foundry-local/app.py`](../../../../../services/foundry-local/app.py)

> **Summary:** A local stand-in for **APIM plus Foundry Agent Service** (and the n8n webhook). It speaks the same HTTP contract as the real ones, so the relay, MCP server, broker and widget run unchanged on a laptop. It is a scripted router, **not an LLM**.

| | |
| --- | --- |
| Layer | APIM agent gateway, Foundry agents, AI Search and n8n (**local stand-ins**) |
| Local run | Used: `uvicorn app:app --port 8105` |
| Azure | **Not deployed.** Replaced by APIM ([`apim/foundry-gateway.policy.xml`](../../../files/apim/foundry-gateway.policy.xml.md)), Foundry agents ([`agents/*.yaml`](../../../files/agents/triage.yaml.md)), AI Search and n8n. |

## What it does

- **Gateway checks (`gateway`)**, like the APIM policy:
  - `Authorization` must equal `FOUNDRY_LOCAL_KEY`;
  - `X-User-Context` must be a valid broker JWT (issuer, audience `healthgen-agent-gateway`, broker JWKS);
  - `/responses` accepts only `agent_reference.name == FOUNDRY_AGENT_NAME`, with no `model`, `instructions` or `tools` in the body.
- **Foundry API surface:**
  - `POST /api/projects/{project}/openai/v1/conversations` returns `{id}`;
  - `POST …/responses` returns `{output: [{type: message, content: [{type: output_text, text: <envelope JSON>}]}]}`.
- **`Scripted.answer`:** it reads `session_ref` and `portal` from the `[turn-context]` block and keeps per-conversation memory (service, provider, slot, ZIP, radius). Rules in order:
  1. confirmations → `submit_*`;
  2. a human or "Talk to a person" → `request_human_handoff`;
  3. `appointment.review` → prepare a booking;
  4. `referral.review` → prepare a referral;
  5. availability;
  6. doctor and provider searches;
  7. plan FAQ (keyword search over `search/documents` through `PlanSearch`, using `ingest.chunks`);
  8. deductible → accumulators;
  9. coverage and cost → `check_benefits`;
  10. service search;
  11. help text.

  Each rule calls the **real MCP server** through the real MCP client, and returns the same envelope shape the real agents produce.
- **`POST /webhook/healthgen-handoff`:** a hand-off stub that returns a random `HO-` ticket. It does not check the signature; the real n8n workflow does.

## Configuration

`BROKER_ISSUER`, `BROKER_JWKS_URL`, `MCP_URL`, `MCP_KEY`, `FOUNDRY_LOCAL_KEY`, `FOUNDRY_PROJECT` (default `healthgen`) and `FOUNDRY_AGENT_NAME` (default `healthgen-triage`).

## How it's used in the real system

It isn't. Use it to exercise identity, cards, human confirmation, roles and hand-off end to end, and in CI. Judge conversation quality only against the real agents in Foundry (playground or a pilot deployment).

## Related

[`requirements.txt`](requirements.txt.md) · [sequence 10](../../../sequences.md#10-local-stack-and-automated-tests)
