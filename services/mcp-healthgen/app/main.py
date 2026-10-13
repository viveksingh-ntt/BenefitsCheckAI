"""HealthGen MCP data spoke (Streamable HTTP, stateless, JSON responses).

    POST /mcp                        MCP endpoint for Foundry agents (Bearer: Entra token or key, see MCP_AUTH)
    GET  /internal/cards/{card_ref}  card data for the agent relay (Bearer: relay credential)
    GET  /healthz

Run:  uvicorn app.main:app --port 8103
"""

from __future__ import annotations

import hmac
import json
import logging
import os
from typing import Any, Callable

import jwt
from jwt import PyJWKClient
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from .cards import CardStore
from .clients import BrokerClient, CoreClient, HandoffClient
from .tools import Deps, register

log = logging.getLogger("healthgen.mcp")

INSTRUCTIONS = (
    "HealthGen member data tools. Always pass the session_ref you were given; never ask the user for member ids. "
    "Tools return card_ref values: put the most relevant one in your reply envelope instead of restating every detail. "
    "Writes are two-step: prepare_* then, only after the user confirms in the card, submit_*."
)


class Authenticator:
    """Validates a bearer credential: Entra access tokens (managed identities) or static keys (dev)."""

    def __init__(self, mode: str, keys: dict[str, str] | None = None, tenant: str | None = None, audiences: list[str] | None = None,
                 clients: dict[str, str] | None = None, jwks_client: Any = None):
        self.mode = mode
        self.keys = keys or {}
        self.tenant = tenant
        self.audiences = audiences or []
        self.clients = clients or {}  # client/app id -> caller name
        self._jwks = jwks_client or (PyJWKClient(f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys", cache_keys=True) if mode == "entra" else None)

    @staticmethod
    def pairs(raw: str) -> dict[str, str]:
        out = {}
        for part in filter(None, (p.strip() for p in raw.split(","))):
            k, _, v = part.partition("=")
            out[k.strip()] = v.strip()
        return out

    def caller(self, authorization: str | None, extra_key: str | None = None) -> str | None:
        if self.mode == "none":
            return "anonymous"
        token = (authorization or "").split(" ", 1)[1].strip() if (authorization or "").lower().startswith("bearer ") else (extra_key or "")
        if not token:
            return None
        if self.mode == "keys":
            return next((name for name, key in self.keys.items() if key and hmac.compare_digest(key, token)), None)
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], audience=self.audiences, leeway=30)
        except jwt.PyJWTError as exc:
            log.info("rejected token: %s", exc)
            return None
        if claims.get("iss") not in (f"https://login.microsoftonline.com/{self.tenant}/v2.0", f"https://sts.windows.net/{self.tenant}/"):
            return None
        return self.clients.get(claims.get("azp") or claims.get("appid") or "")

    @classmethod
    def from_env(cls, prefix: str) -> "Authenticator":
        mode = os.getenv(f"{prefix}_AUTH", "entra")
        if mode == "keys":
            return cls("keys", keys=cls.pairs(os.environ[f"{prefix}_KEYS"]))
        if mode == "none":
            return cls("none")
        return cls("entra", tenant=os.environ["ENTRA_TENANT_ID"], audiences=os.environ[f"{prefix}_AUDIENCES"].split(","),
                   clients={v: k for k, v in cls.pairs(os.environ[f"{prefix}_CLIENTS"]).items()})


class GuardMcp:
    """Rejects unauthenticated MCP traffic before it reaches the MCP session manager."""

    def __init__(self, app: ASGIApp, auth: Authenticator, path: str = "/mcp"):
        self.app = app
        self.auth = auth
        self.path = path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].rstrip("/") == self.path:
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            caller = self.auth.caller(headers.get("authorization"), headers.get("x-mcp-key"))
            if not caller:
                resp = JSONResponse({"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
                await resp(scope, receive, send)
                return
            scope.setdefault("state", {})["caller"] = caller
        await self.app(scope, receive, send)


def credential_from_env() -> Callable[[], str]:
    """How this service authenticates to the broker: a dev key, or a managed identity token for the broker's app id."""
    key = os.getenv("BROKER_CLIENT_KEY")
    if key:
        return lambda: key
    resource = os.environ["BROKER_ENTRA_RESOURCE"]
    from .msi import ManagedIdentityCredential

    cred = ManagedIdentityCredential(os.getenv("AZURE_CLIENT_ID"))
    return lambda: cred.token(resource)


def create_app(deps: Deps | None = None, mcp_auth: Authenticator | None = None, internal_auth: Authenticator | None = None,
               allowed_hosts: list[str] | None = None) -> Any:
    deps = deps or Deps(
        broker=BrokerClient(os.environ["BROKER_URL"], credential_from_env()),
        core=CoreClient(os.environ["CORE_URL"]),
        cards=CardStore(),
        handoff=HandoffClient(os.getenv("HANDOFF_WEBHOOK_URL"), os.getenv("HANDOFF_WEBHOOK_SECRET")),
    )
    mcp_auth = mcp_auth or Authenticator.from_env("MCP")
    internal_auth = internal_auth or Authenticator.from_env("INTERNAL")
    hosts = allowed_hosts if allowed_hosts is not None else [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*").split(",") if h.strip()]

    server = MCPServer(name="healthgen-data", title="HealthGen data spoke", instructions=INSTRUCTIONS, version="0.1.0")
    register(server, deps)
    security = TransportSecuritySettings(enable_dns_rebinding_protection=bool(hosts), allowed_hosts=hosts, allowed_origins=[])
    app = server.streamable_http_app(streamable_http_path="/mcp", json_response=True, stateless_http=True, transport_security=security)

    async def get_card(request: Request) -> JSONResponse:
        if not internal_auth.caller(request.headers.get("authorization")):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        card = deps.cards.get(request.path_params["card_ref"], request.query_params.get("session_ref", ""))
        if not card:
            return JSONResponse({"error": "not_found"}, status_code=404)
        return JSONResponse(card, headers={"Cache-Control": "no-store"})

    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "mcp-healthgen", "tools": len(await server.list_tools())})

    app.router.routes.append(Route("/internal/cards/{card_ref}", get_card))
    app.router.routes.append(Route("/healthz", healthz))
    app.add_middleware(GuardMcp, auth=mcp_auth)
    app.state.deps = deps
    app.state.server = server
    return app


class _Lazy:
    def __init__(self) -> None:
        self._app: Any = None

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if self._app is None:
            logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
            self._app = create_app()
        await self._app(scope, receive, send)


app = _Lazy()

if __name__ == "__main__":  # pragma: no cover
    print(json.dumps({"tools": "run with uvicorn app.main:app"}))
