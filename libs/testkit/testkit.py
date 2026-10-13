"""Small, dependency-free helpers for the service tests (stdlib unittest + urllib).

- ``RsaKey``: a throwaway RSA key with a JWKS view and a signer.
- ``serve(app)``: runs an ASGI app on a free localhost port in a background thread.
- ``http(...)``: JSON over urllib that returns (status, body) instead of raising on 4xx/5xx.
"""

from __future__ import annotations

import contextlib
import json
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Iterator

import jwt
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


class RsaKey:
    def __init__(self, kid: str | None = None):
        self.kid = kid or f"test-{uuid.uuid4().hex[:8]}"
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    @property
    def private_pem(self) -> str:
        return self.private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()

    @property
    def jwks(self) -> dict[str, Any]:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.private.public_key()))
        jwk.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return {"keys": [jwk]}

    def sign(self, claims: dict[str, Any], ttl: int = 300) -> str:
        now = int(time.time())
        body = {"iat": now, "exp": now + ttl, "jti": uuid.uuid4().hex, **claims}
        return jwt.encode(body, self.private, algorithm="RS256", headers={"kid": self.kid})


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def serve(app: Any, port: int | None = None) -> Iterator[str]:
    port = port or free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="auto")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


# Tests only talk to localhost: never route them through a corporate proxy from the environment.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http(method: str, url: str, body: Any = None, headers: dict[str, str] | None = None, form: bool = False, timeout: float = 15) -> tuple[int, Any]:
    hdrs = dict(headers or {})
    payload = None
    if body is not None:
        if form:
            from urllib.parse import urlencode
            payload = urlencode(body).encode()
            hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            payload = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=payload, method=method, headers=hdrs)
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    text = raw.decode() if raw else ""
    try:
        return status, json.loads(text) if text else None
    except json.JSONDecodeError:
        return status, text
