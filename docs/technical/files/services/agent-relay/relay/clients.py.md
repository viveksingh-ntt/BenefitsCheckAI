# `services/agent-relay/relay/clients.py`

Source: [`services/agent-relay/relay/clients.py`](../../../../../../services/agent-relay/relay/clients.py)

> **Summary:** The relay's outbound HTTP clients for the identity broker, the MCP card store and Foundry (through APIM), plus credential helpers.

| | |
| --- | --- |
| Layer | Agent relay |
| Local run | Real. It talks to the local broker, MCP and `foundry-local` using dev keys. |
| Azure | Real. It talks to the internal broker and MCP, and to APIM, using managed identity tokens. |

## What it does

- **`BrokerClient`**
  - `resolve(dl_user_id, conversation_id)` returns a `Session` (`session_ref`, `role`, `portal`, `display_name`, `user_context_token`). The session is cached until one minute before the user-context token expires.
  - `get_action()` and `confirm_action()` support the confirmation flow.
  - `forget()` drops a cached session.
- **`CardClient.get(card_ref, session_ref)`** calls `GET /internal/cards/{ref}?session_ref=` on the MCP server. A 404 returns `None`.
- **`FoundryClient`**
  - `create_conversation()` calls `POST {base}/openai/v1/conversations`.
  - `run()` calls `POST {base}/openai/v1/responses` with `{"agent_reference": {"type": "agent_reference", "name", "version?"}, "conversation", "input": [message]}`.
  - Every call carries `Authorization` (the relay's credential) and `X-User-Context` (the broker JWT), plus an optional APIM subscription key.
  - It retries 429, 502, 503 and 504 up to twice, honouring `Retry-After` up to 10 s. The timeout is 120 s, because A2A plus MCP chains are slow.
- **`output_text()`** reads the assistant text from a Responses payload (`output_text`, or the last `message` item).
- **`token_provider(prefix)`** returns a credential function: `{PREFIX}_KEY` for dev, otherwise a managed identity token for `{PREFIX}_RESOURCE` (see `msi.py`).
- **`UpstreamError(status, code)`** is the single error type that `core.py` maps to user-facing replies.

Calls use stdlib `urllib` run in worker threads (`anyio.to_thread`), so the relay needs no HTTP client dependency. Localhost calls bypass environment proxies.

## Configuration (read via `factory.py`)

| Variable | Local | Azure |
| --- | --- | --- |
| `BROKER_URL` | `http://localhost:8102` | internal broker URL |
| `BROKER_KEY` / `BROKER_RESOURCE` | `dev-relay-key` | `api://healthgen-identity-broker` |
| `MCP_URL` | `http://localhost:8103` | internal MCP URL |
| `MCP_CARDS_KEY` / `MCP_CARDS_RESOURCE` | `dev-relay-cards-key` | `api://healthgen-mcp` |
| `FOUNDRY_BASE_URL` | `http://localhost:8105/api/projects/healthgen` | `https://<apim>.azure-api.net/foundry/api/projects/<project>` |
| `FOUNDRY_KEY` / `FOUNDRY_RESOURCE` | `dev-foundry-key` | `api://healthgen-agent-gateway` |
| `FOUNDRY_AGENT_NAME`, `FOUNDRY_AGENT_VERSION` | `healthgen-triage` | Pin a version in production |
| `APIM_SUBSCRIPTION_KEY` | – | Only if the APIM product requires one |

## How it's used in the real system

In Azure the relay never calls Foundry directly. APIM validates its token and the user context, then calls Foundry with APIM's own identity. Pinning `FOUNDRY_AGENT_VERSION` turns agent prompt changes into a controlled rollout.

## Related

[`core.py`](core.py.md) · [`factory.py`](factory.py.md) · [`msi.py`](msi.py.md) · [APIM agent gateway](../../../../files/apim/foundry-gateway.policy.xml.md)
