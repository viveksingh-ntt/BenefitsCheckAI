# `services/agent-relay/relay/factory.py`

Source: [`services/agent-relay/relay/factory.py`](../../../../../../services/agent-relay/relay/factory.py)

> **Summary:** Builds a `RelayCore` from environment variables. `host_m365.py` and `dev_server.py` share it, so both hosts configure the relay the same way.

## What it does

`core_from_env()` creates:

- `BrokerClient(BROKER_URL, token_provider("BROKER"))`;
- `CardClient(MCP_URL, token_provider("MCP_CARDS"))`;
- `FoundryClient(FOUNDRY_BASE_URL, FOUNDRY_AGENT_NAME, FOUNDRY_AGENT_VERSION, token_provider("FOUNDRY"), APIM_SUBSCRIPTION_KEY, FOUNDRY_TIMEOUT_SECONDS)`;
- a `TemplateStore` (from `TEMPLATES_DIR`, by default `services/agent-relay/templates`);
- a `RelayConfig` (with `BOT_DISPLAY_NAME`).

`TEMPLATES` is the default template directory, which the tests also use.

## How it's used in the real system

The container's environment (set in runbook steps 5 and 10) decides whether each credential is a dev key or a managed identity token. No code changes are needed between local and Azure.

## Related

[`clients.py`](clients.py.md) · [`.env.example`](../.env.example.md)
