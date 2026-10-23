"""AG-UI chat tokens: the broker's side of the AG-UI channel (used instead of Direct Line tokens).

    portal BFF ──assertion──▶ POST /v1/agui/token  → {token, threadId, userId, expires_in}

The token is a short JWT (aud ``healthgen-agui``) that the relay's AG-UI host checks on every run:
``sub`` = a random ``agui_`` user id, ``tid`` = the thread id it may drive. Behind it the broker keeps the same
binding it keeps for Direct Line (user id + thread ↔ portal user ↔ session_ref), so ``/v1/sessions/resolve``,
confirmations and token exchange work unchanged. No member ids or session refs go into the chat token.

The response deliberately mirrors the Direct Line token shape (``token``, ``conversationId``, ``userId``,
``expires_in``) so the widget's existing ``tokenUrl`` / ``getToken`` plumbing works for both channels.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .auth import AuthError, PortalAssertionVerifier, bearer
from .signer import Signer, standard_claims
from .store import Binding, SqliteStore, new_ref

log = logging.getLogger("healthgen.broker.agui")

AGUI_AUDIENCE = os.getenv("AGUI_TOKEN_AUDIENCE", "healthgen-agui")
AGUI_TOKEN_TTL = int(os.getenv("AGUI_TOKEN_TTL_SECONDS", "1800"))


def agui_routes(settings: Any, signer: Signer, store: SqliteStore, portal: PortalAssertionVerifier,
                audience: str = AGUI_AUDIENCE, ttl: int = AGUI_TOKEN_TTL) -> list[Route]:
    """Routes added to the broker app by ``main_agui.create_app``. ``settings`` is ``main.Settings``."""

    def err(status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse({"error": code, "error_description": message}, status_code=status)

    def live(b: Binding | None) -> bool:
        now = time.time()
        return bool(b and not b.revoked and b.expires_at > now and b.created_at + settings.session_max > now)

    def issue(b: Binding) -> JSONResponse:
        claims = standard_claims(settings.issuer, audience, b.dl_user_id, ttl)
        claims.update({"tid": b.conversation_id, "typ": "agui-chat"})
        return JSONResponse({
            "token": signer.sign(claims),
            "conversationId": b.conversation_id,
            "threadId": b.conversation_id,
            "userId": b.dl_user_id,
            "expires_in": ttl,
        }, headers={"Cache-Control": "no-store"})

    async def agui_token(request: Request) -> JSONResponse:
        try:
            user = portal.verify(bearer(request.headers.get("authorization")))
        except AuthError as exc:
            return err(exc.status, exc.code, str(exc))
        body = await request.json() if await request.body() else {}
        if not isinstance(body, dict):
            return err(400, "invalid_request", "JSON object expected")
        reason = body.get("reason", "start")
        thread_id = body.get("conversationId") or body.get("threadId")
        if reason in ("refresh", "resume") and isinstance(thread_id, str):
            b = store.binding_by_conversation(thread_id)
            if b and b.dl_user_id.startswith("agui_") and live(b) and b.principal_ref == user.principal_ref and b.member_ref == user.member_ref:
                store.extend(b.session_ref, min(time.time() + settings.session_idle, b.created_at + settings.session_max))
                return issue(b)
            # Another member in context, unknown or ended thread: start a fresh one.
        now = time.time()
        b = Binding(
            session_ref=new_ref("ses"), dl_user_id=f"agui_{secrets.token_hex(16)}", conversation_id=f"thr_{secrets.token_hex(16)}",
            principal_ref=user.principal_ref, role=user.role, member_ref=user.member_ref, portal=user.portal,
            idm_session=user.idm_session, display_name=user.display_name, created_at=now, expires_at=now + settings.session_idle,
        )
        store.put_binding(b)
        log.info("session %s bound to an AG-UI thread (%s portal)", b.session_ref, b.portal)
        return issue(b)

    return [Route("/v1/agui/token", agui_token, methods=["POST"])]
