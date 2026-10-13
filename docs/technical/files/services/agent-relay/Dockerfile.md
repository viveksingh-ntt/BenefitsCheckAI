# `services/agent-relay/Dockerfile`

Source: [`services/agent-relay/Dockerfile`](../../../../../services/agent-relay/Dockerfile)

> **Summary:** The container image of the Agent relay for Azure Container Apps. It runs `python host_m365.py` on port 3978 as a non-root user.

What it does:

1. Starts from `python:3.13-slim`.
2. Installs `requirements-host.txt`.
3. Copies `relay/`, `templates/`, `host_m365.py` and `dev_server.py`.
4. Runs as UID 10001 and exposes port 3978.

Build it in Azure with `az acr build -r $ACR -t healthgen/agent-relay:0.1.0 services/agent-relay` (runbook step 4). The same image can run the emulator for a shared dev environment by overriding the command: `uvicorn dev_server:app --port 8104`.

The Bot Service JWT middleware guards every HTTP route, so give the container a TCP health probe.
