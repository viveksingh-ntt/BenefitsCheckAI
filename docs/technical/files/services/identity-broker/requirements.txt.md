# `services/identity-broker/requirements.txt`

Source: [`services/identity-broker/requirements.txt`](../../../../../services/identity-broker/requirements.txt)

> **Summary:** The broker's pinned dependencies: `starlette`, `uvicorn[standard]`, `PyJWT[crypto]`, `cryptography` and `python-multipart` (for the form-encoded `/oauth2/token`).

No Azure SDK is needed: Key Vault and managed identity calls are plain REST in `signer.py`.
