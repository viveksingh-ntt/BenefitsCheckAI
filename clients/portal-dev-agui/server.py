"""Portal stand-in for the AG-UI path: hosts the widget with AgUiTransport and plays the portal backend (BFF).

    uvicorn server:app --port 8081       (from clients/portal-dev-agui)

* GET  /                          host page; ?user=alex|jordan|raman switches the signed-in user
* POST /api/agent/agui-token      what a real portal BFF does: sign a short portal assertion for the signed-in user and
                                  exchange it at the identity broker (POST /v1/agui/token) for an AG-UI chat token
* GET  /.well-known/jwks.json     the portal's public key, which the broker trusts (PORTAL_JWKS_URL)
* GET  /widget/*                  the built widget (vendor/agent-widget.iife.js, which includes AgUiTransport)

The dev users are the same fixed, fake users as clients/portal-dev, imported from there so both pages agree.
"""

from __future__ import annotations

import importlib.util
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

HERE = Path(__file__).resolve().parent


def _dev_users() -> dict:
    spec = importlib.util.spec_from_file_location("portal_dev_users", HERE.parent / "portal-dev" / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.USERS


USERS = _dev_users()


def create_app() -> Starlette:
    issuer = os.getenv("PORTAL_ISSUER", "http://localhost:8081")
    broker = os.getenv("BROKER_URL", "http://localhost:8102").rstrip("/")
    agui_endpoint = os.getenv("AGUI_ENDPOINT", "http://localhost:8106/agui")
    widget_dist = Path(os.getenv("WIDGET_DIST", str(HERE / "vendor")))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = f"portal-agui-{uuid.uuid4().hex[:6]}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def current(request: Request) -> str:
        user = request.query_params.get("user") or request.cookies.get("dev_user") or "alex"
        return user if user in USERS else "alex"

    async def page(request: Request):
        user = current(request)
        if request.query_params.get("user"):
            resp = RedirectResponse("/", status_code=303)
            resp.set_cookie("dev_user", user, httponly=True, samesite="strict")
            return resp
        u = USERS[user]
        html = (HERE / "index.html").read_text(encoding="utf-8")
        html = html.replace("__CONFIG__", json.dumps({"user": user, "name": u["name"], "portal": u["portal"], "context": u["context"], "aguiEndpoint": agui_endpoint}))
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    async def jwks(request: Request) -> JSONResponse:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
        return JSONResponse({"keys": [jwk]})

    async def agui_token(request: Request) -> JSONResponse:
        name = current(request)
        u = USERS[name]
        now = int(time.time())
        claims = {"iss": issuer, "aud": "healthgen-identity-broker", "sub": u["sub"], "role": u["role"], "portal": u["portal"],
                  "name": u["name"], "idm_session": f"dev-{name}", "iat": now, "exp": now + 120, "jti": uuid.uuid4().hex}
        if u.get("member_ref"):
            claims["member_ref"] = u["member_ref"]
        assertion = jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})
        body = await request.body()
        req = urllib.request.Request(f"{broker}/v1/agui/token", data=body or b"{}", method="POST",
                                     headers={"Authorization": f"Bearer {assertion}", "Content-Type": "application/json"})

        def call() -> dict:
            with opener.open(req, timeout=15) as resp:
                return json.loads(resp.read())

        try:
            # In a worker thread: the broker calls back into this server for the portal JWKS.
            return JSONResponse(await run_in_threadpool(call), headers={"Cache-Control": "no-store"})
        except urllib.error.HTTPError as exc:
            return JSONResponse({"error": "broker_error", "status": exc.code}, status_code=502)
        except urllib.error.URLError:
            return JSONResponse({"error": "broker_unreachable"}, status_code=502)

    routes = [
        Route("/", page),
        Route("/.well-known/jwks.json", jwks),
        Route("/api/agent/agui-token", agui_token, methods=["POST"]),
    ]
    if widget_dist.exists():
        routes.append(Mount("/widget", app=StaticFiles(directory=str(widget_dist)), name="widget"))
    return Starlette(routes=routes)


app = create_app()
