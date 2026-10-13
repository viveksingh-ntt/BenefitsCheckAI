# `services/agent-relay/host_m365.py`

Source: [`services/agent-relay/host_m365.py`](../../../../../services/agent-relay/host_m365.py)

> **Summary:** The production entry point of the Agent relay. It hosts `RelayCore` on the Microsoft 365 Agents SDK (Python, aiohttp) at `POST /api/messages`, behind Azure Bot Service and Direct Line.

| | |
| --- | --- |
| Layer | Agent relay (host) |
| Local run | Not used: `dev_server.py` replaces it |
| Azure | **Real.** It is the container's `CMD` (`python host_m365.py`, port 3978) |
| Status | ⚠️ Written against the SDK's documented API and not run in the build environment. Pin the package versions after the first install. |

## What it does

- Loads the SDK configuration from the environment (`load_configuration_from_env`) and creates:
  - an `MsalConnectionManager`, which authenticates the bot's identity;
  - a `CloudAdapter`;
  - an `AgentApplication[TurnState]` with `MemoryStorage`.
- Registers handlers for `message` and `event` activities. Each handler:
  1. converts `context.activity` to a Bot Framework dict (`model_dump(by_alias=True)`);
  2. calls `RELAY.on_activity(activity, send)`.

  `send` strips the fields the SDK owns (`from`, `recipient`, `conversation`, `serviceUrl`, `channelId`) and calls `context.send_activity(Activity.model_validate(…))`.
- `on_error` logs the exception type and sends a generic apology.
- `create_app()` builds the aiohttp app with `jwt_authorization_middleware`, which validates the Bot Service channel JWT. It serves `POST /api/messages` and `GET /healthz`.

## Configuration

| Variable | Meaning |
| --- | --- |
| `CONNECTIONS__SERVICE_CONNECTION__SETTINGS__AUTHTYPE` | `UserManagedIdentity` (recommended) or `ClientSecret` |
| `CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID` | Client id of the bot identity (`id-bot`) |
| `CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID` | Tenant id |
| `PORT` | Default 3978 |
| All `relay.factory` variables | See [`relay/factory.py`](relay/factory.py.md) |

## How it's used in the real system

- **Bot endpoint:** Azure Bot (`az bot create … --endpoint https://ca-relay…/api/messages`) sends every Direct Line activity here. The relay's replies go back through the same turn context.
- **Health probe:** the JWT middleware applies to all routes, so use a **TCP** probe on 3978 rather than an HTTP probe of `/healthz`.
- **Scaling:** with more than one replica, use sticky sessions or move relay state to Redis (see [operations](../../../../operations.md)).

## Related

[`relay/core.py`](relay/core.py.md) · [`dev_server.py`](dev_server.py.md) · [`requirements-host.txt`](requirements-host.txt.md) · [`Dockerfile`](Dockerfile.md)
