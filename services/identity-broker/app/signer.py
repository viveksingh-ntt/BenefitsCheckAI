"""JWT signing for the broker.

``LocalRsaSigner``   dev and tests: RSA key from a PEM (env/file) or generated at start-up.
``KeyVaultSigner``   Azure: the private key never leaves Key Vault (HSM-backed key on Premium or Managed HSM).
                     Signs the JWT digest with the Key Vault ``sign`` operation using the container's managed
                     identity. Plain REST over urllib, so no Azure SDK is needed in the image.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
import urllib.parse
import urllib.request
import uuid
from typing import Any, Protocol

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Signer(Protocol):
    kid: str

    def sign(self, claims: dict[str, Any]) -> str: ...

    def jwks(self) -> dict[str, Any]: ...


class LocalRsaSigner:
    def __init__(self, private_pem: str | None = None, kid: str | None = None):
        if private_pem:
            key = serialization.load_pem_private_key(private_pem.encode(), password=None)
            if not isinstance(key, rsa.RSAPrivateKey):
                raise ValueError("BROKER_SIGNING_KEY_PEM must be an RSA key")
            self._key = key
        else:
            self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub = self._key.public_key().public_numbers()
        self.kid = kid or hashlib.sha256(f"{pub.n}:{pub.e}".encode()).hexdigest()[:16]

    def sign(self, claims: dict[str, Any]) -> str:
        return jwt.encode(claims, self._key, algorithm="RS256", headers={"kid": self.kid, "typ": "JWT"})

    def jwks(self) -> dict[str, Any]:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self._key.public_key()))
        jwk.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return {"keys": [jwk]}


class ManagedIdentityCredential:
    """Access tokens from the Container Apps / App Service identity endpoint, falling back to IMDS."""

    def __init__(self, client_id: str | None = None):
        self.client_id = client_id
        self._cache: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()
        self._opener = urllib.request.build_opener()

    def token(self, resource: str) -> str:
        with self._lock:
            cached = self._cache.get(resource)
            if cached and cached[1] - 300 > time.time():
                return cached[0]
        endpoint, header = os.getenv("IDENTITY_ENDPOINT"), os.getenv("IDENTITY_HEADER")
        params = {"resource": resource}
        if self.client_id:
            params["client_id"] = self.client_id
        if endpoint and header:
            params["api-version"] = "2019-08-01"
            req = urllib.request.Request(f"{endpoint}?{urllib.parse.urlencode(params)}", headers={"X-IDENTITY-HEADER": header})
        else:
            params["api-version"] = "2018-02-01"
            req = urllib.request.Request(
                f"http://169.254.169.254/metadata/identity/oauth2/token?{urllib.parse.urlencode(params)}", headers={"Metadata": "true"}
            )
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10) as resp:
            body = json.loads(resp.read())
        expires_on = float(body.get("expires_on") or time.time() + 3000)
        with self._lock:
            self._cache[resource] = (body["access_token"], expires_on)
        return body["access_token"]


class KeyVaultSigner:
    """RS256 JWTs signed by an Azure Key Vault key (``sign`` permission or the Key Vault Crypto User role)."""

    API = "7.4"

    def __init__(self, key_id: str, credential: Any = None, vault_resource: str = "https://vault.azure.net", opener: Any = None):
        # key_id: https://<vault>.vault.azure.net/keys/<name>/<version>  (a pinned version keeps kid stable)
        self.key_id = key_id.rstrip("/")
        self.credential = credential or ManagedIdentityCredential(os.getenv("AZURE_CLIENT_ID"))
        self.vault_resource = vault_resource
        self._opener = opener or urllib.request.build_opener()
        self._jwks: dict[str, Any] | None = None
        self.kid = self.key_id.rsplit("/", 1)[-1]

    def _call(self, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        sep = "&" if "?" in url else "?"
        req = urllib.request.Request(
            f"{url}{sep}api-version={self.API}",
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={"Authorization": f"Bearer {self.credential.token(self.vault_resource)}", "Content-Type": "application/json"},
        )
        with self._opener.open(req, timeout=10) as resp:
            return json.loads(resp.read())

    def sign(self, claims: dict[str, Any]) -> str:
        header = {"alg": "RS256", "typ": "JWT", "kid": self.kid}
        signing_input = f"{b64url(json.dumps(header, separators=(',', ':')).encode())}.{b64url(json.dumps(claims, separators=(',', ':')).encode())}"
        digest = hashlib.sha256(signing_input.encode()).digest()
        result = self._call("POST", f"{self.key_id}/sign", {"alg": "RS256", "value": b64url(digest)})
        return f"{signing_input}.{result['value']}"

    def jwks(self) -> dict[str, Any]:
        if self._jwks is None:
            key = self._call("GET", self.key_id)["key"]
            self._jwks = {"keys": [{"kty": "RSA", "n": key["n"], "e": key["e"], "kid": self.kid, "use": "sig", "alg": "RS256"}]}
        return self._jwks


def signer_from_env() -> Signer:
    key_id = os.getenv("BROKER_KEYVAULT_KEY_ID")
    if key_id:
        return KeyVaultSigner(key_id)
    pem = os.getenv("BROKER_SIGNING_KEY_PEM")
    path = os.getenv("BROKER_SIGNING_KEY_FILE")
    if not pem and path:
        with open(path, encoding="utf-8") as fh:
            pem = fh.read()
    return LocalRsaSigner(pem)


def standard_claims(issuer: str, audience: str, subject: str, ttl: int) -> dict[str, Any]:
    now = int(time.time())
    return {"iss": issuer, "aud": audience, "sub": subject, "iat": now, "nbf": now - 5, "exp": now + ttl, "jti": uuid.uuid4().hex}
