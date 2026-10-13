# `services/agent-relay/requirements-host.txt`

Source: [`services/agent-relay/requirements-host.txt`](../../../../../services/agent-relay/requirements-host.txt)

> **Summary:** The extra dependencies for the production host: the Microsoft 365 Agents SDK (`microsoft-agents-hosting-aiohttp`, `microsoft-agents-authentication-msal`, `microsoft-agents-activity`) and `aiohttp`. It includes `requirements.txt`.

The SDK versions are lower bounds (`>=0.5`), because they could not be resolved in the build environment. After the first successful `pip install` (`az acr build` does it), pin exact versions here so builds are reproducible. The [`Dockerfile`](Dockerfile.md) installs this file.
