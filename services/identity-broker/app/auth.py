"""Who is calling the broker.

* Portal BFFs prove the signed-in user with a short-lived *portal assertion* JWT signed by the portal
  (its in-house IdM session behind it). Verified against the portal's JWKS.
* Internal services (agent relay, MCP server, APIM) authenticate as themselves:
    SERVICE_AUTH=entra  Entra ID access tokens (managed identities); ``azp``/``appid`` must be allow-listed.
    SERVICE_AUTH=keys   shared keys, for local dev only.
"""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient


class AuthError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


class JwtVerifier:
    def __init__(self, issuers: list[str], audiences: list[str], jwks_url: str | None = None, jwks: dict[str, Any] | None = None, leeway: int = 30):
        if not jwks_url and not jwks:
            raise ValueError("A JWKS URL or JWKS document is required")
        self.issuers = issuers
        self.audiences = audiences
        self.leeway = leeway
        self._client = PyJWKClient(jwks_url, cache_keys=True, lifespan=600) if jwks_url else None
        self._static = {k.get("kid"): jwt.PyJWK(k) for k in (jwks or {}).get("keys", [])}

    def verify(self, token: str, require: list[str] | None = None) -> dict[str, Any]:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            key = self._static[kid].key if kid in self._static else (self._client.get_signing_key(kid).key if self._client else None)
            if key is None:
                raise AuthError(401, "invalid_token", "Unknown signing key")
            claims = jwt.decode(token, key, algorithms=["RS256", "PS256", "ES256"], audience=self.audiences, leeway=self.leeway,
                                options={"require": ["exp", "iat", "iss", *(require or [])]})
        except AuthError:
            raise
        except jwt.PyJWTError as exc:
            raise AuthError(401, "invalid_token", str(exc)) from exc
        if claims["iss"] not in self.issuers:
            raise AuthError(401, "invalid_token", "Untrusted issuer")
        return claims


def bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError(401, "missing_token", "Bearer token required")
    return authorization.split(" ", 1)[1].strip()


@dataclass
class PortalUser:
    principal_ref: str
    role: str
    member_ref: str | None
    portal: str
    idm_session: str | None
    display_name: str | None


class PortalAssertionVerifier:
    AUDIENCE = "healthgen-identity-broker"

    def __init__(self, verifier: JwtVerifier):
        self.verifier = verifier

    @classmethod
    def from_env(cls) -> "PortalAssertionVerifier":
        jwks_json = os.getenv("PORTAL_JWKS_JSON")
        return cls(JwtVerifier(
            issuers=[i.strip() for i in os.environ["PORTAL_ISSUERS"].split(",")],
            audiences=[os.getenv("PORTAL_ASSERTION_AUDIENCE", cls.AUDIENCE)],
            jwks_url=os.getenv("PORTAL_JWKS_URL"),
            jwks=json.loads(jwks_json) if jwks_json else None,
        ))

    def verify(self, assertion: str) -> PortalUser:
        c = self.verifier.verify(assertion, require=["sub", "jti"])
        if c.get("exp", 0) - c.get("iat", 0) > 600:
            raise AuthError(401, "invalid_token", "Portal assertions must live 10 minutes or less")
        role = c.get("role")
        if role not in ("member", "provider"):
            raise AuthError(403, "invalid_role", "role must be member or provider")
        member_ref = c.get("member_ref") or (c["sub"] if role == "member" else None)
        if role == "member" and member_ref != c["sub"]:
            raise AuthError(403, "invalid_member", "A member can only act for themselves")
        return PortalUser(
            principal_ref=c["sub"],
            role=role,
            member_ref=member_ref,
            portal=c.get("portal") or role,
            idm_session=c.get("idm_session"),
            display_name=c.get("name"),
        )


class ServiceAuthenticator:
    def __init__(self, mode: str, keys: dict[str, str] | None = None, entra: JwtVerifier | None = None, clients: dict[str, str] | None = None):
        self.mode = mode
        self.keys = keys or {}
        self.entra = entra
        self.clients = clients or {}  # app/client id -> service name

    @staticmethod
    def _pairs(raw: str) -> dict[str, str]:
        out = {}
        for part in filter(None, (p.strip() for p in raw.split(","))):
            name, _, value = part.partition("=")
            out[name.strip()] = value.strip()
        return out

    @classmethod
    def from_env(cls) -> "ServiceAuthenticator":
        mode = os.getenv("SERVICE_AUTH", "entra")
        if mode == "keys":
            return cls("keys", keys=cls._pairs(os.environ["SERVICE_KEYS"]))
        tenant = os.environ["ENTRA_TENANT_ID"]
        verifier = JwtVerifier(
            issuers=[f"https://login.microsoftonline.com/{tenant}/v2.0", f"https://sts.windows.net/{tenant}/"],
            audiences=[a.strip() for a in os.environ["BROKER_ENTRA_AUDIENCES"].split(",")],
            jwks_url=f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys",
        )
        clients = {v: k for k, v in cls._pairs(os.environ["SERVICE_CLIENTS"]).items()}
        return cls("entra", entra=verifier, clients=clients)

    def authenticate(self, authorization: str | None, allowed: set[str]) -> str:
        token = bearer(authorization)
        if self.mode == "keys":
            service = next((name for name, key in self.keys.items() if key and hmac.compare_digest(key, token)), None)
        else:
            assert self.entra is not None
            claims = self.entra.verify(token)
            service = self.clients.get(claims.get("azp") or claims.get("appid") or "")
        if not service:
            raise AuthError(401, "unknown_service", "Caller is not a known service")
        if service not in allowed:
            raise AuthError(403, "service_not_allowed", f"{service} may not call this endpoint")
        return service
