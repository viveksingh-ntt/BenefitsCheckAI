"""Local stand-in for Foundry Agent Service + the APIM gateway, so the whole stack runs on a laptop.

NOT an LLM. It is a scripted router that speaks the same HTTP contract the relay uses in Azure
(POST {project}/openai/v1/conversations, POST {project}/openai/v1/responses with agent_reference), checks the
X-User-Context token like the APIM policy does, calls the REAL MCP data spoke for every member-specific answer,
and answers plan questions from search/documents with a keyword search. Use it to exercise identity, cards,
HITL and hand-off end to end; use the real agents in Foundry to judge conversation quality.

    uvicorn app:app --port 8105
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sys
from pathlib import Path
from typing import Any

import httpx2
import jwt
from jwt import PyJWKClient
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

log = logging.getLogger("healthgen.foundry-local")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "search"))
from ingest import chunks  # noqa: E402

SERVICE_CODES = {"derm-skin-exam": "svc_focused_skin_exam"}


def envelope(reply: str, **kw: Any) -> dict[str, Any]:
    return {"reply": reply, **{k: v for k, v in kw.items() if v is not None}}


def chip(title: str, recommended: bool = False) -> dict[str, Any]:
    return {"title": title, "recommended": recommended}


class PlanSearch:
    def __init__(self) -> None:
        self.docs = [c for p in sorted((ROOT / "search" / "documents").glob("*.md")) for c in chunks(p)]

    def best(self, query: str, plan: str | None) -> dict[str, Any] | None:
        words = {w for w in re.findall(r"[a-z]{4,}", query.lower())} - {"what", "does", "with", "have", "need", "plan", "much"}
        scored = []
        for d in self.docs:
            hay = f"{d['section']} {d['content']}".lower()
            score = sum(hay.count(w) for w in words) + (3 if plan and plan in d["plan"] else 0) + 2 * sum(w in d["section"].lower() for w in words)
            scored.append((score, d))
        scored.sort(key=lambda x: -x[0])
        return scored[0][1] if scored and scored[0][0] > 0 else None


class Scripted:
    """Routing rules standing in for triage + specialists."""

    def __init__(self, mcp_url: str, mcp_key: str):
        self.mcp_url = mcp_url
        self.mcp_key = mcp_key
        self.memory: dict[str, dict[str, Any]] = {}
        self.search = PlanSearch()

    async def tool(self, name: str, **args: Any) -> dict[str, Any]:
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {self.mcp_key}"}, trust_env=False, timeout=60) as hc:
            async with Client(streamable_http_client(self.mcp_url, http_client=hc)) as client:
                res = await client.call_tool(name, args)
        if res.is_error:
            text = res.content[0].text if res.content else "error"
            raise ToolFailure(text)
        return res.structured_content or {}

    async def answer(self, conv_id: str, text: str) -> dict[str, Any]:
        ctx = dict(re.findall(r"^(session_ref|portal|locale|page): (.+)$", text, re.M))
        body = text.split("[/turn-context]", 1)[-1].strip()
        mem = self.memory.setdefault(conv_id, {"service_ref": "svc_focused_skin_exam"})
        sref = ctx.get("session_ref", "")
        provider_portal = ctx.get("portal") == "provider"
        kv = dict(re.findall(r"\b(service_ref|provider_ref|slot_ref|zip|radius_miles|service_code)=([A-Za-z0-9_-]+)", body))
        req = re.search(r"\brequest=(.+?)(?:, [a-z_]+=|\.?$)", body, re.M)
        if req:
            kv["request"] = req.group(1)
        if "service_code" in kv:
            kv.setdefault("service_ref", SERVICE_CODES.get(kv["service_code"], mem["service_ref"]))
        for k in ("service_ref", "provider_ref", "slot_ref", "zip", "radius_miles"):
            if k in kv:
                mem[k] = kv[k].strip()
        low = body.lower()
        try:
            m = re.search(r"confirmed request (act_[0-9a-f]{32}).*?Call (submit_\w+)", body)
            if m:
                out = await self.tool(m.group(2), session_ref=sref, action_id=m.group(1))
                if m.group(2) == "submit_referral":
                    return envelope("The referral is submitted.", card_ref=out.get("card_ref"), result_chip="Referral submitted", breadcrumb="Referral",
                                    suggestions=[chip("Find another doctor"), chip("Check benefits")])
                return envelope("You're booked.", card_ref=out.get("card_ref"), result_chip="Appointment booked", breadcrumb="Confirmation",
                                follow_up="Remember to ask your PCP for the dermatology referral before the visit.",
                                suggestions=[chip("Check referral rules", True), chip("Compare copays")])
            if "talk to a person" in low or re.search(r"\b(human|agent|representative)\b", low):
                out = await self.tool("request_human_handoff", session_ref=sref, reason="user_request", topic="Member asked for a care specialist")
                return envelope(f"I've asked a care specialist to follow up. Typical response time is {out.get('expected_response')}.",
                                handoff={"ticket_ref": out.get("ticket_ref"), "reason": "user_request"}, result_chip=f"Hand-off ticket {out.get('ticket_ref')} created")
            if "(appointment.review)" in body:
                out = await self.tool("prepare_appointment_request", session_ref=sref, provider_ref=mem["provider_ref"], slot_ref=mem["slot_ref"], service_ref=mem["service_ref"])
                return envelope("Here's your request. Check the details, then confirm.", card_ref=out["card_ref"], breadcrumb="Appointment review")
            if "(referral.review)" in body:
                out = await self.tool("prepare_referral", session_ref=sref, to_provider_ref=mem.get("provider_ref", "prv_19"), service_ref=mem["service_ref"])
                return envelope("I've drafted the referral. Review it and submit when ready.", card_ref=out["card_ref"], breadcrumb="Referral review")
            if "(appointment.availability)" in body or "availability" in low:
                out = await self.tool("get_availability", session_ref=sref, provider_ref=mem.get("provider_ref", "prv_19"), service_ref=mem["service_ref"])
                if not out.get("card_ref"):
                    return envelope("There are no open times in the next few days. Try another doctor.", suggestions=[chip("Find dermatologists", True)])
                return envelope("Here are the next open times. Choosing one doesn't book it.", card_ref=out["card_ref"], breadcrumb="Availability",
                                suggestions=[chip("Compare copays"), chip("Check referral rules")])
            if re.search(r"\((providers\.search|providers\.back|service\.find)\)", body) or re.search(r"doctor|dermatolog|in-network|find care", low):
                args = {"session_ref": sref, "service_ref": mem["service_ref"]}
                if mem.get("zip"):
                    args["zip"] = mem["zip"]
                if mem.get("radius_miles"):
                    args["radius_miles"] = int(mem["radius_miles"])
                out = await self.tool("find_providers", **args)
                if not out.get("card_ref"):
                    return envelope("I couldn't find in-network doctors in that distance. Try a wider radius.", suggestions=[chip("Within 10 miles", True)])
                first = out["providers"][0]["name"]
                follow = (f"{first} is selected. Review referral prepares details for approval; nothing is sent until you submit."
                          if provider_portal else f"{first} is selected. You'll review any appointment before confirming.")
                return envelope("These doctors match the plan and service." if provider_portal else "Here are in-network dermatologists near you.",
                                card_ref=out["card_ref"], result_chip="Service and plan network matched", breadcrumb="Find care", follow_up=follow,
                                suggestions=[chip("Check benefits", True), chip("Compare locations")])
            if re.search(r"referral rule|how long|valid|appeal|prior auth|what is|what's a", low):
                plan = "PPO" if "ppo" in low else "HMO"
                doc = self.search.best(body, plan)
                if not doc:
                    return envelope("I couldn't find that in the plan documents. A care specialist can help.", suggestions=[chip("Talk to a person", True)])
                return envelope(f"{doc['content'][:420]} ({doc['title']}, {doc['section']})", breadcrumb="Plan FAQ",
                                suggestions=[chip("Check my benefits", True), chip("Find dermatologists")])
            if re.search(r"deductible|out of pocket|out-of-pocket", low):
                out = await self.tool("get_accumulators", session_ref=sref)
                d = out["deductible"]
                return envelope(f"You've met ${d['individual_met']:,.0f} of your ${d['individual_limit']:,.0f} deductible; ${d['individual_remaining']:,.0f} remains this year.",
                                result_chip="Accumulators reviewed", suggestions=[chip("Check benefits", True)])
            if "find a covered service" not in low and re.search(r"cover|copay|cost|benefit|pay", low):
                out = await self.tool("check_benefits", session_ref=sref, service_ref=mem["service_ref"])
                row = out["benefits"][0]
                reply = ("Yes. A medical skin exam is covered when medically necessary. "
                         f"Estimated cost is ${row['in_network']['copay']:.0f} per visit" + (", and you need a PCP referral first." if row.get("referral_required") else "."))
                return envelope(reply, card_ref=out.get("card_ref"), result_chip="Plan eligibility and benefits reviewed", breadcrumb="Benefit check",
                                follow_up="You can find this service next.",
                                suggestions=[chip("Find dermatologists", True), chip("Check referral rules"), chip("Compare copays")])
            if "find a covered service" in low or re.search(r"skin exam|skin check|mole", low):
                out = await self.tool("search_services", session_ref=sref, query=kv.get("request") or "skin exam mole")
                return envelope("A focused skin exam matches your request. Choose an option to find an in-network dermatologist.",
                                card_ref=out.get("card_ref"), result_chip="Service options matched to your plan", breadcrumb="Find care",
                                suggestions=[chip("Check benefits", True), chip("Find doctors", True)])
        except ToolFailure as exc:
            log.info("tool failure: %s", exc)
            return envelope("Sorry, I couldn't complete that. " + str(exc).split(": ", 1)[-1], suggestions=[chip("Talk to a person")])
        return envelope("I can check your benefits, find in-network doctors and help you book. What would you like to do?",
                        suggestions=[chip("Check benefits", True), chip("Find a doctor"), chip("Talk to a person")])


class ToolFailure(Exception):
    pass


def create_app() -> Starlette:
    project = os.getenv("FOUNDRY_PROJECT", "healthgen")
    agent_name = os.getenv("FOUNDRY_AGENT_NAME", "healthgen-triage")
    key = os.getenv("FOUNDRY_LOCAL_KEY", "dev-foundry-key")
    broker_issuer = os.environ["BROKER_ISSUER"]
    jwks = PyJWKClient(os.environ["BROKER_JWKS_URL"], cache_keys=True)
    scripted = Scripted(os.environ["MCP_URL"].rstrip("/") + "/mcp", os.environ["MCP_KEY"])
    conversations: set[str] = set()

    def gateway(request: Request) -> JSONResponse | None:
        """What the APIM policy does: caller credential + a valid broker user-context token."""
        if request.headers.get("authorization") != f"Bearer {key}":
            return JSONResponse({"error": {"code": "unauthorized"}}, status_code=401)
        uctx = request.headers.get("x-user-context", "")
        try:
            jwt.decode(uctx, jwks.get_signing_key_from_jwt(uctx).key, algorithms=["RS256"], audience="healthgen-agent-gateway", issuer=broker_issuer)
        except Exception as exc:  # noqa: BLE001
            log.info("user context rejected: %s", exc)
            return JSONResponse({"error": {"code": "session_required"}}, status_code=401)
        return None

    async def create_conversation(request: Request) -> JSONResponse:
        if (denied := gateway(request)) is not None:
            return denied
        cid = f"conv_{secrets.token_hex(12)}"
        conversations.add(cid)
        return JSONResponse({"id": cid, "object": "conversation"})

    async def responses(request: Request) -> JSONResponse:
        if (denied := gateway(request)) is not None:
            return denied
        body = await request.json()
        ref = body.get("agent_reference") or {}
        if ref.get("name") != agent_name or any(k in body for k in ("model", "instructions", "tools")):
            return JSONResponse({"error": {"code": "gateway_policy"}}, status_code=403)
        cid = body.get("conversation")
        if cid not in conversations:
            return JSONResponse({"error": {"code": "conversation_not_found"}}, status_code=404)
        items = body.get("input") or []
        text = items[-1]["content"] if items and isinstance(items[-1].get("content"), str) else ""
        env = await scripted.answer(cid, text)
        out_text = json.dumps(env)
        return JSONResponse({"id": f"resp_{secrets.token_hex(8)}", "object": "response", "status": "completed",
                             "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": out_text}]}]})

    async def handoff_stub(request: Request) -> JSONResponse:
        """Stand-in for the n8n webhook in local runs (signature not checked here; the n8n workflow checks it)."""
        payload = await request.json()
        log.info("hand-off requested: %s", {k: payload.get(k) for k in ("reason", "audience")})
        return JSONResponse({"ticket_ref": f"HO-{secrets.randbelow(9000) + 1000}", "queue": "care-team", "expected_response": "under 10 minutes during business hours"})

    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "foundry-local", "note": "scripted stand-in, not an LLM"})

    base = f"/api/projects/{project}/openai/v1"
    return Starlette(routes=[
        Route("/healthz", healthz),
        Route(f"{base}/conversations", create_conversation, methods=["POST"]),
        Route(f"{base}/responses", responses, methods=["POST"]),
        Route("/webhook/healthgen-handoff", handoff_stub, methods=["POST"]),
    ])


class _Lazy:
    def __init__(self) -> None:
        self._app: Starlette | None = None

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if self._app is None:
            logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
            self._app = create_app()
        await self._app(scope, receive, send)


app = _Lazy()
