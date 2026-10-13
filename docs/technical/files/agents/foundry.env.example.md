# `agents/foundry.env.example`

Source: [`agents/foundry.env.example`](../../../../agents/foundry.env.example)

> **Summary:** A template of the settings `deploy_agents.py` needs: subscription, resource group, Foundry account and project, model deployment, MCP URL and audience, and the search service and index.

Copy it to `agents/foundry.env` (runbook step 7 writes it for you) and pass it with `--env-file`. The values are not secrets. `PROJECT_ENDPOINT` is derived as `https://{FOUNDRY_ACCOUNT}.services.ai.azure.com/api/projects/{FOUNDRY_PROJECT}` unless you set it.
