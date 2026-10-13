# `services/mcp-healthgen/app/msi.py`

Source: [`services/mcp-healthgen/app/msi.py`](../../../../../../services/mcp-healthgen/app/msi.py)

> **Summary:** Gets managed identity tokens (Container Apps identity endpoint, falling back to IMDS) so the MCP server can authenticate to the broker in Azure. It is a copy of the relay's [`msi.py`](../../../../files/services/agent-relay/relay/msi.py.md).

It is used only when `BROKER_CLIENT_KEY` is not set. It then requests a token for `BROKER_ENTRA_RESOURCE` (`api://healthgen-identity-broker`) as `AZURE_CLIENT_ID` (`id-mcp`).
