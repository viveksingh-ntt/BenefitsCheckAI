"""End-to-end over AG-UI, exactly as AgUiTransport talks: portal BFF → broker (/v1/agui/token) → relay host_agui (SSE)
→ Foundry stand-in → MCP → broker token exchange → core. Starts the local processes on ports 9201-9206 and 9181.

    python -m unittest tests.e2e.test_local_stack_agui -v
"""

import http.cookiejar
import json
import pathlib
import sys
import unittest
import urllib.error
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from local_stack_agui import running  # noqa: E402


class AgUiClient:
    """Cookie-keeping HTTP client playing the widget's AgUiTransport in one browser."""

    def __init__(self, portal: str, relay: str):
        self.portal, self.relay = portal, relay
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(self.jar))
        self.token = self.thread = None
        self.interrupts: list[dict] = []

    def req(self, method, url, body=None, token=None, accept="application/json"):
        headers = {"Content-Type": "application/json", "Accept": accept, "Origin": self.portal}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        r = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers)
        try:
            with self.opener.open(r, timeout=60) as resp:
                return resp.status, resp.headers, resp.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read().decode()

    def sign_in(self, user, body=None):
        self.req("GET", f"{self.portal}/?user={user}")
        status, _, raw = self.req("POST", f"{self.portal}/api/agent/agui-token", body or {"reason": "start"})
        assert status == 200, (status, raw)
        tok = json.loads(raw)
        self.token, self.thread = tok["token"], tok["threadId"]
        return tok

    def run(self, *, text=None, action=None, journey=None, resume=None, context=None, thread=None, token=None, auto_cancel=True):
        """POST one RunAgentInput; return (status, events). Open interrupts are cancelled unless answered, like the widget."""
        answered = {r["interruptId"] for r in resume or []}
        open_ = self.interrupts if auto_cancel else []
        resume = (resume or []) + [{"interruptId": i["id"], "status": "cancelled"} for i in open_ if i["id"] not in answered]
        body = {"threadId": thread or self.thread, "runId": f"run_{uuid.uuid4().hex[:12]}", "state": {}, "tools": [],
                "messages": [{"id": "m1", "role": "user", "content": text}] if text else [],
                "context": context or [], "forwardedProps": {**({"action": action} if action else {}), **({"journey": journey} if journey else {})}}
        if resume:
            body["resume"] = resume
        status, headers, raw = self.req("POST", f"{self.relay}/agui/run", body, token or self.token, accept="text/event-stream")
        if status != 200:
            return status, json.loads(raw or "{}")
        assert headers["Content-Type"].startswith("text/event-stream")
        events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]
        fin = events[-1]
        if fin["type"] == "RUN_FINISHED":
            self.interrupts = fin["outcome"].get("interrupts", []) if fin["outcome"]["type"] == "interrupt" else []
        return status, events

    def say(self, text, **kw):
        return self.run(text=text, **kw)[1]

    def press(self, verb, **data):
        return self.run(action={"verb": verb, "data": data})[1]


def text_of(events):
    return "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")


def card(events, template_id):
    snap = next(e for e in events if e["type"] == "ACTIVITY_SNAPSHOT" and e["activityType"] == "adaptive_card" and e["content"]["templateId"] == template_id)
    return snap["content"]["card"]


def card_action(c, verb):
    return next(a for a in c["actions"] if a.get("verb") == verb)


