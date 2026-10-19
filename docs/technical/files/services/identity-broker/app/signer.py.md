# `services/identity-broker/app/signer.py`

Source: [`services/identity-broker/app/signer.py`](../../../../../../services/identity-broker/app/signer.py)

> **Summary:** Signs the broker's JWTs. Locally it uses an RSA key; in Azure it uses an HSM-backed Azure Key Vault key, so the private key never leaves Key Vault.

## What it does

- **`LocalRsaSigner(pem?)`:** RS256 with a key from `BROKER_SIGNING_KEY_PEM` or `BROKER_SIGNING_KEY_FILE`, or an ephemeral key generated at start-up. The `kid` is derived from the public key.
- **`KeyVaultSigner(key_id)`:**
  - builds the JWT header and payload, SHA-256 hashes the signing input, then calls Key Vault `POST {key_id}/sign?api-version=7.4` with `{"alg":"RS256","value":<digest>}`;
  - gets the JWKS once from `GET {key_id}`, as `n` and `e`;
  - uses the key **version** as the `kid`;
  - authenticates with `ManagedIdentityCredential` (Container Apps identity endpoint, falling back to IMDS) for `https://vault.azure.net`.
- **`signer_from_env()`:** uses `BROKER_KEYVAULT_KEY_ID` if set, otherwise the local signer.
- **`standard_claims(iss, aud, sub, ttl)`:** `iat`, `nbf` (−5 s), `exp` and a random `jti`.
- **`Signer`:** a protocol shared by both implementations, requiring `sign(claims)` and `jwks()`.
- **`ManagedIdentityCredential`:** caches resource access tokens until five minutes before expiry, then requests a new token from the Container Apps/App Service identity endpoint or, if unavailable, IMDS.
- **`b64url` / `b64url_decode`:** URL-safe, unpadded Base64 helpers used to construct the Key Vault-signed JWT.

## How it's used in the real system

- Create an `RSA-HSM` key (`az keyvault key create --kty RSA-HSM`, on a Premium vault) and give the broker identity **Key Vault Crypto User**. Set `BROKER_KEYVAULT_KEY_ID` to the *versioned* key id.
- Each token costs one Key Vault sign call. At pilot volumes this is fine; watch the vault's throttling limits (service limits per vault) as traffic grows.
- **Rotation:** create a new version, publish both public keys for one token lifetime (the current code publishes only the configured key, so extend `jwks()` during rotation), then switch.
- ⚠️ The Key Vault path is tested against a fake vault that follows the REST shape, not against a real vault.

When no PEM is configured, the local signer creates a new ephemeral RSA-2048 key at startup. Tokens signed before a process restart then cannot be verified against the restarted process's JWKS; configure a persistent key file when local token continuity is needed.

## Related

Test: `KeyVaultSignerTest` in [`tests/test_broker.py`](../tests/test_broker.py.md) · runbook step 3.
