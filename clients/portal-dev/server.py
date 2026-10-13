"""Portal stand-in for local runs: hosts the widget and plays the portal backend (BFF).

    uvicorn server:app --port 8080       (from clients/portal-dev)

* GET  /                              host page with <agent-widget>; ?user=alex|jordan|raman switches the signed-in user
* POST /api/agent/directline-token    what a real portal BFF does: sign a short portal assertion for the signed-in
                                      user and exchange it at the identity broker for a Direct Line token
* GET  /.well-known/jwks.json         the portal's public key, which the broker trusts (PORTAL_JWKS_URL)
* GET  /widget/*                      the built widget (agent-widget/dist)

Dev users are fixed and fake. In the real portals, the in-house IdM session decides who the user is.
"""

from __future__ import annotations

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
USERS = {
    "alex": {"sub": "mbr_7f3a", "role": "member", "portal": "member", "name": "Alex",
             "context": {"member": {"ref": "mbr_7f3a", "displayName": "Alex Morgan", "planName": "Harbor HMO", "idLast4": "4821", "status": "Active", "relationship": "self"},
                         "page": {"route": "/benefits", "breadcrumb": "Benefit check"}}},
    "jordan": {"sub": "mbr_2c91", "role": "member", "portal": "member", "name": "Jordan",
               "context": {"member": {"ref": "mbr_2c91", "displayName": "Jordan Lee", "planName": "Harbor PPO", "idLast4": "1307", "status": "Active", "relationship": "self"},
                           "page": {"route": "/benefits", "breadcrumb": "Benefit check"}}},
    "raman": {"sub": "prv_pcp_01", "role": "provider", "portal": "provider", "member_ref": "mbr_7f3a", "name": "Dr. Raman",
              "context": {"member": {"ref": "mbr_7f3a", "displayName": "Alex Morgan", "planName": "Harbor HMO", "idLast4": "4821", "status": "Active", "relationship": "patient"},
                          "provider": {"npi": "1093817465", "orgName": "Harbor Primary Care"},
                          "page": {"route": "/patients/mbr_7f3a", "breadcrumb": "Doctor search"}}},
}


def create_app() -> Starlette:
    issuer = os.getenv("PORTAL_ISSUER", "http://localhost:8080")
    broker = os.getenv("BROKER_URL", "http://localhost:8102").rstrip("/")
    directline = os.getenv("DIRECTLINE_DOMAIN", "http://localhost:8104/v3/directline")
    widget_dist = Path(os.getenv("WIDGET_DIST", str(HERE / "vendor")))  # a build of the agent-widget repo
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = f"portal-dev-{uuid.uuid4().hex[:6]}"
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
        html = html.replace("__CONFIG__", json.dumps({"user": user, "name": u["name"], "portal": u["portal"], "context": u["context"], "directLineDomain": directline}))
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    async def jwks(request: Request) -> JSONResponse:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
        return JSONResponse({"keys": [jwk]})

    async def directline_token(request: Request) -> JSONResponse:
        u = USERS[current(request)]
        now = int(time.time())
        claims = {"iss": issuer, "aud": "healthgen-identity-broker", "sub": u["sub"], "role": u["role"], "portal": u["portal"],
                  "name": u["name"], "idm_session": f"dev-{current(request)}", "iat": now, "exp": now + 120, "jti": uuid.uuid4().hex}
        if u.get("member_ref"):
            claims["member_ref"] = u["member_ref"]
        assertion = jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})
        body = await request.body()
        req = urllib.request.Request(f"{broker}/v1/directline/token", data=body or b"{}", method="POST",
                                     headers={"Authorization": f"Bearer {assertion}", "Content-Type": "application/json"})
        def call() -> dict:
            with opener.open(req, timeout=15) as resp:
                return json.loads(resp.read())

        try:
            # In a worker thread: the broker calls back into this server for the portal JWKS.
            return JSONResponse(await run_in_threadpool(call))
        except urllib.error.HTTPError as exc:
            return JSONResponse({"error": "broker_error", "status": exc.code}, status_code=502)
        except urllib.error.URLError:
            return JSONResponse({"error": "broker_unreachable"}, status_code=502)

    routes = [
        Route("/", page),
        Route("/.well-known/jwks.json", jwks),
        Route("/api/agent/directline-token", directline_token, methods=["POST"]),
    ]
    if widget_dist.exists():
        routes.append(Mount("/widget", app=StaticFiles(directory=str(widget_dist)), name="widget"))
    return Starlette(routes=routes)


app = create_app()