class LocalStackAgUiE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = running(base=9200, quiet=True)
        cls.urls = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def client(self, user):
        c = AgUiClient(self.urls["portal"], self.urls["relay"])
        c.sign_in(user)
        return c

    def test_member_benefit_check_to_booking_with_interrupt(self):
        c = self.client("alex")
        ev = c.say("Is a skin check covered?", context=[{"description": "page", "value": "/benefits"}, {"description": "member", "value": "mbr_2c91"}])
        types = [e["type"] for e in ev]
        self.assertEqual(types[0], "RUN_STARTED")
        self.assertIn("STEP_STARTED", types)
        facts = {f["title"]: f["value"] for f in card(ev, "benefit-coverage@1")["body"][3]["facts"]}
        self.assertEqual(facts["Visit cost"], "$40 specialist copay per visit")  # Alex's HMO; the spoofed context is ignored
        self.assertIn("covered", text_of(ev))
        chip = next(e for e in ev if e["type"] == "ACTIVITY_SNAPSHOT" and e["activityType"] == "result_chip")
        self.assertEqual(chip["content"]["text"], "Plan eligibility and benefits reviewed")

        ev = c.press("service.find", serviceRef="svc_focused_skin_exam", zip="10013", distance="5")
        results = card(ev, "provider-results@1")
        self.assertEqual([i["value"] for i in results["body"][2]["items"]], ["prv_19", "prv_42"])

        ev = c.press("provider.view", providerRef="prv_19")
        nav = next(e for e in ev if e["type"] == "CUSTOM" and e["name"] == "navigate")
        self.assertEqual(nav["value"], {"route": "/providers/prv_19"})

        ev = c.press("appointment.availability", providerRef="prv_19", serviceRef="svc_focused_skin_exam")
        slots = card(ev, "availability-slots@1")
        slot = slots["body"][2]["items"][0]["value"]

        ev = c.press("appointment.review", **card_action(slots, "appointment.review")["data"], slotRef=slot)
        review = card(ev, "booking-review@1")
        action_id = card_action(review, "appointment.confirm")["data"]["actionId"]
        fin = ev[-1]
        self.assertEqual(fin["outcome"]["type"], "interrupt")
        self.assertEqual(fin["outcome"]["interrupts"][0]["id"], action_id)

        # The run is paused: plain input without answering the interrupt is refused by the relay.
        status, ev = c.run(text="hello", auto_cancel=False)
        self.assertEqual((ev[-1]["type"], ev[-1]["code"]), ("RUN_ERROR", "interrupt_pending"))

        status, ev = c.run(resume=[{"interruptId": action_id, "status": "resolved", "payload": {"approved": True, "note": "left shoulder"}}])
        self.assertEqual(card(ev, "confirmation@1")["body"][0]["text"], "Booked")
        self.assertEqual(ev[-1]["outcome"], {"type": "success"})

        status, ev = c.run(resume=[{"interruptId": action_id, "status": "resolved", "payload": {"approved": True}}])
        self.assertEqual(ev[-1]["code"], "unknown_interrupt")  # replay is refused; the booking happened once

    def test_declining_the_review_books_nothing(self):
        c = self.client("jordan")
        c.press("appointment.availability", providerRef="prv_19", serviceRef="svc_focused_skin_exam")
        slots = card(c.press("appointment.availability", providerRef="prv_19", serviceRef="svc_focused_skin_exam"), "availability-slots@1")
        ev = c.press("appointment.review", **card_action(slots, "appointment.review")["data"], slotRef=slots["body"][2]["items"][0]["value"])
        action_id = ev[-1]["outcome"]["interrupts"][0]["id"]
        status, ev = c.run(resume=[{"interruptId": action_id, "status": "resolved", "payload": {"approved": False}}])
        self.assertIn("nothing was booked", text_of(ev))
        self.assertFalse(any(e.get("activityType") == "adaptive_card" for e in ev))

    def test_provider_referral_with_attestation(self):
        c = self.client("raman")
        results = card(c.say("Find an in-network dermatologist for Alex"), "provider-results@1")
        self.assertEqual([a["title"] for a in results["actions"]], ["Review referral", "View doctor"])
        ev = c.press("referral.review", serviceRef="svc_focused_skin_exam", providerRef="prv_42")
        card(ev, "referral-review@1")
        action_id = ev[-1]["outcome"]["interrupts"][0]["id"]
        status, ev = c.run(resume=[{"interruptId": action_id, "status": "resolved", "payload": {"approved": True, "attest": False}}])
        self.assertIn("medical necessity", text_of(ev))
        ev = c.press("referral.review", serviceRef="svc_focused_skin_exam", providerRef="prv_42")
        action_id = ev[-1]["outcome"]["interrupts"][0]["id"]
        status, ev = c.run(resume=[{"interruptId": action_id, "status": "resolved",
                                    "payload": {"approved": True, "attest": True, "note": "changing mole, 3 months"}}])
        self.assertEqual(card(ev, "confirmation@1")["body"][0]["text"], "Submitted")

    def test_member_cannot_use_provider_actions(self):
        c = self.client("jordan")
        ev = c.press("referral.review", serviceRef="svc_focused_skin_exam", providerRef="prv_42")
        self.assertFalse(any(e.get("activityType") == "adaptive_card" and e["content"]["templateId"] == "referral-review@1" for e in ev))
        self.assertEqual(ev[-1]["outcome"], {"type": "success"})

    def test_handoff_and_journey(self):
        c = self.client("jordan")
        ev = c.run(action={"verb": "handoff"})[1]
        handoff = next(e for e in ev if e["type"] == "CUSTOM" and e["name"] == "handoff")
        self.assertTrue(handoff["value"]["ticketRef"].startswith("HO-"))
        ev = c.run(journey={"id": "doctor-search", "params": {"serviceCode": "derm-skin-exam", "zip": "10013", "radiusMiles": 5}})[1]
        self.assertEqual(ev[-1]["type"], "RUN_FINISHED")
        self.assertTrue(text_of(ev))

    def test_chat_token_is_bound_to_its_thread_and_resumes(self):
        a, b = self.client("alex"), self.client("jordan")
        self.assertEqual(a.run(text="hi", thread=b.thread)[0], 403)
        self.assertEqual(a.req("GET", f"{a.relay}/agui/threads/{b.thread}", token=a.token)[0], 403)
        self.assertEqual(a.run(text="hi", token="not-a-token")[0], 401)
        a.say("Is a skin check covered?")
        # Page reload: the BFF resumes the same thread for the same user and the transcript comes back.
        tok = a.sign_in("alex", {"reason": "resume", "conversationId": a.thread})
        self.assertEqual(tok["threadId"], a.thread)
        status, _, raw = a.req("GET", f"{a.relay}/agui/threads/{a.thread}", token=a.token)
        snap = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertEqual([m["role"] for m in snap["messages"]][:2], ["user", "assistant"])
        # Another user cannot take over Alex's thread by naming it.
        other = b.sign_in("jordan", {"reason": "resume", "conversationId": a.thread})
        self.assertNotEqual(other["threadId"], a.thread)

    def test_cors_allows_only_the_portal(self):
        c = AgUiClient(self.urls["portal"], self.urls["relay"])
        r = urllib.request.Request(f"{c.relay}/agui/run", method="OPTIONS", headers={
            "Origin": "https://evil.example", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"})
        try:
            with c.opener.open(r, timeout=10) as resp:
                allowed = resp.headers.get("access-control-allow-origin")
        except urllib.error.HTTPError as exc:
            allowed = exc.headers.get("access-control-allow-origin")
        self.assertIsNone(allowed)


if __name__ == "__main__":
    unittest.main()
