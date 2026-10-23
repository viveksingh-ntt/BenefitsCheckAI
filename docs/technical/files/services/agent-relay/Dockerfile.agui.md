# `services/agent-relay/Dockerfile.agui`

Source: [`services/agent-relay/Dockerfile.agui`](../../../../../services/agent-relay/Dockerfile.agui)

> **Summary:** Container image for the relay's AG-UI host: runs `uvicorn host_agui:app` on port 8106 as a non-root user, with a 75 s keep-alive for long SSE responses.

| | |
| --- | --- |
| Layer | Agent relay (AG-UI path) |
| Azure | Built with `az acr build ... -f services/agent-relay/Dockerfile.agui` |

See the deploy delta in [AG-UI](../../../../ag-ui.md). The Direct Line image ([`Dockerfile`](../../../files/services/agent-relay/Dockerfile.md)) is unchanged.
