# `services/mcp-healthgen/app/clients.py`

Source: [`services/mcp-healthgen/app/clients.py`](../../../../../../services/mcp-healthgen/app/clients.py)

> **Summary:** The MCP server's HTTP clients: the identity broker (token exchange, pending actions), HealthGen core, and the signed n8n hand-off webhook.

## What it does

- **`BrokerClient.exchange(session_ref, scope?, action_id?)`:**
  - posts an RFC 8693 form to `/oauth2/token` and returns a `Grant` (token, expiry, claims, and the `action` for writes);
  - caches read grants per session and scope until 30 s before expiry, and never caches write grants;
  - reads the claims (`role`, `member_ref`) without verifying them, because it is its own token fresh from the broker. The core verifies the signature.
- **`BrokerClient.create_action(session_ref, kind, params, summary)`** calls `POST /v1/actions`.
- **`CoreClient.get` and `CoreClient.post`** send `Authorization: Bearer <downstream token>` and turn booleans into `true`/`false`.
- **`HandoffClient.send(payload)`** posts compact JSON (`ensure_ascii=False`, equal to `JSON.stringify` in n8n) with `X-HealthGen-Timestamp` and `X-HealthGen-Signature: sha256=HMAC(secret, ts + "." + body)`.
- **`UpstreamError(status, code)`** carries the upstream error code, which the tools map to friendly text.

## How it's used in the real system

In Azure the broker credential is a managed identity token for `api://healthgen-identity-broker`, or `BROKER_CLIENT_KEY` in dev. The hand-off secret comes from Key Vault (runbook step 11). For the real core, point `CORE_URL` at its internal endpoint. If the core needs its own credential instead of the broker JWT, add it in `CoreClient`, and keep the broker JWT as the identity of the end user.
