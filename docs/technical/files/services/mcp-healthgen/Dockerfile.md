# `services/mcp-healthgen/Dockerfile`

Source: [`services/mcp-healthgen/Dockerfile`](../../../../../services/mcp-healthgen/Dockerfile)

> **Summary:** The container image of the MCP data spoke: `python:3.13-slim`, run as UID 10001 with `uvicorn app.main:app --port 8103`.

Deploy it on internal ingress with one replica (the card store is in memory) and the `id-mcp` identity. APIM fronts it for Foundry (runbook steps 5 and 9).
