# `services/identity-broker/app/main.py`

Source: [`services/identity-broker/app/main.py`](../../../../../../services/identity-broker/app/main.py)

> **Summary:** The identity broker's HTTP API. It binds Direct Line users to portal users, issues user-context tokens, keeps pending write actions for human confirmation, and performs RFC 8693 token exchange for the MCP server.

| | |
| --- | --- |
| Layer | Identity (HealthGen service) |
| Local run | Real code: local RSA key, shared service keys, SQLite in a temp folder |
| Azure | Real code: Key Vault HSM key, Entra service authentication, internal ingress, one replica (pilot) |
| Run | `uvicorn app.main:app --port 8102` |

## Endpoints

Every route except the health and discovery endpoints authenticates its caller. Portal routes use a verified portal assertion; service routes use the allow-listed service identity. The error response shape is `{"error": "<code>", "error_description": "<message>"}`.

| Route | Caller | Behavior |
| --- | --- | --- |
| `POST /v1/directline/token` | Portal BFF | Verifies the portal assertion. A new chat generates a random `dl_` user id, obtains a Direct Line token, and stores the user/session binding. For `reason` `refresh` or `resume`, a matching live `conversationId` is reconnected and its idle expiry extended; an unknown or different user's conversation falls back to a new chat. Returns `{token, conversationId, expires_in, streamUrl, userId}`. |
| `POST /v1/directline/logout` | Portal BFF | Revokes every binding associated with the assertion's `idm_session` and cancels its pending or confirmed actions. An assertion without `idm_session` is rejected. |
| `POST /v1/sessions/resolve` | Agent relay | Accepts `{dl_user_id, conversation_id}` and requires an active binding with the same conversation. Returns the opaque `session_ref`, role, portal, display name, and a signed user-context JWT; it does not return a member reference. |
| `GET /v1/sessions/{session_ref}/status` | Agent relay, APIM, MCP | Returns `{active, role}` after service authentication. Active status reflects revocation, idle expiry, and the maximum session lifetime. |
| `POST /v1/actions` | MCP server | Creates a pending `appointment.request` (member) or `referral.submit` (provider). The broker enforces the action role, binds `member_ref` from the session, checks the exact parameter keys, cancels older pending actions of the same kind, and sets a 15-minute expiry. |
| `GET /v1/actions/{action_id}?session_ref=...` | Agent relay | Returns an action only when it belongs to the supplied session reference; includes its status, review summary, parameters, expiry, and expired flag. |
| `POST /v1/actions/{action_id}/confirm` | Agent relay | Requires an active session and atomically transitions that session's pending action to confirmed. Only the action kind's permitted extras are saved, each truncated to 300 characters. A stale or already handled action returns HTTP 409. |
| `POST /v1/actions/{action_id}/cancel` | Agent relay | Atomically transitions a pending action for the supplied session to cancelled and returns whether the transition succeeded. |
| `POST /oauth2/token` | MCP server | Implements the supported RFC 8693 token-exchange grant. The subject token is a HealthGen session reference and the audience must be `healthgen-core`. Without `action_id`, only `READ_SCOPES` are granted (all read scopes by default). With an action id, the action must belong to the session and be confirmed; a compare-and-set consumes it once. The short-lived token carries the corresponding write scope and `confirmed_action` id/kind/parameter hash. The response also returns the action parameters and permitted extras for the MCP server to submit downstream. |
| `GET /.well-known/jwks.json` | Token consumers | Publishes the configured signer's public keys with a five-minute public cache header. |
| `GET /.well-known/openid-configuration` | Token consumers | Returns issuer, JWKS URL, token endpoint, and supported token-exchange metadata. |
| `GET /healthz` | Probes | Returns `{"status":"ok","service":"identity-broker"}`. |

The route handlers are created inside `create_app`, which accepts settings and dependencies as injectable arguments for tests. The exported ASGI `app` is lazy: it creates the Starlette application on the first request, so importing `app.main` does not immediately read runtime environment variables.

## Policies in code

- `READ_SCOPES`: members, eligibility, accumulators, benefits, prior auth, services, providers.
- `ACTION_KINDS`: allowed roles, write scope, exact params and allowed extras per action kind.
- Sessions: 60 minutes idle (`SESSION_IDLE_SECONDS`) and 12 hours maximum (`SESSION_MAX_SECONDS`). User-context tokens last 10 minutes and downstream tokens 5 minutes; the 15-minute action lifetime is configured by `Settings.action_ttl`.
- `params_sha256`: SHA-256 of canonical JSON (sorted keys, compact separators, UTF-8), matching the core's computation. This hash is included in the downstream token's `confirmed_action` claim.
- `guarded`: translates authentication failures, Direct Line failures, and common malformed-input exceptions into structured JSON errors. Direct Line failures become `directline_unavailable`; unexpected exceptions are not converted into successful responses.

## Configuration

`Settings.from_env()` reads `BROKER_ISSUER` (required), `CORE_AUDIENCE` (default `healthgen-core`), `USER_CONTEXT_AUDIENCE` (default `healthgen-agent-gateway`), `SESSION_IDLE_SECONDS` (default `3600`), `SESSION_MAX_SECONDS` (default `43200`), and comma-separated `DIRECTLINE_TRUSTED_ORIGINS`. The factory also wires the signer, store, Direct Line client, portal assertion verifier, and service authenticator from their respective environment settings; see [auth.py](auth.py.md), [signer.py](signer.py.md), [directline.py](directline.py.md), and [store.py](store.py.md).

## How it's used in the real system

- **Portal side:** both portal BFFs call `/v1/directline/token` and `/v1/directline/logout` (see runbook step 12).
- **Service side:** the relay, MCP server and APIM call it with managed identity tokens, allow-listed by client id in `SERVICE_CLIENTS`.
- **Exposure:** keep it on internal ingress, and expose only `/v1/directline/*` to the BFFs.
- **Scaling:** move the store to Redis or Cosmos DB before running a second replica.

## Related

[`auth.py`](auth.py.md) · [`signer.py`](signer.py.md) · [`store.py`](store.py.md) · [`directline.py`](directline.py.md) · [identity and security](../../../../../identity-and-security.md) · sequences [1](../../../../sequences.md#1-start-a-chat-session), [4](../../../../sequences.md#4-booking-with-human-confirmation), [7](../../../../sequences.md#7-resume-token-refresh-and-logout) · tests: [`test_broker.py`](../tests/test_broker.py.md)
