"""Agent relay host for the AG-UI protocol (an alternative to host_m365.py + Azure Bot Service + Direct Line).

    uvicorn host_agui:app --port 8106

    POST /agui/run                  RunAgentInput (JSON) → text/event-stream of AG-UI events
    GET  /agui/threads/{threadId}   transcript + open interrupts, for page reloads
    GET  /healthz

Every request carries the broker's AG-UI chat token (``Authorization: Bearer``; aud ``healthgen-agui``). Its ``tid``
must equal the request's thread id, so a token drives exactly one thread. Behind the token the relay core runs
unchanged: broker session resolution, safe card actions, cards from data, confirmations, masking.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, AsyncIterator

import jwt
from jwt import PyJWKClient
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from relay.agui import EventMapper, InputError, ThreadStore, new_id, sse, to_activities, valid_id
from relay.core import RelayCore

log = logging.getLogger("healthgen.relay.agui")
MAX_BODY = 64 * 1024


class ChatTokenVerifier:
    """Checks the broker-issued AG-UI chat token (RS256, broker JWKS)."""

    def __init__(self, issuer: str, audience: str = "healthgen-agui", jwks_url: str | None = None, jwks: dict[str, Any] | None = None):
        self.issuer = issuer
        self.audience = audience
        self._client = PyJWKClient(jwks_url, cache_keys=True, lifespan=600) if jwks_url else None
        self._static = {k.get("kid"): jwt.PyJWK(k) for k in (jwks or {}).get("keys", [])}

    def verify(self, authorization: str | None) -> dict[str, Any] | None:
        if not authorization or not authorization.lower().startswith("bearer "):
            return None
        token = authorization.split(" ", 1)[1].strip()
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            key = self._static[kid].key if kid in self._static else (self._client.get_signing_key(kid).key if self._client else None)
            if key is None:
                return None
            claims = jwt.decode(token, key, algorithms=["RS256"], audience=self.audience, issuer=self.issuer, leeway=30,
                                options={"require": ["exp", "sub", "tid"]})
        except Exception as exc:  # noqa: BLE001 - any token problem is a 401
            log.info("chat token rejected: %s", type(exc).__name__)
            return None
        return claims if claims.get("typ") == "agui-chat" else None


def create_app(core: RelayCore | None = None, verifier: ChatTokenVerifier | None = None, threads: ThreadStore | None = None,
               origins: list[str] | None = None) -> Starlette:
    if core is None:
        from relay.factory import core_from_env

        core = core_from_env()
    verifier = verifier or ChatTokenVerifier(
        issuer=os.environ["BROKER_ISSUER"],
        audience=os.getenv("AGUI_TOKEN_AUDIENCE", "healthgen-agui"),
        jwks_url=os.getenv("BROKER_JWKS_URL", os.environ["BROKER_ISSUER"].rstrip("/") + "/.well-known/jwks.json"),
    )
    threads = threads or ThreadStore()
    origins = origins if origins is not None else [o.strip() for o in os.getenv("AGUI_CORS_ORIGINS", "").split(",") if o.strip()]

    def denied(status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse({"error": code, "message": message}, status_code=status)

    async def run(request: Request) -> Any:
        claims = verifier.verify(request.headers.get("authorization"))
        if not claims:
            return denied(401, "unauthorized", "A valid chat token is required")
        raw = await request.body()
        if len(raw) > MAX_BODY:
            return denied(413, "too_large", "Request too large")
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return denied(400, "invalid_json", "Body must be a RunAgentInput JSON object")
        if not isinstance(body, dict) or not valid_id(body.get("threadId")):
            return denied(400, "invalid_input", "threadId is required")
        if body["threadId"] != claims["tid"]:
            return denied(403, "thread_mismatch", "This token belongs to another thread")
        thread_id = body["threadId"]
        run_id = body["runId"] if valid_id(body.get("runId")) else new_id("run")
        thread = threads.get(thread_id)
        mapper = EventMapper(thread_id, run_id, thread)

        async def stream() -> AsyncIterator[bytes]:
            for ev in mapper.start():
                yield sse(ev)
            try:
                activities, direct = to_activities(body, claims["sub"], thread)
            except InputError as exc:
                for ev in mapper.error(exc.code, str(exc)):
                    yield sse(ev)
                return
            if direct:
                for ev in mapper.text(direct):
                    yield sse(ev)
            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

            async def send(activity: dict[str, Any]) -> None:
                await queue.put(activity)

            async def drive() -> None:
                try:
                    for act in activities:
                        await core.on_activity(act, send)
                finally:
                    await queue.put(None)

            task = asyncio.create_task(drive())
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    for ev in mapper.map(item):
                        yield sse(ev)
                await task
            except Exception:  # noqa: BLE001 - never leak internals to the client
                log.exception("AG-UI run failed")
                for ev in mapper.error("relay_error", "Something went wrong. Please try again."):
                    yield sse(ev)
                return
            finally:
                if not task.done():
                    task.cancel()
            for ev in mapper.finish():
                yield sse(ev)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    async def thread_snapshot(request: Request) -> JSONResponse:
        claims = verifier.verify(request.headers.get("authorization"))
        thread_id = request.path_params["thread_id"]
        if not claims:
            return denied(401, "unauthorized", "A valid chat token is required")
        if claims["tid"] != thread_id:
            return denied(403, "thread_mismatch", "This token belongs to another thread")
        st = threads.get(thread_id)
        return JSONResponse({
            "type": "MESSAGES_SNAPSHOT",
            "threadId": thread_id,
            "messages": st.messages,
            "state": st.state,
            "interrupts": [{k: v for k, v in i.items() if k != "verb"} for i in st.open_interrupts.values()],
        }, headers={"Cache-Control": "no-store"})

    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "agent-relay-agui"})

    return Starlette(
        routes=[
            Route("/healthz", healthz),
            Route("/agui/run", run, methods=["POST"]),
            Route("/agui/threads/{thread_id}", thread_snapshot),
        ],
        middleware=[Middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                               allow_headers=["Authorization", "Content-Type", "Accept"], max_age=600)],
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
