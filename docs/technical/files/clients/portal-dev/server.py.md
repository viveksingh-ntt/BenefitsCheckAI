# `clients/portal-dev/server.py`

Source: [`clients/portal-dev/server.py`](../../../../../clients/portal-dev/server.py)

> **Summary:** A local stand-in for the member and provider portals. It serves the host page with the widget and plays the **portal backend (BFF)**: it signs portal assertions for fake signed-in users and exchanges them at the broker for Direct Line tokens.

| | |
| --- | --- |
| Layer | Portal (stand-in) |
| Local run | Used: `uvicorn server:app --port 8080` (from `clients/portal-dev`) |
| Production | Your portal BFFs implement the same token endpoint. This file is the **reference implementation** for them. |

## Endpoints

| Route | What it does |
| --- | --- |
| `GET /?user=alex\|jordan\|raman` | Sets a `dev_user` cookie and redirects. Without the query, it renders `index.html` with that user's display context. |
| `POST /api/agent/directline-token` | Signs an RS256 portal assertion (2-minute lifetime: `iss`, `aud=healthgen-identity-broker`, `sub`, `role`, `portal`, `name`, `idm_session`, `jti`, plus `member_ref` for the provider), posts it to `{BROKER_URL}/v1/directline/token` with the widget's JSON body, and returns the broker's response. The broker call runs in a worker thread, because the broker calls back into this server for its JWKS. |
| `GET /.well-known/jwks.json` | The public key the broker trusts (`PORTAL_JWKS_URL`). The key is generated at start-up. |
| `/widget/*` | Static files from `WIDGET_DIST` (default `vendor/`). |

Dev users:

- `alex`: member `mbr_7f3a`;
- `jordan`: member `mbr_2c91`;
- `raman`: provider `prv_pcp_01`, with patient `mbr_7f3a`.

## How it's used in the real system

Portal teams copy the token endpoint logic into their BFF:

1. The user comes from the real IdM session, not a cookie switcher.
2. The signing key comes from their key store, and its JWKS is published.
3. For providers, `member_ref` is set only after the portal's own provider–patient relationship check.
4. Logout calls `/v1/directline/logout`.

See runbook step 12.
