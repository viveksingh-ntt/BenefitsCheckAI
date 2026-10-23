# `services/identity-broker/app/agui.py`

Source: [`services/identity-broker/app/agui.py`](../../../../../../services/identity-broker/app/agui.py)

> **Summary:** The broker's AG-UI token endpoint, `POST /v1/agui/token`. It exchanges a portal assertion for a short chat token bound to one AG-UI thread, the counterpart of `/v1/directline/token`.

| | |
| --- | --- |
| Layer | Identity broker (AG-UI path) |
| Local run | **Real**, mounted by `main_agui.py` |
| Azure | **Real**, in the broker container when it runs `app.main_agui:app` |

## What it does

`agui_routes(settings, signer, store, portal, audience, ttl)` returns the route. For each request it:

1. verifies the portal assertion in `Authorization: Bearer` with the same `PortalAssertionVerifier` as Direct Line (issuer allowlist, portal JWKS, `jti` replay check);
2. on `reason: refresh` or `resume` with a `conversationId`, reuses that binding only if it is live, is an AG-UI binding (`agui_` user id) and belongs to the same principal and member. Otherwise it starts a new thread, so naming someone else's thread id gets you a fresh, empty one;
3. on start, creates a `Binding` with `dl_user_id = agui_<hex>` and `conversation_id = thr_<hex>`. This is the same table Direct Line uses, so `/v1/sessions/resolve`, logout and the session lifetime work unchanged;
4. signs the chat token with the broker key: `iss`, `aud=healthgen-agui`, `sub=agui_…`, `tid=thr_…`, `typ=agui-chat`, `iat`, `exp` (default 30 minutes).

The response has the Direct Line shape so the widget's `tokenUrlFetcher` works as-is: `{token, conversationId, threadId, userId, expires_in}`.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `AGUI_TOKEN_AUDIENCE` | `healthgen-agui` | `aud` of the chat token; must match the relay's `AGUI_TOKEN_AUDIENCE` |
| `AGUI_TOKEN_TTL_SECONDS` | `1800` | Chat token lifetime. The widget refreshes 60 s before expiry. |

## How it's used in the real system

The portal BFF calls it server-to-server (see [`portal-dev-agui/server.py`](../../../../files/clients/portal-dev-agui/server.py.md)). The broker is internal; expose this path to the BFFs the same way as `/v1/directline/*`. See [AG-UI](../../../../../ag-ui.md).

## Related

[`main_agui.py`](../../../../files/services/identity-broker/app/main_agui.py.md) · [`test_agui_tokens.py`](../../../../files/services/identity-broker/tests/test_agui_tokens.py.md) · [`main.py`](../../../../files/services/identity-broker/app/main.py.md) · [`host_agui.py`](../../../../files/services/agent-relay/host_agui.py.md)
