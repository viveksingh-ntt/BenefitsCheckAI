"""Identity broker.

Binds a Direct Line user to the portal user, gives the relay a short user-context token for APIM, keeps
pending write actions (human-in-the-loop) and performs RFC 8693 token exchange for the MCP data spoke.

    portal BFF ──assertion──▶ POST /v1/directline/token     → Direct Line token for dl_<random> (+ binding)
    agent relay ────────────▶ POST /v1/sessions/resolve     → session_ref + user-context JWT (aud: APIM)
    MCP server ─────────────▶ POST /v1/actions              → pending action (review card), action_id
    agent relay ────────────▶ GET  /v1/actions/{id}         → authoritative review summary for the card
    agent relay ────────────▶ POST /v1/actions/{id}/confirm → user pressed Confirm in the card
    MCP server ─────────────▶ POST /oauth2/token            → downstream JWT for HealthGen core (+ one-time
                                                              confirmed_action claim when exchanging a confirmed action)
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .auth import AuthError, PortalAssertionVerifier, ServiceAuthenticator, bearer
from .directline import DirectLineClient, DirectLineError
from .signer import Signer, signer_from_env, standard_claims
from .store import Action, Binding, SqliteStore, new_ref

log = logging.getLogger("healthgen.broker")

TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
SESSION_REF_TYPE = "urn:healthgen:params:oauth:token-type:session-ref"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"

READ_SCOPES = {
    "members.read", "eligibility.read", "accumulators.read", "benefits.read",
    "priorauth.read", "services.read", "providers.read",
}

ACTION_KINDS: dict[str, dict[str, Any]] = {
    "appointment.request": {"roles": {"member"}, "scope": "appointment.request",
                            "params": ("member_ref", "provider_ref", "slot_ref", "service_ref"), "extras": ("note",)},
    "referral.submit": {"roles": {"provider"}, "scope": "referral.submit",
                        "params": ("member_ref", "to_provider_ref", "service_ref", "visits"), "extras": ("reason",)},
}


def params_sha256(params: dict[str, Any]) -> str:
    import hashlib
    import json

    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class Settings:
    issuer: str
    core_audience: str = "healthgen-core"
    user_context_audience: str = "healthgen-agent-gateway"
    user_context_ttl: int = 600
    downstream_ttl: int = 300
    session_idle: int = 3600
    session_max: int = 12 * 3600
    action_ttl: int = 900
    trusted_origins: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            issuer=os.environ["BROKER_ISSUER"],
            core_audience=os.getenv("CORE_AUDIENCE", "healthgen-core"),
            user_context_audience=os.getenv("USER_CONTEXT_AUDIENCE", "healthgen-agent-gateway"),
            session_idle=int(os.getenv("SESSION_IDLE_SECONDS", "3600")),
            session_max=int(os.getenv("SESSION_MAX_SECONDS", str(12 * 3600))),
            trusted_origins=[o.strip() for o in os.getenv("DIRECTLINE_TRUSTED_ORIGINS", "").split(",") if o.strip()],
        )


def err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": code, "error_description": message}, status_code=status)


def create_app(
    settings: Settings | None = None,
    signer: Signer | None = None,
    store: SqliteStore | None = None,
    directline: DirectLineClient | None = None,
    portal: PortalAssertionVerifier | None = None,
    services: ServiceAuthenticator | None = None,
) -> Starlette:
    settings = settings or Settings.from_env()
    signer = signer or signer_from_env()
    store = store or SqliteStore(os.getenv("BROKER_DB_PATH", ":memory:"))
    directline = directline or DirectLineClient(os.environ["DIRECTLINE_SECRET"], os.getenv("DIRECTLINE_ENDPOINT", "https://directline.botframework.com"))
    portal = portal or PortalAssertionVerifier.from_env()
    services = services or ServiceAuthenticator.from_env()

    def guarded(fn):
        async def handler(request: Request) -> JSONResponse:
            try:
                return await fn(request)
            except AuthError as exc:
                log.info("denied %s: %s", request.url.path, exc.code)
                return err(exc.status, exc.code, str(exc))
            except DirectLineError as exc:
                log.warning("direct line: %s", exc)
                return err(502 if exc.status >= 500 else 503, "directline_unavailable", "Chat service is unavailable")
            except (KeyError, ValueError, TypeError) as exc:
                return err(400, "invalid_request", str(exc))
        return handler

    def live_binding(b: Binding | None) -> Binding:
        now = time.time()
        if not b or b.revoked or b.expires_at < now or b.created_at + settings.session_max < now:
            raise AuthError(401, "session_inactive", "Session has ended; start a new conversation")
        return b

    def touch(b: Binding) -> None:
        store.extend(b.session_ref, min(time.time() + settings.session_idle, b.created_at + settings.session_max))

    # ------------------------------------------------------------ portal facing

    @guarded
    async def directline_token(request: Request) -> JSONResponse:
        user = portal.verify(bearer(request.headers.get("authorization")))
        body = await request.json() if await request.body() else {}
        reason = body.get("reason", "start")
        conversation_id = body.get("conversationId")
        if reason in ("refresh", "resume") and conversation_id:
            b = store.binding_by_conversation(conversation_id)
            if b and not b.revoked and b.principal_ref == user.principal_ref and b.member_ref == user.member_ref:
                b = live_binding(b)
                conv = await run_in_threadpool(directline.reconnect, conversation_id, body.get("watermark"))
                touch(b)
                return JSONResponse({
                    "token": conv["token"], "conversationId": conv.get("conversationId", conversation_id),
                    "expires_in": conv.get("expires_in", 3600), "streamUrl": conv.get("streamUrl"), "userId": b.dl_user_id,
                })
            # Different member in context, unknown or ended conversation: fall through to a fresh one.
        dl_user_id = f"dl_{secrets.token_hex(16)}"
        gen = await run_in_threadpool(directline.generate_token, dl_user_id, None, settings.trusted_origins or None)
        now = time.time()
        b = Binding(
            session_ref=new_ref("ses"), dl_user_id=dl_user_id, conversation_id=gen["conversationId"],
            principal_ref=user.principal_ref, role=user.role, member_ref=user.member_ref, portal=user.portal,
            idm_session=user.idm_session, display_name=user.display_name, created_at=now, expires_at=now + settings.session_idle,
        )
        store.put_binding(b)
        log.info("session %s bound (%s portal)", b.session_ref, b.portal)
        return JSONResponse({
            "token": gen["token"], "conversationId": gen["conversationId"], "expires_in": gen.get("expires_in", 3600),
            "streamUrl": gen.get("streamUrl"), "userId": dl_user_id,
        })

    @guarded
    async def directline_logout(request: Request) -> JSONResponse:
        user = portal.verify(bearer(request.headers.get("authorization")))
        if not user.idm_session:
            raise ValueError("Portal assertion has no idm_session to end")
        count = store.revoke_idm_session(user.idm_session)
        return JSONResponse({"revoked": count})

    # ------------------------------------------------------------- relay facing

    @guarded
    async def resolve_session(request: Request) -> JSONResponse:
        services.authenticate(request.headers.get("authorization"), {"agent-relay"})
        body = await request.json()
        b = live_binding(store.binding_by_dl_user(str(body["dl_user_id"])))
        if b.conversation_id != body.get("conversation_id"):
            raise AuthError(403, "conversation_mismatch", "Direct Line user does not belong to this conversation")
        touch(b)
        claims = standard_claims(settings.issuer, settings.user_context_audience, b.session_ref, settings.user_context_ttl)
        claims.update({"sid": b.session_ref, "role": b.role, "portal": b.portal, "azp": "agent-relay"})
        return JSONResponse({
            "session_ref": b.session_ref,
            "role": b.role,
            "portal": b.portal,
            "display_name": b.display_name,
            "user_context_token": signer.sign(claims),
            "expires_in": settings.user_context_ttl,
        })

    @guarded
    async def session_status(request: Request) -> JSONResponse:
        services.authenticate(request.headers.get("authorization"), {"agent-relay", "apim", "mcp-healthgen"})
        b = store.binding_by_session(request.path_params["session_ref"])
        now = time.time()
        active = bool(b and not b.revoked and b.expires_at > now and b.created_at + settings.session_max > now)
        return JSONResponse({"active": active, "role": b.role if active and b else None})

    @guarded
    async def get_action(request: Request) -> JSONResponse:
        services.authenticate(request.headers.get("authorization"), {"agent-relay"})
        a = store.get_action(request.path_params["action_id"])
        if not a or a.session_ref != request.query_params.get("session_ref"):
            return err(404, "not_found", "No such action in this session")
        return JSONResponse({"action_id": a.action_id, "kind": a.kind, "status": a.status, "summary": a.summary,
                             "params": a.params, "expires_at": a.expires_at, "expired": a.expires_at < time.time()})

    @guarded
    async def confirm_action(request: Request) -> JSONResponse:
        services.authenticate(request.headers.get("authorization"), {"agent-relay"})
        body = await request.json()
        session_ref = str(body["session_ref"])
        live_binding(store.binding_by_session(session_ref))
        a = store.get_action(request.path_params["action_id"])
        if not a or a.session_ref != session_ref:
            return err(404, "not_found", "No such action in this session")
        allowed = ACTION_KINDS[a.kind]["extras"]
        extras = {k: str(v)[:300] for k, v in (body.get("extras") or {}).items() if k in allowed and v}
        if not store.transition(a.action_id, session_ref, "pending", "confirmed", extras):
            return err(409, "action_not_pending", "This request was already confirmed, cancelled or has expired")
        log.info("action %s (%s) confirmed in %s", a.action_id, a.kind, session_ref)
        return JSONResponse({"action_id": a.action_id, "status": "confirmed"})

    @guarded
    async def cancel_action(request: Request) -> JSONResponse:
        services.authenticate(request.headers.get("authorization"), {"agent-relay"})
        body = await request.json()
        ok = store.transition(request.path_params["action_id"], str(body["session_ref"]), "pending", "cancelled")
        return JSONResponse({"cancelled": ok})

    # --------------------------------------------------------------- MCP facing

    @guarded
    async def create_action(request: Request) -> JSONResponse:
        services.authenticate(request.headers.get("authorization"), {"mcp-healthgen"})
        body = await request.json()
        b = live_binding(store.binding_by_session(str(body["session_ref"])))
        kind = str(body["kind"])
        spec = ACTION_KINDS.get(kind)
        if not spec:
            raise ValueError(f"Unknown action kind {kind}")
        if b.role not in spec["roles"]:
            raise AuthError(403, "role_not_allowed", f"{b.role} cannot {kind}")
        params = dict(body["params"])
        if params.get("member_ref") not in (None, b.member_ref):
            raise AuthError(403, "member_mismatch", "Action is for a different member")
        params["member_ref"] = b.member_ref
        if set(params) != set(spec["params"]):
            raise ValueError(f"{kind} needs exactly {', '.join(spec['params'])}")
        now = time.time()
        store.cancel_pending(b.session_ref, kind)  # only the latest review card can be confirmed
        a = Action(action_id=new_ref("act"), session_ref=b.session_ref, kind=kind, params=params, status="pending",
                   summary=body.get("summary"), created_at=now, expires_at=now + settings.action_ttl)
        store.put_action(a)
        return JSONResponse({"action_id": a.action_id, "expires_at": a.expires_at}, status_code=201)

    @guarded
    async def token_exchange(request: Request) -> JSONResponse:
        service = services.authenticate(request.headers.get("authorization"), {"mcp-healthgen"})
        form = await request.form()
        if form.get("grant_type") != TOKEN_EXCHANGE:
            return err(400, "unsupported_grant_type", "Only token exchange is supported")
        if form.get("subject_token_type") != SESSION_REF_TYPE:
            return err(400, "invalid_request", "subject_token_type must be a HealthGen session ref")
        if form.get("audience", settings.core_audience) != settings.core_audience:
            return err(400, "invalid_target", "Unknown audience")
        try:
            b = live_binding(store.binding_by_session(str(form.get("subject_token"))))
        except AuthError:
            return err(400, "invalid_grant", "Session is not active")
        touch(b)
        claims = standard_claims(settings.issuer, settings.core_audience, b.principal_ref, settings.downstream_ttl)
        claims.update({"role": b.role, "member_ref": b.member_ref, "sid": b.session_ref, "act": {"sub": service}})
        extra: dict[str, Any] = {}
        action_id = form.get("action_id")
        if action_id:
            a = store.get_action(str(action_id))
            if not a or a.session_ref != b.session_ref:
                return err(400, "invalid_grant", "Unknown action")
            if a.status == "pending":
                return err(400, "confirmation_required", "The user has not confirmed this request yet")
            if not store.transition(a.action_id, b.session_ref, "confirmed", "consumed"):
                return err(400, "invalid_grant", "Action is not confirmed, already used or expired")
            scope = ACTION_KINDS[a.kind]["scope"]
            claims["confirmed_action"] = {"id": a.action_id, "kind": a.kind, "params_sha256": params_sha256(a.params)}
            extra["action"] = {"action_id": a.action_id, "kind": a.kind, "params": a.params, "extras": a.extras or {}}
            log.info("action %s consumed by %s", a.action_id, service)
        else:
            requested = set(str(form.get("scope") or " ".join(sorted(READ_SCOPES))).split())
            if not requested <= READ_SCOPES:
                return err(400, "invalid_scope", "Write scopes need a confirmed action")
            scope = " ".join(sorted(requested))
        claims["scope"] = scope
        return JSONResponse({
            "access_token": signer.sign(claims), "issued_token_type": ACCESS_TOKEN_TYPE, "token_type": "Bearer",
            "expires_in": settings.downstream_ttl, "scope": scope, **extra,
        }, headers={"Cache-Control": "no-store"})

    # ------------------------------------------------------------------ public

    async def jwks(request: Request) -> JSONResponse:
        return JSONResponse(await run_in_threadpool(signer.jwks), headers={"Cache-Control": "public, max-age=300"})

    async def discovery(request: Request) -> JSONResponse:
        return JSONResponse({
            "issuer": settings.issuer,
            "jwks_uri": settings.issuer.rstrip("/") + "/.well-known/jwks.json",
            "token_endpoint": settings.issuer.rstrip("/") + "/oauth2/token",
            "grant_types_supported": [TOKEN_EXCHANGE],
            "id_token_signing_alg_values_supported": ["RS256"],
        })

    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "identity-broker"})

    app = Starlette(routes=[
        Route("/healthz", healthz),
        Route("/.well-known/jwks.json", jwks),
        Route("/.well-known/openid-configuration", discovery),
        Route("/v1/directline/token", directline_token, methods=["POST"]),
        Route("/v1/directline/logout", directline_logout, methods=["POST"]),
        Route("/v1/sessions/resolve", resolve_session, methods=["POST"]),
        Route("/v1/sessions/{session_ref}/status", session_status),
        Route("/v1/actions", create_action, methods=["POST"]),
        Route("/v1/actions/{action_id}", get_action),
        Route("/v1/actions/{action_id}/confirm", confirm_action, methods=["POST"]),
        Route("/v1/actions/{action_id}/cancel", cancel_action, methods=["POST"]),
        Route("/oauth2/token", token_exchange, methods=["POST"]),
    ])
    app.state.store = store
    return app


class _Lazy:
    def __init__(self) -> None:
        self._app: Starlette | None = None

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if self._app is None:
            logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
            self._app = create_app()
        await self._app(scope, receive, send)


app = _Lazy()
