# `apim/mcp-gateway.policy.xml`

Source: [`apim/mcp-gateway.policy.xml`](../../../../apim/mcp-gateway.policy.xml)

> **Summary:** The APIM policy for the **MCP gateway** (Foundry → HealthGen MCP). It accepts only the Foundry project's managed identity, only `POST /mcp`, applies limits, and calls the MCP server with APIM's identity.

| | |
| --- | --- |
| Local run | Not used: `foundry-local` calls MCP directly with a dev key |
| Azure | **Real:** the `healthgen-mcp` API, path `/mcp/healthgen`, backend the internal MCP container app |

## Inbound steps

1. `validate-jwt`: an Entra token with audience `api://healthgen-mcp` and `appid` equal to `{{foundry-project-mi-client-id}}`.
2. Only `POST …/mcp` (405 otherwise; the server runs stateless with JSON responses, so there is no GET SSE stream). Bodies over 64 KB get 413.
3. `rate-limit-by-key`: 300 calls a minute per caller IP.
4. `authentication-managed-identity` for `api://healthgen-mcp`. The MCP server lists APIM in `MCP_CLIENTS`.

Backend timeout is 95 s, under Foundry's MCP timeout of about 100 s.

## Why the token exchange is not in APIM

The RFC 8693 exchange needs `session_ref` and `action_id` from inside the MCP JSON-RPC body, and the write path must consume the confirmation atomically. The MCP server therefore does the exchange against the broker for each tool call, and APIM validates the caller and applies the limits.
