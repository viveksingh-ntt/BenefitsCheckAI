# `agents/connections.yaml`

Source: [`agents/connections.yaml`](../../../../agents/connections.yaml)

> **Summary:** The Foundry project connections that the agents reference as `${conn:NAME}`: AI Search, the HealthGen MCP server, and two RemoteA2A connections to the specialists.

| Connection | Category and auth | Target |
| --- | --- | --- |
| `healthgen-search` | `CognitiveSearch`, `AAD` (project identity, which needs Search Index Data Reader) | `https://${SEARCH_SERVICE_NAME}.search.windows.net` |
| `healthgen-mcp` | `RemoteTool`, `ProjectManagedIdentity`, audience `${MCP_AUDIENCE}` | `${MCP_SERVER_URL}` (the APIM MCP gateway) |
| `a2a-benefit-check` | `RemoteA2A`, `AgenticIdentityToken`, audience `https://ai.azure.com` | `${PROJECT_ENDPOINT}/agents/healthgen-benefit-check/endpoint/protocols/a2a` |
| `a2a-plan-faq` | same | `…/agents/healthgen-plan-faq/endpoint/protocols/a2a` |

`deploy_agents.py` PUTs each `properties` block to ARM (`…/projects/{p}/connections/{name}?api-version=2025-04-01-preview`).

⚠️ The `healthgen-mcp` category and auth type are written from the documentation. If ARM rejects them, create the connection with `azd ai connection create --kind remote-tool --auth-type project-managed-identity` (runbook step 7) and rerun with `--skip-connections`.
