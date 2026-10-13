# `libs/testkit/testkit.py`

Source: [`libs/testkit/testkit.py`](../../../../../libs/testkit/testkit.py)

> **Summary:** Shared, dependency-free test helpers: throwaway RSA keys with a JWKS view, an in-thread uvicorn server, and an HTTP helper that never uses environment proxies.

| Helper | Use |
| --- | --- |
| `RsaKey(kid?)` | `.jwks`, `.private_pem`, `.sign(claims, ttl)` (adds `iat`, `exp`, `jti`). Plays the broker or a portal in tests. |
| `serve(app, port?)` | A context manager that runs an ASGI app on a free localhost port and yields its base URL. |
| `free_port()` | Picks an unused port. |
| `http(method, url, body?, headers?, form?)` | Returns `(status, json_or_text)`, with no exceptions on 4xx or 5xx. It bypasses proxies. |

The service tests add `libs/testkit` to `sys.path`. It is test-only and never shipped in images.
