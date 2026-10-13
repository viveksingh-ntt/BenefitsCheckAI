# `services/identity-broker/app/directline.py`

Source: [`services/identity-broker/app/directline.py`](../../../../../../services/identity-broker/app/directline.py)

> **Summary:** The server-side Direct Line 3.0 calls that need the channel secret: generating a user-bound token, and reconnecting to an existing conversation.

## What it does

- **`DirectLineClient(secret, endpoint)`:**
  - `generate_token(user_id, user_name?, trusted_origins?)` calls `POST /v3/directline/tokens/generate`.
  - `reconnect(conversation_id, watermark?)` calls `GET /v3/directline/conversations/{id}` and returns a fresh token and stream URL.
- Errors raise `DirectLineError(status)`, which the API turns into 502 or 503 `directline_unavailable`.
- Localhost endpoints bypass environment proxies.

## Configuration

| Variable | Local | Azure |
| --- | --- | --- |
| `DIRECTLINE_SECRET` | `local-dev-secret` (shared with `dev_server.py`) | Key Vault reference to the Direct Line site key |
| `DIRECTLINE_ENDPOINT` | `http://localhost:8104` | `https://directline.botframework.com`, or a regional endpoint |
| `DIRECTLINE_TRUSTED_ORIGINS` | the local portal | the portal origins |

## How it's used in the real system

**Enhanced authentication** must be on for the Direct Line site. It binds `from.id` to the token's `user.id`, which the relay relies on, and it requires `dl_`-prefixed ids, which the broker generates. The secret exists only here, in Key Vault and in Bot Service.
