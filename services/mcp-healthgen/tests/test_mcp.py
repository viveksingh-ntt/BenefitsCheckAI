"""Integration test: real MCP client → MCP server → identity broker → HealthGen core mock (all on localhost)."""

import contextlib
import datetime as dt
import hashlib
import hmac
import importlib
import json
import logging
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve()
SERVICES = HERE.parents[2]
sys.path[:0] = [str(HERE.parents[3] / "libs" / "testkit")]

import anyio  # noqa: E402
import httpx2  # noqa: E402
from mcp.client.client import Client  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from testkit import RsaKey, http, serve  # noqa: E402


def load_service(name: str):
    """Each service has a top-level ``app`` package; import them side by side under distinct names."""
    for mod in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]
    sys.path.insert(0, str(SERVICES / name))
    try:
        main = importlib.import_module("app.main")
        pkg = {m: sys.modules[m] for m in sys.modules if m == "app" or m.startswith("app.")}
    finally:
        sys.path.pop(0)
        for mod in list(pkg):
            del sys.modules[mod]
    return pkg


CORE = load_service("healthgen-core-mock")
BROKER = load_service("identity-broker")
MCP = load_service("mcp-healthgen")

logging.disable(logging.INFO)
PORTAL_ISS = "https://portal.test"
HANDOFF_SECRET = "hook-secret"


def fake_directline():
    n = {"i": 0}

    async def generate(request: Request):
        n["i"] += 1
        return JSONResponse({"conversationId": f"conv{n['i']}", "token": "t", "expires_in": 3600})

    return Starlette(routes=[Route("/v3/directline/tokens/generate", generate, methods=["POST"])])


def fake_n8n(received):
    async def hook(request: Request):
        raw = await request.body()
        ts = request.headers["x-healthgen-timestamp"]
        expected = "sha256=" + hmac.new(HANDOFF_SECRET.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, request.headers["x-healthgen-signature"]):
            return JSONResponse({"error": "bad signature"}, status_code=401)
        received.append(json.loads(raw))
        return JSONResponse({"ticket_ref": "HO-1001", "queue": "care-team"})

    return Starlette(routes=[Route("/webhook/handoff", hook, methods=["POST"])])


class McpIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = contextlib.ExitStack()
        cls.portal_key = RsaKey()
        signer = BROKER["app.signer"].LocalRsaSigner()
        dl = cls.stack.enter_context(serve(fake_directline()))
        bauth = BROKER["app.auth"]
        broker_app = BROKER["app.main"].create_app(
            settings=BROKER["app.main"].Settings(issuer="http://broker.test"),
            signer=signer,
            directline=BROKER["app.directline"].DirectLineClient("s", dl),
            portal=bauth.PortalAssertionVerifier(bauth.JwtVerifier([PORTAL_ISS], [bauth.PortalAssertionVerifier.AUDIENCE], jwks=cls.portal_key.jwks)),
            services=bauth.ServiceAuthenticator("keys", keys={"agent-relay": "k-relay", "mcp-healthgen": "k-mcp"}),
        )
        cls.broker = cls.stack.enter_context(serve(broker_app))
        core_app = CORE["app.main"].create_app(CORE["app.auth"].TokenValidator("http://broker.test", jwks=signer.jwks()), today=lambda: dt.date(2026, 10, 14))
        core = cls.stack.enter_context(serve(core_app))
        cls.handoffs = []
        n8n = cls.stack.enter_context(serve(fake_n8n(cls.handoffs)))
        clients = MCP["app.clients"]
        deps = MCP["app.tools"].Deps(
            broker=clients.BrokerClient(cls.broker, lambda: "k-mcp"),
            core=clients.CoreClient(core),
            cards=MCP["app.cards"].CardStore(),
            handoff=clients.HandoffClient(n8n + "/webhook/handoff", HANDOFF_SECRET),
        )
        A = MCP["app.main"].Authenticator
        mcp_app = MCP["app.main"].create_app(deps, A("keys", keys={"foundry": "k-foundry"}), A("keys", keys={"agent-relay": "k-relay-cards"}))
        cls.mcp = cls.stack.enter_context(serve(mcp_app))

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    # ---------------------------------------------------------------- helpers

    def session(self, sub="mbr_7f3a", role="member", **extra):
        assertion = self.portal_key.sign({"iss": PORTAL_ISS, "aud": "healthgen-identity-broker", "sub": sub, "role": role, **extra})
        _, tok = http("POST", self.broker + "/v1/directline/token", {}, {"Authorization": f"Bearer {assertion}"})
        _, ses = http("POST", self.broker + "/v1/sessions/resolve", {"dl_user_id": tok["userId"], "conversation_id": tok["conversationId"]}, {"Authorization": "Bearer k-relay"})
        return ses["session_ref"]

    def run_mcp(self, steps, key="k-foundry"):
        async def go():
            async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {key}"}, trust_env=False, timeout=30) as hc:
                async with Client(streamable_http_client(self.mcp + "/mcp", http_client=hc)) as client:
                    return await steps(client)
        return anyio.run(go)

    def call(self, name, **args):
        async def steps(client):
            return await client.call_tool(name, args)
        return self.run_mcp(steps)

    def card(self, card_ref, session_ref, key="k-relay-cards"):
        return http("GET", f"{self.mcp}/internal/cards/{card_ref}?session_ref={session_ref}", headers={"Authorization": f"Bearer {key}"})

    # ------------------------------------------------------------------ tests

    def test_rejects_unauthenticated_mcp(self):
        status, _ = http("POST", self.mcp + "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(status, 401)
        with self.assertRaises(Exception):
            self.run_mcp(lambda c: c.list_tools(), key="wrong")

    def test_lists_tools_with_annotations(self):
        tools = self.run_mcp(lambda c: c.list_tools()).tools
        names = {t.name for t in tools}
        self.assertTrue({"check_benefits", "find_providers", "prepare_appointment_request", "submit_appointment_request", "request_human_handoff"} <= names)
        submit = next(t for t in tools if t.name == "submit_appointment_request")
        self.assertTrue(submit.annotations.destructive_hint)
        self.assertIn("session_ref", submit.input_schema["required"])
        self.assertNotIn("member_ref", json.dumps([t.input_schema for t in tools]))

    def test_benefit_check_screen(self):
        sref = self.session()
        res = self.call("check_benefits", session_ref=sref, service_ref="svc_focused_skin_exam")
        self.assertFalse(res.is_error, res)
        out = res.structured_content
        self.assertEqual(out["benefits"][0]["in_network"]["copay"], 40.0)
        status, card = self.card(out["card_ref"], sref)
        self.assertEqual(status, 200)
        self.assertEqual(card["template_id"], "benefit-coverage@1")
        facts = {f["title"]: f["value"] for f in card["data"]["facts"]}
        self.assertEqual(facts["Visit cost"], "$40 specialist copay per visit")
        self.assertEqual(facts["Referral"], "PCP referral required before visit")
        # Cards are bound to the session and need the relay credential.
        self.assertEqual(self.card(out["card_ref"], self.session())[0], 404)
        self.assertEqual(self.card(out["card_ref"], sref, key="nope")[0], 401)

    def test_invalid_session_ref_is_a_tool_error(self):
        res = self.call("check_benefits", session_ref="ses_" + "0" * 32, service_ref="svc_focused_skin_exam")
        self.assertTrue(res.is_error)
        self.assertIn("invalid_grant", res.content[0].text)
        res = self.call("check_benefits", session_ref="mbr_2c91", service_ref="svc_focused_skin_exam")
        self.assertTrue(res.is_error)  # schema pattern rejects anything that is not a session ref

    def test_service_and_provider_search_screens(self):
        sref = self.session()
        res = self.call("search_services", session_ref=sref, query="changing mole")
        out = res.structured_content
        _, card = self.card(out["card_ref"], sref)
        self.assertEqual(card["template_id"], "service-options@1")
        self.assertEqual(card["data"]["zip"], "10013")
        self.assertEqual(card["data"]["selected"], "svc_focused_skin_exam")
        self.assertNotIn("svc_cosmetic_skin_screening", [s["ref"] for s in card["data"]["services"]])
        res = self.call("find_providers", session_ref=sref, service_ref="svc_focused_skin_exam")
        out = res.structured_content
        self.assertEqual([p["ref"] for p in out["providers"]], ["prv_19", "prv_42"])
        _, card = self.card(out["card_ref"], sref)
        self.assertEqual(card["data"]["audience"], "member")
        self.assertEqual(card["data"]["doctors"][0]["initials"], "NP")
        self.assertEqual(card["data"]["plan"], "Harbor HMO")

    def test_booking_requires_confirmation_in_card(self):
        sref = self.session()
        res = self.call("get_availability", session_ref=sref, provider_ref="prv_19", service_ref="svc_focused_skin_exam")
        slot = res.structured_content["slots"][0]["ref"]
        _, card = self.card(res.structured_content["card_ref"], sref)
        self.assertEqual(card["data"]["slots"][0]["label"], "Thu, Oct 15 · 10:30 AM")
        res = self.call("prepare_appointment_request", session_ref=sref, provider_ref="prv_19", slot_ref=slot, service_ref="svc_focused_skin_exam")
        self.assertFalse(res.is_error, res)
        action_id = res.structured_content["action_id"]
        _, card = self.card(res.structured_content["card_ref"], sref)
        self.assertEqual(card["data"]["actionId"], action_id)
        # The model calling submit straight away is refused.
        res = self.call("submit_appointment_request", session_ref=sref, action_id=action_id)
        self.assertTrue(res.is_error)
        self.assertIn("confirmation_required", res.content[0].text)
        # The relay confirms after the member pressed Confirm in the card.
        status, _ = http("POST", f"{self.broker}/v1/actions/{action_id}/confirm", {"session_ref": sref, "extras": {"note": "left shoulder"}}, {"Authorization": "Bearer k-relay"})
        self.assertEqual(status, 200)
        res = self.call("submit_appointment_request", session_ref=sref, action_id=action_id)
        self.assertFalse(res.is_error, res.content)
        self.assertEqual(res.structured_content["status"], "booked")
        _, card = self.card(res.structured_content["card_ref"], sref)
        self.assertEqual(card["template_id"], "confirmation@1")
        # One confirmation, one booking.
        self.assertTrue(self.call("submit_appointment_request", session_ref=sref, action_id=action_id).is_error)

    def test_provider_referral_flow(self):
        sref = self.session(sub="prv_pcp_01", role="provider", member_ref="mbr_7f3a", portal="provider")
        res = self.call("find_providers", session_ref=sref, service_ref="svc_focused_skin_exam")
        _, card = self.card(res.structured_content["card_ref"], sref)
        self.assertEqual(card["data"]["audience"], "provider")
        self.assertTrue(self.call("prepare_appointment_request", session_ref=sref, provider_ref="prv_19", slot_ref="slt_x", service_ref="svc_focused_skin_exam").is_error)
        res = self.call("prepare_referral", session_ref=sref, to_provider_ref="prv_42", service_ref="svc_focused_skin_exam")
        self.assertFalse(res.is_error, res.content)
        action_id = res.structured_content["action_id"]
        _, card = self.card(res.structured_content["card_ref"], sref)
        self.assertEqual(card["data"]["memberName"], "Alex Morgan")
        http("POST", f"{self.broker}/v1/actions/{action_id}/confirm", {"session_ref": sref, "extras": {"reason": "changing mole"}}, {"Authorization": "Bearer k-relay"})
        res = self.call("submit_referral", session_ref=sref, action_id=action_id)
        self.assertFalse(res.is_error, res.content)
        self.assertEqual(res.structured_content["status"], "submitted")

    def test_member_cannot_refer(self):
        sref = self.session()
        res = self.call("prepare_referral", session_ref=sref, to_provider_ref="prv_42", service_ref="svc_focused_skin_exam")
        self.assertTrue(res.is_error)

    def test_handoff_posts_signed_webhook_without_member_ids(self):
        sref = self.session(sub="mbr_2c91")
        res = self.call("request_human_handoff", session_ref=sref, reason="user_request", topic="Question about a bill")
        self.assertEqual(res.structured_content["ticket_ref"], "HO-1001")
        self.assertEqual(self.handoffs[-1]["session_ref"], sref)
        self.assertNotIn("mbr_2c91", json.dumps(self.handoffs[-1]))


if __name__ == "__main__":
    unittest.main()
