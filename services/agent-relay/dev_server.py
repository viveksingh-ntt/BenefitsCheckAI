"""Local Direct Line 3.0 emulator with the relay core in-process (no Azure Bot Service needed).

    uvicorn dev_server:app --port 8104

Implements the subset the widget and the identity broker use, over HTTP polling (no WebSocket stream):

    POST /v3/directline/tokens/generate                 (secret)  token bound to user.id, new conversation
    POST /v3/directline/tokens/refresh                  (token)
    POST /v3/directline/conversations                   (token)   returns the token's conversation
    GET  /v3/directline/conversations/{id}              (secret or token) fresh token, for resume
    POST /v3/directline/conversations/{id}/activities   (token)   from.id is forced to the token's user
    GET  /v3/directline/conversations/{id}/activities?watermark=N

Like enhanced authentication, a token only works for its own conversation and user. For local development only.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from relay.core import RelayCore

log = logging.getLogger("healthgen.dev-directline")
TOKEN_TTL = 1800


@dataclass
class Conversation:
    id: str
    user_id: str
    activities: list[dict[str, Any]] = field(default_factory=list)
    created: float = field(default_factory=time.time)


def create_app(core: RelayCore | None = None, secret: str | None = None, origins: list[str] | None = None) -> Starlette:
    if core is None:
        from relay.factory import core_from_env

        core = core_from_env()
    secret = secret or os.environ["DIRECTLINE_SECRET"]
    origins = origins if origins is not None else [o for o in os.getenv("DEV_CORS_ORIGINS", "http://localhost:8080").split(",") if o]
    conversations: dict[str, Conversation] = {}
    tokens: dict[str, tuple[str, float]] = {}  # token -> (conversation id, expiry)
    tasks: set[asyncio.Task] = set()

    def now_iso() -> str:
        return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")

    def issue(conv_id: str) -> dict[str, Any]:
        token = f"dlt_{secrets.token_urlsafe(24)}"
        tokens[token] = (conv_id, time.time() + TOKEN_TTL)
        return {"conversationId": conv_id, "token": token, "expires_in": TOKEN_TTL}

    def bearer(request: Request) -> str:
        auth = request.headers.get("authorization", "")
        return auth[7:].strip() if auth.lower().startswith("bearer ") else ""

    def conv_for_token(request: Request) -> Conversation | None:
        entry = tokens.get(bearer(request))
        if not entry or entry[1] < time.time():
            return None
        return conversations.get(entry[0])

    def denied(status: int = 403, msg: str = "Forbidden") -> JSONResponse:
        return JSONResponse({"error": {"code": "BadArgument" if status == 400 else "TokenOrSecretInvalid", "message": msg}}, status_code=status)

    def append(conv: Conversation, activity: dict[str, Any]) -> str:
        activity = dict(activity)
        activity["id"] = f"{conv.id}|{len(conv.activities):07d}"
        activity["timestamp"] = now_iso()
        activity["channelId"] = "directline"
        activity["conversation"] = {"id": conv.id}
        conv.activities.append(activity)
        return activity["id"]

    async def generate(request: Request) -> JSONResponse:
        if not secrets.compare_digest(bearer(request), secret):
            return denied()
        body = await request.json() if await request.body() else {}
        user_id = ((body.get("user") or {}).get("id")) or f"dl_{secrets.token_hex(8)}"
        if not user_id.startswith("dl_"):
            return denied(400, "User ids must start with dl_ when enhanced authentication is on")
        conv = Conversation(id=f"devconv-{secrets.token_hex(6)}", user_id=user_id)
        conversations[conv.id] = conv
        return JSONResponse(issue(conv.id))

    async def refresh(request: Request) -> JSONResponse:
        conv = conv_for_token(request)
        if not conv:
            return denied()
        tokens.pop(bearer(request), None)
        return JSONResponse(issue(conv.id))

    async def start_conversation(request: Request) -> JSONResponse:
        conv = conv_for_token(request)
        if not conv:
            return denied()
        return JSONResponse({"conversationId": conv.id, "token": bearer(request), "expires_in": int(tokens[bearer(request)][1] - time.time())}, status_code=201)

    async def get_conversation(request: Request) -> JSONResponse:
        conv = conversations.get(request.path_params["cid"])
        if not conv:
            return denied(404, "Conversation not found")
        if not secrets.compare_digest(bearer(request), secret):
            owner = conv_for_token(request)
            if not owner or owner.id != conv.id:
                return denied()
        return JSONResponse(issue(conv.id))

    async def post_activity(request: Request) -> JSONResponse:
        conv = conv_for_token(request)
        if not conv or conv.id != request.path_params["cid"]:
            return denied()
        activity = await request.json()
        activity["from"] = {**(activity.get("from") or {}), "id": conv.user_id, "role": "user"}  # enhanced auth behaviour
        activity_id = append(conv, activity)
        incoming = dict(conv.activities[-1])

        async def send(out: dict[str, Any]) -> None:
            append(conv, out)

        async def run() -> None:
            try:
                await core.on_activity(incoming, send)
            except Exception:  # noqa: BLE001 - surface any relay bug in the dev log, keep the server up
                log.exception("relay failed")
                append(conv, {"type": "message", "from": {"id": "care-assistant", "role": "bot"}, "text": "Relay error (see dev server log)."})

        task = asyncio.create_task(run())
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return JSONResponse({"id": activity_id})

    async def get_activities(request: Request) -> JSONResponse:
        conv = conv_for_token(request)
        if not conv or conv.id != request.path_params["cid"]:
            return denied()
        try:
            start = int(request.query_params.get("watermark") or 0)
        except ValueError:
            start = 0
        return JSONResponse({"activities": conv.activities[start:], "watermark": str(len(conv.activities))})

    async def upload(request: Request) -> JSONResponse:
        return JSONResponse({"error": {"code": "NotSupported", "message": "Uploads are not supported by the dev emulator"}}, status_code=501)

    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "dev-directline", "conversations": len(conversations)})

    prefix = "/v3/directline"
    return Starlette(
        routes=[
            Route("/healthz", healthz),
            Route(f"{prefix}/tokens/generate", generate, methods=["POST"]),
            Route(f"{prefix}/tokens/refresh", refresh, methods=["POST"]),
            Route(f"{prefix}/conversations", start_conversation, methods=["POST"]),
            Route(prefix + "/conversations/{cid}", get_conversation),
            Route(prefix + "/conversations/{cid}/activities", post_activity, methods=["POST"]),
            Route(prefix + "/conversations/{cid}/activities", get_activities, methods=["GET"]),
            Route(prefix + "/conversations/{cid}/upload", upload, methods=["POST"]),
        ],
        middleware=[Middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])],
    )


class _Lazy:
    def __init__(self) -> None:
        self._app: Starlette | None = None

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if self._app is None:
            logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
            self._app = create_app()
        await self._app(scope, receive, send)


app = _Lazy()
