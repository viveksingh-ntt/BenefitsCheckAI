# `services/identity-broker/app/auth.py`

Source: [`services/identity-broker/app/auth.py`](../../../../../../services/identity-broker/app/auth.py)

> **Summary:** Decides who is calling the broker: portal BFFs (signed portal assertions) or internal services (Entra managed identity tokens, or dev keys).

## What it does

- **`JwtVerifier`:** verifies an RS256, PS256 or ES256 JWT against a JWKS URL (`PyJWKClient`, cached for 10 minutes) or a static JWKS. It checks the audience, the issuer allowlist and the required claims, with 30 s leeway.
- **`PortalAssertionVerifier`:** verifies the BFF's assertion (aud `healthgen-identity-broker`). It requires `sub` and `jti`, rejects lifetimes over 10 minutes, and requires `role` to be `member` or `provider`. A member's `member_ref` must equal their `sub`; a provider's `member_ref` is the patient in context. The result is a `PortalUser`.
- **`ServiceAuthenticator.authenticate(authorization, allowed)`:**
  - `SERVICE_AUTH=entra` validates an Entra v1 or v2 token for `BROKER_ENTRA_AUDIENCES`, then maps `azp`/`appid` to a service name through `SERVICE_CLIENTS` (`agent-relay=<id>,mcp-healthgen=<id>,apim=<id>`).
  - `SERVICE_AUTH=keys` compares shared keys in constant time (`SERVICE_KEYS`, dev only).
  - Each endpoint passes the services it allows, for example only `mcp-healthgen` may call `/oauth2/token`.
- **`bearer(authorization)`:** extracts the bearer credential or raises a 401 `AuthError`.
- **`AuthError`:** carries the HTTP status and stable error code used by the broker's request handlers.

## Configuration

| Variable | Purpose |
| --- | --- |
| `PORTAL_ISSUERS` | Comma-separated trusted portal assertion issuers. |
| `PORTAL_JWKS_URL` or `PORTAL_JWKS_JSON` | Remote or inline portal verification keys. At least one must be configured. |
| `PORTAL_ASSERTION_AUDIENCE` | Portal assertion audience; defaults to `healthgen-identity-broker`. |
| `SERVICE_AUTH` | `entra` by default; set to `keys` for local development. |
| `ENTRA_TENANT_ID`, `BROKER_ENTRA_AUDIENCES`, `SERVICE_CLIENTS` | Tenant, accepted service-token audiences, and service-name-to-client-id mappings in Entra mode. |
| `SERVICE_KEYS` | Comma-separated `service-name=key` pairs in local key mode. |

The broker endpoints pass an explicit allowlist to `authenticate`, so a valid service credential alone does not grant access to every internal route.

## How it's used in the real system

In Azure, use `SERVICE_AUTH=entra` and the clients of the managed identities `id-relay` and `id-mcp`, plus APIM's identity. The portal BFF teams publish their JWKS at `PORTAL_JWKS_URL` and sign assertions only after their own session checks. For providers, this includes the provider–patient relationship, which the core checks again through the panel.

## Related

Tests: `test_rejects_bad_assertions` and `test_resolve_requires_relay_and_matching_conversation` in [`tests/test_broker.py`](../tests/test_broker.py.md).
