# `services/mcp-healthgen/requirements.txt`

Source: [`services/mcp-healthgen/requirements.txt`](../../../../../services/mcp-healthgen/requirements.txt)

> **Summary:** Pinned dependencies: `mcp==2.2.0` (MCP Python SDK v2, which also brings `httpx2`), `starlette`, `uvicorn[standard]`, `PyJWT[crypto]`, `cryptography`, `pydantic` and `anyio`.

The server targets MCP SDK 2.x (`mcp.server.mcpserver.MCPServer`). The 1.x `FastMCP` import path does not exist in 2.x.
