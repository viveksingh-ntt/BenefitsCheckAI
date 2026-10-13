# `agents/deploy_agents.py`

Source: [`agents/deploy_agents.py`](../../../../agents/deploy_agents.py)

> **Summary:** Deploys the declarative agents and connections to a Foundry project: it fills in placeholders, PUTs the connections, creates the agents or new agent versions, and enables incoming A2A on the specialists. It needs PyYAML and the Azure CLI only.

## Usage

```bash
python agents/deploy_agents.py --env-file agents/foundry.env --dry-run   # print every request
python agents/deploy_agents.py --env-file agents/foundry.env [--skip-connections] [--only healthgen-triage]
```

## What it does

1. **`load_env_file`:** reads `foundry.env` and the environment, checks the required settings, and derives `PROJECT_ENDPOINT`.
2. **`resolve`:** fills `${VAR}`, `${conn:NAME}` (the connection's ARM id) and `{{> partial}}` (`partials/*.md`). **`agent_body`** refuses anything left unresolved.
3. **`deploy_connections`:** PUTs every entry in `connections.yaml` to ARM.
4. **`deploy_agent`**, in the order plan FAQ, benefit check, triage:
   - `GET /agents/{name}?api-version=v1`;
   - if the agent is new, `POST /agents` with `{name, definition, description, metadata}`;
   - otherwise, `POST /agents/{name}/versions`;
   - if `a2a.enabled`, `PATCH /agents/{name}` (merge-patch: `agent_endpoint.protocol_configuration` with `responses` and `a2a`, plus `agent_card`), then a check that `agentCard/v1.0` is served.
5. **`Http.token`:** `az account get-access-token --resource https://ai.azure.com` (or `https://management.azure.com`), or `FOUNDRY_TOKEN` and `ARM_TOKEN` when set.

## How it's used in the real system

Run it from a pipeline or an operator machine whenever an agent YAML changes. Each run creates a new agent version. The relay keeps using its pinned `FOUNDRY_AGENT_VERSION` until you change it.

⚠️ The incoming-A2A PATCH body is not shown on Microsoft's page. If Foundry rejects it, set `a2a.enable_body` in the agent YAML.

## Related

[`agents/README.md`](README.md.md) · [sequence 9](../../sequences.md#9-deploying-agents-and-plan-documents) · runbook step 7
