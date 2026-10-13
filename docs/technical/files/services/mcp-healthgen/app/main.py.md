# `services/mcp-healthgen/app/main.py`

Source: [`services/mcp-healthgen/app/main.py`](../../../../../../services/mcp-healthgen/app/main.py)

> **Summary:** Builds the MCP server: Streamable HTTP at `/mcp` (stateless, JSON responses), a guard that authenticates callers, and the internal card endpoint the relay uses.

| | |
| --- | --- |
| Run | `uvicorn app.main:app --port 8103` |
| SDK | `mcp` 2.2 (`MCPServer`, `streamable_http_app`) |

## What it does

- **`create_app(deps?, mcp_auth?, internal_auth?, allowed_hosts?)`:**
  - creates `MCPServer("healthgen-data")` with server instructions and registers the tools (`tools.register`);
  - mounts it with `stateless_http=True`, `json_response=True` and DNS-rebinding protection (`MCP_ALLOWED_HOSTS`);
  - adds `GET /internal/cards/{card_ref}?session_ref=` (relay only) and `GET /healthz`.
- **`GuardMcp`:** an ASGI middleware that rejects `/mcp` requests without a valid credential (401 with `WWW-Authenticate`) before they reach the MCP session manager.
- **`Authenticator`:**
  - `entra`: validates an Entra token for `{PREFIX}_AUDIENCES` and maps `azp`/`appid` to a caller through `{PREFIX}_CLIENTS`;
  - `keys`: dev keys, as a Bearer token or `x-mcp-key`;
  - `none`: local only.
  - The two instances use the prefixes `MCP` (for `/mcp`) and `INTERNAL` (for `/internal`).
- **`credential_from_env()`** chooses how this server authenticates to the broker.

## How it's used in the real system

- **Who calls it:** Foundry's MCP tool calls APIM (`/mcp/healthgen/mcp`), authenticated with the project managed identity. APIM validates that identity and calls this server with APIM's own identity, so `MCP_CLIENTS` lists APIM. The relay calls `/internal/cards` directly inside the Container Apps environment, so `INTERNAL_CLIENTS` lists the relay.
- **Hosts:** set `MCP_ALLOWED_HOSTS` to the hosts APIM uses.
- **Timeouts:** Foundry gives MCP calls about 100 s; the tools are designed to finish within a few seconds.
