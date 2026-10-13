"""Validation of the downstream access token minted by the identity broker (RFC 8693 token exchange).

The token is an RS256 JWT signed with the broker's key (a Key Vault HSM key in Azure, a local RSA key in dev):

    iss  = BROKER_ISSUER            aud = "healthgen-core"
    sub  = principal ref            role = "member" | "provider"
    member_ref = member whose data may be read or written in this call
    sid  = session_ref (audit only) act = {"sub": "<calling service>"}
    scope = space separated, e.g. "eligibility.read benefits.read appointment.request"
    confirmed_action = {"id", "kind", "params_sha256"}   only on write tokens, one use
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import jwt
from jwt import PyJWKClient

AUDIENCE = os.getenv("CORE_AUDIENCE", "healthgen-core")


class AuthError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass
class Principal:
    sub: str
    role: str
    member_ref: str | None
    scopes: set[str]
    session_ref: str | None
    actor: str | None
    confirmed_action: dict[str, Any] | None
    jti: str
    claims: dict[str, Any] = field(repr=False, default_factory=dict)

    def require_scope(self, scope: str) -> None:
        if scope not in self.scopes:
            raise AuthError(403, "insufficient_scope", f"Token lacks scope {scope}")

    def require_member(self, member_ref: str) -> None:
        if not self.member_ref or self.member_ref != member_ref:
            raise AuthError(403, "member_mismatch", "Token is not scoped to this member")


def params_sha256(params: dict[str, Any]) -> str:
    """Canonical hash of an action's parameters. The broker uses the same function."""
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TokenValidator:
    def __init__(self, issuer: str, jwks_url: str | None = None, jwks: dict[str, Any] | None = None, audience: str = AUDIENCE, leeway: int = 30):
        if not jwks_url and not jwks:
            raise ValueError("Configure CORE_JWKS_URL or CORE_JWKS_JSON")
        self.issuer = issuer
        self.audience = audience
        self.leeway = leeway
        self._client = PyJWKClient(jwks_url, cache_keys=True, lifespan=300) if jwks_url else None
        self._static = {k["kid"]: jwt.PyJWK(k) for k in (jwks or {}).get("keys", [])}
        self._used_jti: dict[str, float] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "TokenValidator":
        jwks_json = os.getenv("CORE_JWKS_JSON")
        return cls(
            issuer=os.environ["BROKER_ISSUER"],
            jwks_url=os.getenv("CORE_JWKS_URL"),
            jwks=json.loads(jwks_json) if jwks_json else None,
        )

    def _key(self, token: str) -> Any:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.PyJWTError as exc:
            raise AuthError(401, "invalid_token", "Malformed token") from exc
        if kid in self._static:
            return self._static[kid].key
        if self._client:
            try:
                return self._client.get_signing_key(kid).key
            except jwt.PyJWTError as exc:
                raise AuthError(401, "invalid_token", "Unknown signing key") from exc
        raise AuthError(401, "invalid_token", "Unknown signing key")

    def validate(self, authorization: str | None) -> Principal:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise AuthError(401, "missing_token", "Bearer token required")
        token = authorization.split(" ", 1)[1].strip()
        try:
            claims = jwt.decode(
                token,
                self._key(token),
                algorithms=["RS256", "PS256"],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway,
                options={"require": ["exp", "iat", "sub", "jti"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError(401, "invalid_token", str(exc)) from exc
        role = claims.get("role")
        if role not in ("member", "provider"):
            raise AuthError(401, "invalid_token", "Unknown role")
        return Principal(
            sub=claims["sub"],
            role=role,
            member_ref=claims.get("member_ref"),
            scopes=set(str(claims.get("scope", "")).split()),
            session_ref=claims.get("sid"),
            actor=(claims.get("act") or {}).get("sub"),
            confirmed_action=claims.get("confirmed_action"),
            jti=claims["jti"],
            claims=claims,
        )

    def consume_confirmation(self, principal: Principal, kind: str, params: dict[str, Any]) -> str:
        """Writes need a one-time confirmation that matches exactly what is being written."""
        ca = principal.confirmed_action
        if not ca or ca.get("kind") != kind:
            raise AuthError(403, "confirmation_required", "This action needs the member's or provider's confirmation")
        if ca.get("params_sha256") != params_sha256(params):
            raise AuthError(403, "confirmation_mismatch", "Request does not match the confirmed action")
        now = time.time()
        with self._lock:
            for k, exp in list(self._used_jti.items()):
                if exp < now:
                    del self._used_jti[k]
            if principal.jti in self._used_jti:
                raise AuthError(409, "confirmation_replayed", "This confirmation was already used")
            self._used_jti[principal.jti] = float(principal.claims.get("exp", now + 600))
        return str(ca.get("id"))
