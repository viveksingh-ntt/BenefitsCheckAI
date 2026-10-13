# `services/healthgen-core-mock/app/auth.py`

Source: [`services/healthgen-core-mock/app/auth.py`](../../../../../../services/healthgen-core-mock/app/auth.py)

> **Summary:** Validates the broker's downstream JWT, exposes the caller as a `Principal`, and consumes one-time write confirmations.

## What it does

- **`TokenValidator(issuer, jwks_url | jwks)`:** verifies RS256 or PS256 against the broker JWKS (`CORE_JWKS_URL`, cached 5 minutes, or `CORE_JWKS_JSON`). It checks the audience (`healthgen-core`), the issuer (`BROKER_ISSUER`), and that `exp`, `iat`, `sub` and `jti` are present, and requires `role` to be `member` or `provider`.
- **`Principal`:** `sub`, `role`, `member_ref`, `scopes`, `session_ref` (`sid`), `actor` (`act.sub`), `confirmed_action`, `jti`, and the helpers `require_scope` and `require_member`.
- **`consume_confirmation(principal, kind, params)`:**
  - the token must carry `confirmed_action` of that kind, with `params_sha256` equal to the hash of the request's parameters;
  - the `jti` must not have been used before (kept in memory until the token expires).

  It returns the confirmation id, which is stored with the booking for audit.
- **`params_sha256`:** canonical JSON (sorted keys, compact) through SHA-256. It is the same function as in the broker.

## How it's used in the real system

Reproduce these checks in the real core, or in an API gateway policy in front of it. In particular, keep the `jti` replay protection in a shared store if the core runs several instances.
