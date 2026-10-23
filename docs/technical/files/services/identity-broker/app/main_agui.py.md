# `services/identity-broker/app/main_agui.py`

Source: [`services/identity-broker/app/main_agui.py`](../../../../../../services/identity-broker/app/main_agui.py)

> **Summary:** Broker entry point for the AG-UI path: the unchanged `main.create_app` plus the `/v1/agui/token` route, and able to start without a Direct Line secret.

| | |
| --- | --- |
| Layer | Identity broker (AG-UI path) |
| Local run | **Real**: `uvicorn app.main_agui:app` (started by `scripts/local_stack_agui.py`) |
| Azure | **Real**: the broker container's command on the AG-UI path |

## What it does

- `create_app(...)` builds the same settings, signer, SQLite store and portal verifier as `main.py`, calls `main.create_app` with them, and appends the routes from [`agui.py`](../../../../files/services/identity-broker/app/agui.py.md). Every existing route (session resolve, actions, token exchange, JWKS, logout) is unchanged.
- If `DIRECTLINE_SECRET` is not set, it passes a `NoDirectLine` stub, so `/v1/directline/token` returns 502 `directline_unavailable` instead of the app failing to start.
- `app` is lazy, so importing the module doesn't read the environment.

## How it's used in the real system

Run the broker image with `uvicorn app.main_agui:app` instead of `app.main:app`. Setting `DIRECTLINE_SECRET` as well lets one broker serve both paths during a migration. See the deploy delta in [AG-UI](../../../../../ag-ui.md).
