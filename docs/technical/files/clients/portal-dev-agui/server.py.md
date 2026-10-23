# `clients/portal-dev-agui/server.py`

Source: [`clients/portal-dev-agui/server.py`](../../../../../clients/portal-dev-agui/server.py)

> **Summary:** Portal stand-in for the AG-UI path: serves the host page and plays the portal BFF, exchanging a signed portal assertion at `POST /v1/agui/token` for the widget.

| | |
| --- | --- |
| Layer | Portal stand-in |
| Local run | **Real**: started by `scripts/local_stack_agui.py` on 8081 |
| Azure | Not deployed. It is a reference for the real portal BFFs. |

## What it does

- `GET /`: the host page with the dev user's display context. `?user=alex|jordan|raman` switches the user (cookie).
- `POST /api/agent/agui-token`: signs a 2-minute portal assertion for the signed-in user and forwards the widget's body (`reason`, `conversationId`) to the broker. The call runs in a worker thread because the broker fetches this server's JWKS during the call.
- `GET /.well-known/jwks.json`: the portal key the broker trusts.
- `/widget/*`: the vendored widget bundle.

The dev users are loaded from [`portal-dev/server.py`](../../../files/clients/portal-dev/server.py.md) so both pages agree.

## How it's used in the real system

Each portal BFF adds the same endpoint next to (or instead of) `/api/agent/directline-token`. See [AG-UI](../../../../ag-ui.md).
