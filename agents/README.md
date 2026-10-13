# Foundry agents (declarative YAML)

| File | Agent | Reached by | Tools |
| --- | --- | --- | --- |
| `triage.yaml` | `healthgen-triage` | Agent relay (Responses API through APIM) | A2A → both specialists, MCP `request_human_handoff` |
| `benefit-check.yaml` | `healthgen-benefit-check` | Triage over A2A 1.0 | HealthGen MCP (11 tools), AI Search |
| `plan-faq.yaml` | `healthgen-plan-faq` | Triage over A2A 1.0 | AI Search only (no PHI) |
| `connections.yaml` | Project connections | | AI Search, MCP, 2 × RemoteA2A |

## File format

The top-level fields mirror the Foundry Agent Service REST API (`api-version=v1`):

- `name`, `description`, `metadata`;
- `definition`, sent as-is: `kind: prompt`, `model`, `instructions`, `tools`;
- `a2a`: whether to enable incoming A2A, the `agent_card`, and an optional `enable_body` that overrides the PATCH body.

Placeholders:

- `${VAR}`: a value from `foundry.env` (see `foundry.env.example`) or the environment.
- `${conn:NAME}`: the ARM id of the project connection `NAME`.
- `{{> envelope}}`: the shared reply contract in `partials/envelope.md`.

## Deploying

```bash
python agents/deploy_agents.py --env-file agents/foundry.env --dry-run
python agents/deploy_agents.py --env-file agents/foundry.env [--skip-connections] [--only healthgen-triage]
```

The script deploys in this order:

1. Connections, through ARM `PUT`.
2. The specialists. `POST /agents` the first time, then `POST /agents/{name}/versions`.
3. Incoming A2A on the specialists (`PATCH /agents/{name}`, merge-patch), followed by a check that the agent card is served.
4. The triage agent.

Tokens come from `az account get-access-token`.

⚠️ The incoming-A2A PATCH body is not shown on the Microsoft Learn page. The script sends `{"agent_endpoint": {"protocol_configuration": {"responses": {}, "a2a": {}}}, "agent_card": {...}}`. If Foundry rejects it, put the documented body in `a2a.enable_body`.

## Rules every agent follows

- Reply with one JSON reply envelope (`partials/envelope.md`). The relay renders it.
- Pass `session_ref` from the `[turn-context]` block to every HealthGen tool. Never ask for or invent member ids.
- Point to cards with `card_ref`; don't restate card data in the reply.
- Book or refer only in two steps. Call `submit_*` only after the relay says the user confirmed that `action_id`. The broker and the core enforce this whatever the prompt says.
