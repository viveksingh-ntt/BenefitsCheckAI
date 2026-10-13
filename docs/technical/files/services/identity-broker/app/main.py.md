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

| Route | Caller | What it does |
| --- | --- | --- |
| `POST /v1/directline/token` | Portal BFF, with a portal assertion | **start:** creates `dl_<random>`, calls Direct Line `tokens/generate` with the secret (and trusted origins), and stores a binding. **refresh/resume** with a `conversationId`: if the binding belongs to the same user and member and is still live, calls Direct Line `reconnect` and extends the session. Otherwise it starts fresh. Returns `{token, conversationId, expires_in, streamUrl, userId}`. |
| `POST /v1/directline/logout` | Portal BFF | Revokes every binding of the assertion's `idm_session` and cancels its pending actions. |
| `POST /v1/sessions/resolve` | Agent relay | `{dl_user_id, conversation_id}` returns `session_ref`, role, portal, display name and a 10-minute **user-context JWT** (aud `healthgen-agent-gateway`). It checks that the conversation matches the binding. Member ids are never returned. |
| `GET /v1/sessions/{ref}/status` | Relay, APIM, MCP | `{active, role}`. APIM uses it for revocation. |
| `POST /v1/actions` | MCP server | Creates a **pending action** (`appointment.request` for members, `referral.submit` for providers). It forces `member_ref` from the session, checks the exact parameter set, supersedes older pending actions of the same kind, and expires after 15 minutes. |
| `GET /v1/actions/{id}?session_ref=` | Relay | Status, kind, summary and params, for checking a Confirm press. |
| `POST /v1/actions/{id}/confirm` | Relay | pending → confirmed (atomic). Stores the allowed extras (`note` or `reason`, ≤ 300 chars). |
| `POST /v1/actions/{id}/cancel` | Relay | pending → cancelled. |
| `POST /oauth2/token` | MCP server | **RFC 8693.** `subject_token` = session ref (type `urn:healthgen:params:oauth:token-type:session-ref`), audience `healthgen-core`. Without an action it grants only read scopes. With `action_id` the action must be confirmed; it is consumed atomically, and the token gets the write scope plus `confirmed_action {id, kind, params_sha256}`, with the action params and extras in the response. |
| `GET /.well-known/jwks.json`, `/.well-known/openid-configuration` | Core, APIM, foundry-local | Public signing keys and issuer metadata. |
| `GET /healthz` | Probes | Liveness. |

## Policies in code

- `READ_SCOPES`: members, eligibility, accumulators, benefits, prior auth, services, providers.
- `ACTION_KINDS`: allowed roles, write scope, exact params and allowed extras per action kind.
- Sessions: 60 minutes idle (`SESSION_IDLE_SECONDS`) and 12 hours maximum (`SESSION_MAX_SECONDS`). User-context tokens last 10 minutes and downstream tokens 5 minutes.
- `params_sha256`: canonical JSON hashing, identical to the core's.

## How it's used in the real system

- **Portal side:** both portal BFFs call `/v1/directline/token` and `/v1/directline/logout` (see runbook step 12).
- **Service side:** the relay, MCP server and APIM call it with managed identity tokens, allow-listed by client id in `SERVICE_CLIENTS`.
- **Exposure:** keep it on internal ingress, and expose only `/v1/directline/*` to the BFFs.
- **Scaling:** move the store to Redis or Cosmos DB before running a second replica.

## Related

[`auth.py`](auth.py.md) · [`signer.py`](signer.py.md) · [`store.py`](store.py.md) · [`directline.py`](directline.py.md) · [identity and security](../../../../../identity-and-security.md) · sequences [1](../../../../sequences.md#1-start-a-chat-session), [4](../../../../sequences.md#4-booking-with-human-confirmation), [7](../../../../sequences.md#7-resume-token-refresh-and-logout)
