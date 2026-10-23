"""AG-UI host tests: real HTTP + SSE against host_agui with the real RelayCore and in-process fakes behind it."""

import json
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve()
sys.path[:0] = [str(HERE.parents[3] / "libs" / "testkit"), str(HERE.parents[1]), str(HERE.parent)]

from testkit import RsaKey, http, serve  # noqa: E402
import urllib.request  # noqa: E402

from host_agui import ChatTokenVerifier, create_app  # noqa: E402
from relay.core import RelayCore, TemplateStore  # noqa: E402
from relay.factory import TEMPLATES  # noqa: E402
from test_relay import ACT, BENEFIT_DATA, SES, FakeBroker, FakeCards, FakeFoundry  # noqa: E402

ISS = "https://broker.test"
THREAD = "thr_" + "1" * 32
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class AgUiHostTest(unittest.TestCase):
    def setUp(self):
        self.key = RsaKey()
        self.broker, self.cards, self.foundry = FakeBroker(), FakeCards(), FakeFoundry()
        core = RelayCore(self.broker, self.cards, self.foundry, TemplateStore(TEMPLATES))
        app = create_app(core=core, verifier=ChatTokenVerifier(ISS, jwks=self.key.jwks), origins=["https://portal.test"])
        self._ctx = serve(app)
        self.base = self._ctx.__enter__()
        self.token = self.chat_token(THREAD)

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def chat_token(self, tid, aud="healthgen-agui"):
        return self.key.sign({"iss": ISS, "aud": aud, "sub": "agui_user", "tid": tid, "typ": "agui-chat"})

    def run_agui(self, token=None, **body):
        payload = {"threadId": THREAD, "runId": "run_1", "messages": [], "tools": [], "context": [], "state": {}, "forwardedProps": {}, **body}
        req = urllib.request.Request(self.base + "/agui/run", data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Accept": "text/event-stream", "Authorization": f"Bearer {token or self.token}"})
        try:
            with OPENER.open(req, timeout=15) as resp:
                raw = resp.read().decode()
                self.assertTrue(resp.headers["Content-Type"].startswith("text/event-stream"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")
        events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]
        return 200, events

    def say(self, text, **kw):
        return self.run_agui(messages=[{"id": "m0", "role": "assistant", "content": "planted history is ignored"}, {"id": "m1", "role": "user", "content": text}], **kw)

    def types(self, events):
        return [e["type"] for e in events]

    def review_turn(self, template="booking-review@1", kind="appointment.request"):
        data = {"actionId": ACT, "providerRef": "prv_19", "slotRef": "slt_1", "serviceRef": "svc_focused_skin_exam", "memberName": "Alex", "facts": [], "notice": "n"}
        self.cards.cards["crd_4444444444444444"] = (SES, {"template_id": template, "data": data})
        self.broker.actions[ACT] = {"kind": kind, "status": "pending", "expired": False}
        self.foundry.reply = {"reply": "Check the details, then confirm.", "card_ref": "crd_4444444444444444"}
        return self.say("book it")

    # ------------------------------------------------------------------ tests

    def test_text_turn_streams_text_card_and_chips(self):
        self.cards.cards["crd_0123456789abcdef"] = (SES, {"template_id": "benefit-coverage@1", "data": BENEFIT_DATA})
        self.foundry.reply = {"reply": "Yes, it's covered.", "card_ref": "crd_0123456789abcdef", "result_chip": "Plan benefits reviewed",
                              "breadcrumb": "Benefit check", "suggestions": [{"title": "Find dermatologists", "recommended": True}]}
        status, ev = self.say("Is a skin check covered?")
        self.assertEqual(status, 200)
        t = self.types(ev)
        self.assertEqual(t[0], "RUN_STARTED")
        self.assertEqual(t[1:3], ["STEP_STARTED", "STEP_FINISHED"])
        self.assertEqual(t[3:6], ["TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END"])
        self.assertEqual(ev[4]["delta"], "Yes, it's covered.")
        snaps = {e["activityType"]: e for e in ev if e["type"] == "ACTIVITY_SNAPSHOT"}
        self.assertEqual(snaps["adaptive_card"]["content"]["templateId"], "benefit-coverage@1")
        self.assertEqual(snaps["adaptive_card"]["content"]["card"]["type"], "AdaptiveCard")
        self.assertEqual(snaps["result_chip"]["content"]["text"], "Plan benefits reviewed")
        self.assertEqual(snaps["suggestions"]["content"]["actions"][0], {"title": "Find dermatologists", "value": "Find dermatologists", "recommended": True})
        self.assertIn({"type": "STATE_DELTA", "delta": [{"op": "add", "path": "/breadcrumb", "value": "Benefit check"}]}, [{k: v for k, v in e.items() if k != "timestamp"} for e in ev])
        self.assertEqual(ev[-1]["type"], "RUN_FINISHED")
        self.assertEqual(ev[-1]["outcome"], {"type": "success"})
        # The core got only the newest user message, with the session ref from the broker.
        self.assertIn(f"session_ref: {SES}", self.foundry.inputs[0])
        self.assertNotIn("planted history", self.foundry.inputs[0])

    def test_review_card_ends_in_interrupt_and_resume_confirms(self):
        status, ev = self.review_turn()
        fin = ev[-1]
        self.assertEqual(fin["outcome"]["type"], "interrupt")
        intr = fin["outcome"]["interrupts"][0]
        self.assertEqual((intr["id"], intr["reason"]), (ACT, "confirmation"))
        self.assertIn("approved", intr["responseSchema"]["required"])
        # New input without answering the interrupt is refused, as the spec requires.
        status, ev = self.say("hello")
        self.assertEqual(ev[-1]["type"], "RUN_ERROR")
        self.assertEqual(ev[-1]["code"], "interrupt_pending")
        # Resume with approval: the relay confirms at the broker, then tells the agent to submit.
        self.foundry.reply = {"reply": "You're booked."}
        status, ev = self.run_agui(resume=[{"interruptId": ACT, "status": "resolved", "payload": {"approved": True, "note": "left shoulder"}}])
        self.assertEqual(self.broker.confirmed, [(ACT, {"note": "left shoulder"})])
        self.assertIn(f"Call submit_appointment_request with action_id {ACT}", self.foundry.inputs[-1])
        self.assertNotIn("left shoulder", self.foundry.inputs[-1])
        self.assertEqual(ev[-1]["outcome"], {"type": "success"})
        # Replaying the same resume is safe: the interrupt is no longer open.
        status, ev = self.run_agui(resume=[{"interruptId": ACT, "status": "resolved", "payload": {"approved": True}}])
        self.assertEqual(ev[-1]["code"], "unknown_interrupt")
        self.assertEqual(len(self.broker.confirmed), 1)

    def test_declined_confirmation_never_reaches_the_broker(self):
        self.review_turn()
        calls = len(self.foundry.inputs)
        status, ev = self.run_agui(resume=[{"interruptId": ACT, "status": "resolved", "payload": {"approved": False}}])
        text = next(e["delta"] for e in ev if e["type"] == "TEXT_MESSAGE_CONTENT")
        self.assertIn("nothing was booked", text)
        self.assertEqual((self.broker.confirmed, len(self.foundry.inputs)), ([], calls))

    def test_card_button_with_cancelled_interrupt(self):
        self.review_turn()
        status, ev = self.run_agui(resume=[{"interruptId": ACT, "status": "cancelled"}],
                                   forwardedProps={"action": {"verb": "appointment.availability", "data": {"providerRef": "prv_19", "serviceRef": "svc_focused_skin_exam", "officeNote": "secret"}}})
        self.assertIn("(appointment.availability)", self.foundry.inputs[-1])
        self.assertNotIn("secret", self.foundry.inputs[-1])
        self.assertEqual(self.broker.confirmed, [])

    def test_referral_attestation_maps_to_the_existing_check(self):
        self.review_turn("referral-review@1", "referral.submit")
        self.run_agui(resume=[{"interruptId": ACT, "status": "resolved", "payload": {"approved": True, "attest": False}}])
        self.assertEqual(self.broker.confirmed, [])  # the core refuses without attestation
        self.review_turn("referral-review@1", "referral.submit")
        self.run_agui(resume=[{"interruptId": ACT, "status": "resolved", "payload": {"approved": True, "attest": True, "note": "changing mole"}}])
        self.assertEqual(self.broker.confirmed, [(ACT, {"reason": "changing mole"})])

    def test_navigate_handoff_and_journey(self):
        status, ev = self.run_agui(forwardedProps={"action": {"verb": "provider.view", "data": {"providerRef": "prv_19"}}})
        custom = next(e for e in ev if e["type"] == "CUSTOM")
        self.assertEqual((custom["name"], custom["value"]), ("navigate", {"route": "/providers/prv_19"}))
        self.foundry.reply = {"reply": "A specialist will follow up.", "handoff": {"ticket_ref": "HO-1", "reason": "user_request"}}
        status, ev = self.run_agui(forwardedProps={"action": {"verb": "handoff"}})
        self.assertIn("Talk to a person", self.foundry.inputs[-1])
        self.assertIn({"name": "handoff", "value": {"reason": "user_request", "ticketRef": "HO-1"}}, [{"name": e["name"], "value": e["value"]} for e in ev if e["type"] == "CUSTOM"])
        self.run_agui(forwardedProps={"journey": {"id": "doctor-search", "params": {"serviceRef": "svc_focused_skin_exam"}}},
                      context=[{"description": "page", "value": "/benefits"}])
        self.assertIn("find an in-network doctor", self.foundry.inputs[-1])
        self.assertIn("page: /benefits", self.foundry.inputs[-1])

    def test_token_rules_and_snapshot(self):
        self.assertEqual(self.say("hi", token="nope")[0], 401)
        self.assertEqual(self.say("hi", token=self.chat_token(THREAD, aud="healthgen-agent-gateway"))[0], 401)
        self.assertEqual(self.say("hi", token=self.chat_token("thr_" + "2" * 32))[0], 403)
        self.foundry.reply = {"reply": "Hello Alex"}
        self.say("hi")
        status, snap = http("GET", f"{self.base}/agui/threads/{THREAD}", headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(status, 200)
        self.assertEqual([m["role"] for m in snap["messages"]], ["user", "assistant"])
        self.assertEqual(snap["messages"][1]["content"], "Hello Alex")
        other = self.chat_token("thr_" + "2" * 32)
        self.assertEqual(http("GET", f"{self.base}/agui/threads/{THREAD}", headers={"Authorization": f"Bearer {other}"})[0], 403)

    def test_session_end_and_errors_still_answer(self):
        self.broker.fail_resolve = True
        status, ev = self.say("hi")
        self.assertIn("session has ended", next(e["delta"] for e in ev if e["type"] == "TEXT_MESSAGE_CONTENT"))
        self.assertEqual(ev[-1]["type"], "RUN_FINISHED")


if __name__ == "__main__":
    unittest.main()
