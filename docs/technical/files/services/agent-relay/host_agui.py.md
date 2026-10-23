# `services/agent-relay/host_agui.py`

Source: [`services/agent-relay/host_agui.py`](../../../../../services/agent-relay/host_agui.py)

> **Summary:** The relay's AG-UI host, an alternative to `host_m365.py` + Bot Service + Direct Line: `POST /agui/run` streams AG-UI events over SSE, and `GET /agui/threads/{id}` restores a thread.

| | |
| --- | --- |
| Layer | Agent relay (host, AG-UI path) |
| Local run | **Real**: `uvicorn host_agui:app --port 8106` |
| Azure | **Real**: the `ca-relay-agui` Container App (`Dockerfile.agui`) |

## What it does

- **`ChatTokenVerifier`** checks the broker's chat token: RS256 against the broker JWKS, `iss`, `aud=healthgen-agui`, required `exp`/`sub`/`tid`, and `typ=agui-chat`. Any failure is a 401.
- **`POST /agui/run`**:
  - checks the token, caps the body at 64 KB (413), parses the JSON (400), and requires the `threadId` to equal the token's `tid` (403 `thread_mismatch`);
  - streams `RUN_STARTED`, then runs the activities from `to_activities` through the unchanged `RelayCore.on_activity`. A queue lets each reply activity go out as events while the core is still working;
  - finishes with `RUN_FINISHED` (success or interrupt). Input problems become `RUN_ERROR` with a code; any other exception becomes `RUN_ERROR relay_error` with a generic message.
- **`GET /agui/threads/{thread_id}`** returns `{type: MESSAGES_SNAPSHOT, messages, state, interrupts}` for the token's own thread.
- **CORS** allows only `AGUI_CORS_ORIGINS`. Responses carry `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no` so proxies don't buffer the stream.

## Configuration

| Variable | Meaning |
| --- | --- |
| `BROKER_ISSUER` | Broker issuer; also the default JWKS base |
| `BROKER_JWKS_URL` | Override for the broker JWKS URL |
| `AGUI_TOKEN_AUDIENCE` | Default `healthgen-agui` |
| `AGUI_CORS_ORIGINS` | Comma-separated portal origins |
| All `relay.factory` variables | See [`relay/factory.py`](../../../files/services/agent-relay/relay/factory.py.md) |

## How it's used in the real system

It is reached directly from browsers, so put Front Door or Application Gateway with WAF and rate limits in front, with an origin timeout above the longest turn. Run one replica until `ThreadStore` moves to Redis. See [AG-UI](../../../../ag-ui.md).

## Related

[`relay/agui.py`](../../../files/services/agent-relay/relay/agui.py.md) · [`relay/core.py`](../../../files/services/agent-relay/relay/core.py.md) · [`host_m365.py`](../../../files/services/agent-relay/host_m365.py.md) · [`Dockerfile.agui`](../../../files/services/agent-relay/Dockerfile.agui.md) · [`tests/test_agui.py`](../../../files/services/agent-relay/tests/test_agui.py.md)
