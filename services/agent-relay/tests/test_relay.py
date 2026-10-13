import json
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve()
sys.path[:0] = [str(HERE.parents[1])]

import anyio  # noqa: E402

from relay.clients import AgentTurn, Session, UpstreamError  # noqa: E402
from relay.core import RelayCore, TemplateStore  # noqa: E402
from relay.envelope import mask_outbound, parse_envelope  # noqa: E402
from relay.factory import TEMPLATES  # noqa: E402
from relay.templating import expand_template  # noqa: E402

SES = "ses_" + "a" * 32
ACT = "act_" + "b" * 32


class FakeBroker:
    def __init__(self):
        self.actions = {}
        self.confirmed = []
        self.fail_resolve = False

    async def resolve(self, dl_user_id, conversation_id):
        if self.fail_resolve:
            raise UpstreamError(401, "session_inactive")
        return Session(SES, "member", "member", "Alex", "uctx", 1e12)

    async def get_action(self, action_id, session_ref):
        if action_id not in self.actions or session_ref != SES:
            raise UpstreamError(404, "not_found")
        return self.actions[action_id]

    async def confirm_action(self, action_id, session_ref, extras):
        self.confirmed.append((action_id, extras))
        self.actions[action_id]["status"] = "confirmed"
        return {"status": "confirmed"}


class FakeCards:
    def __init__(self):
        self.cards = {}

    async def get(self, card_ref, session_ref):
        c = self.cards.get(card_ref)
        return c[1] if c and c[0] == session_ref else None


class FakeFoundry:
    def __init__(self):
        self.inputs = []
        self.reply = {"reply": "Hello"}
        self.raw_output = []
        self.error = None
        self.conversations = 0

    async def create_conversation(self, user_context, metadata=None):
        self.conversations += 1
        return f"conv_{self.conversations}"

    async def run(self, conversation_id, text, user_context):
        if self.error:
            raise self.error
        self.inputs.append(text)
        body = self.reply if isinstance(self.reply, str) else json.dumps(self.reply)
        return AgentTurn(body, "resp_1", self.raw_output)


BENEFIT_DATA = {
    "service": {"name": "Focused skin exam", "category": "Dermatology", "ref": "svc_focused_skin_exam"},
    "plan": {"name": "Harbor HMO", "year": "2026", "ref": "pln_harbor_hmo_2026"},
    "coverage": {"label": "Covered when medically necessary"},
    "facts": [{"title": "Visit cost", "value": "$40 specialist copay per visit"}],
    "notice": "Estimate.",
}


class RelayTest(unittest.TestCase):
    def setUp(self):
        self.broker, self.cards, self.foundry = FakeBroker(), FakeCards(), FakeFoundry()
        self.core = RelayCore(self.broker, self.cards, self.foundry, TemplateStore(TEMPLATES))
        self.sent = []

    def turn(self, **activity):
        base = {"type": "message", "id": "in1", "from": {"id": "dl_user"}, "conversation": {"id": "conv-dl-1"}}
        base.update(activity)

        async def send(a):
            self.sent.append(a)

        anyio.run(self.core.on_activity, base, send)
        return self.sent

    def messages(self):
        return [a for a in self.sent if a["type"] == "message"]

    def test_text_turn_with_card_and_follow_up(self):
        self.cards.cards["crd_0123456789abcdef"] = (SES, {"template_id": "benefit-coverage@1", "data": BENEFIT_DATA})
        self.foundry.reply = {"reply": "Yes, it's covered.", "card_ref": "crd_0123456789abcdef", "follow_up": "Want to find a doctor?",
                              "result_chip": "Plan benefits reviewed", "suggestions": [{"title": "Find dermatologists", "recommended": True}, "Check referral rules"]}
        self.turn(text="Is a skin check covered?")
        self.assertEqual(self.sent[0]["type"], "typing")
        self.assertEqual(self.sent[0]["entities"][0]["streamType"], "informative")
        lead, card, follow = self.messages()
        self.assertEqual(lead["text"], "Yes, it's covered.")
        self.assertEqual(lead["channelData"]["resultChip"]["text"], "Plan benefits reviewed")
        self.assertNotIn("suggestedActions", lead)
        content = card["attachments"][0]["content"]
        self.assertEqual(content["type"], "AdaptiveCard")
        self.assertEqual(content["body"][0]["text"], "Focused skin exam")
        self.assertEqual(card["channelData"]["templateId"], "benefit-coverage@1")
        self.assertEqual(follow["suggestedActions"]["actions"][0], {"type": "imBack", "title": "Find dermatologists", "value": "Find dermatologists", "channelData": {"recommended": True}})
        # The agent got the session ref in the turn context, not member identity.
        self.assertIn(f"session_ref: {SES}", self.foundry.inputs[0])
        self.assertIn("Is a skin check covered?", self.foundry.inputs[0])

    def test_conversation_is_reused(self):
        self.turn(text="hi")
        self.turn(text="again")
        self.assertEqual(self.foundry.conversations, 1)

    def test_card_from_other_session_or_unknown_template_is_dropped(self):
        self.cards.cards["crd_1111111111111111"] = ("ses_other", {"template_id": "benefit-coverage@1", "data": {}})
        self.cards.cards["crd_2222222222222222"] = (SES, {"template_id": "evil@1", "data": {}})
        self.foundry.reply = {"reply": "x", "card_ref": "crd_1111111111111111"}
        self.turn(text="a")
        self.foundry.reply = {"reply": "y", "card_ref": "crd_2222222222222222"}
        self.turn(text="b")
        self.assertFalse(any("attachments" in m for m in self.messages()))

    def test_card_ref_fallback_from_mcp_output(self):
        self.cards.cards["crd_3333333333333333"] = (SES, {"template_id": "benefit-coverage@1", "data": BENEFIT_DATA})
        self.foundry.reply = {"reply": "Here you go"}
        self.foundry.raw_output = [{"type": "mcp_call", "name": "check_benefits", "output": json.dumps({"card_ref": "crd_3333333333333333"})}]
        self.turn(text="benefits")
        self.assertTrue(any("attachments" in m for m in self.messages()))

    def test_card_action_forwards_only_validated_refs(self):
        self.turn(value={"action": {"verb": "providers.search", "data": {"serviceRef": "svc_focused_skin_exam", "zip": "10013", "distance": "5",
                                                                         "officeNote": "my SSN is 123-45-6789", "serviceRef2": "x", "providerRef": "prv_19; DROP"}}})
        text = self.foundry.inputs[0]
        self.assertIn("service_ref=svc_focused_skin_exam, zip=10013, radius_miles=5", text)
        self.assertNotIn("SSN", text)
        self.assertNotIn("prv_19", text)
        self.assertEqual(self.sent[0]["text"], "Searching in-network doctors…")

    def test_navigation_verbs_do_not_call_the_agent(self):
        self.turn(value={"action": {"verb": "provider.view", "data": {"providerRef": "prv_19"}}})
        self.assertEqual(self.foundry.inputs, [])
        nav = next(a for a in self.sent if a["type"] == "event")
        self.assertEqual((nav["name"], nav["value"]), ("navigate", {"route": "/providers/prv_19"}))

    def test_unknown_verb(self):
        self.turn(value={"action": {"verb": "admin.deleteAll", "data": {}}})
        self.assertEqual(self.foundry.inputs, [])
        self.assertIn("isn't available", self.messages()[0]["text"])

    def test_confirm_unlocks_write_via_broker(self):
        self.broker.actions[ACT] = {"kind": "appointment.request", "status": "pending", "expired": False}
        self.turn(value={"action": {"verb": "appointment.confirm", "data": {"actionId": ACT, "providerRef": "prv_19", "officeNote": "left shoulder"}}})
        self.assertEqual(self.broker.confirmed, [(ACT, {"note": "left shoulder"})])
        self.assertIn(f"Call submit_appointment_request with action_id {ACT}", self.foundry.inputs[0])
        self.assertNotIn("left shoulder", self.foundry.inputs[0])
        # A second press does nothing.
        self.sent.clear()
        self.turn(value={"action": {"verb": "appointment.confirm", "data": {"actionId": ACT}}})
        self.assertEqual(len(self.foundry.inputs), 1)
        self.assertIn("already handled", self.messages()[0]["text"])

    def test_confirm_rejects_wrong_kind_bad_id_and_missing_attestation(self):
        self.broker.actions[ACT] = {"kind": "referral.submit", "status": "pending", "expired": False}
        self.turn(value={"action": {"verb": "appointment.confirm", "data": {"actionId": ACT}}})
        self.turn(value={"action": {"verb": "appointment.confirm", "data": {"actionId": "act_nothex"}}})
        self.turn(value={"action": {"verb": "referral.submit", "data": {"actionId": ACT, "attest": "false"}}})
        self.assertEqual(self.broker.confirmed, [])
        self.assertEqual(self.foundry.inputs, [])
        self.turn(value={"action": {"verb": "referral.submit", "data": {"actionId": ACT, "attest": "true", "clinicalNote": "changing mole"}}})
        self.assertEqual(self.broker.confirmed, [(ACT, {"reason": "changing mole"})])

    def test_context_event_sets_page_but_ignores_client_identity(self):
        self.turn(type="event", name="context", value={"locale": "es-US", "member": {"ref": "mbr_2c91"}, "page": {"route": "/benefits/dermatology"}})
        self.assertEqual(self.foundry.inputs, [])
        self.turn(text="hola")
        self.assertIn("page: /benefits/dermatology", self.foundry.inputs[0])
        self.assertIn("locale: es-US", self.foundry.inputs[0])
        self.assertNotIn("mbr_2c91", self.foundry.inputs[0])

    def test_start_journey_and_handoff_events(self):
        self.turn(type="event", name="startJourney", value={"journeyId": "doctor-search", "params": {"serviceRef": "svc_focused_skin_exam", "zip": "10013"}})
        self.assertIn("find an in-network doctor", self.foundry.inputs[0])
        self.assertIn("service_ref=svc_focused_skin_exam", self.foundry.inputs[0])
        self.foundry.reply = {"reply": "A specialist will follow up.", "handoff": {"ticket_ref": "HO-1001", "reason": "user_request"}}
        self.turn(type="event", name="handoffRequest", value={})
        ev = [a for a in self.sent if a["type"] == "event"][-1]
        self.assertEqual(ev["value"], {"reason": "user_request", "ticketRef": "HO-1001"})

    def test_plain_text_and_masking(self):
        self.foundry.reply = f"Your SSN 123-45-6789 and id 123456789012 for {SES}"
        self.turn(text="x")
        text = self.messages()[0]["text"]
        self.assertNotIn("123-45-6789", text)
        self.assertIn("***-**-6789", text)
        self.assertIn("••••9012", text)
        self.assertNotIn(SES, text)

    def test_guardrail_and_errors(self):
        self.foundry.error = UpstreamError(403, "content_filter")
        self.turn(text="bad")
        self.assertIn("can't help with that", self.messages()[-1]["text"])
        self.foundry.error = UpstreamError(500, "boom")
        self.turn(text="x")
        self.assertIn("something went wrong", self.messages()[-1]["text"])

    def test_session_ended(self):
        self.broker.fail_resolve = True
        self.turn(text="x")
        self.assertIn("session has ended", self.messages()[0]["text"])
        self.assertEqual(self.foundry.inputs, [])

    def test_rate_limit(self):
        self.core.config.max_turns_per_minute = 2
        for _ in range(3):
            self.turn(text="x")
        self.assertEqual(len(self.foundry.inputs), 2)
        self.assertIn("quickly", self.messages()[-1]["text"])


class EnvelopeAndTemplateTest(unittest.TestCase):
    def test_envelope_parsing(self):
        env, ok = parse_envelope('```json\n{"reply": "hi", "card_ref": "", "suggestions": ["A"]}\n```')
        self.assertTrue(ok)
        self.assertIsNone(env.card_ref)
        self.assertEqual(env.suggestions[0].title, "A")
        env, ok = parse_envelope('{"reply": "hi", "card_ref": "not-a-ref"}')
        self.assertFalse(ok)
        self.assertEqual(env.reply, "hi")
        env, ok = parse_envelope("just text")
        self.assertEqual((env.reply, ok), ("just text", False))

    def test_mask(self):
        self.assertEqual(mask_outbound("act_0123456789abcdef0123456789abcdef"), "[ref]")

    def test_provider_template_audience(self):
        t = TemplateStore(TEMPLATES).templates["provider-results@1"]
        data = {"title": "T", "doctors": [{"ref": "prv_19", "name": "Dr. Nina Patel"}], "plan": "Harbor HMO", "radius": 5, "zip": "10013",
                "selected": "prv_19", "serviceRef": "svc_focused_skin_exam", "notice": "n"}
        member = expand_template(t, {**data, "audience": "member"})
        provider = expand_template(t, {**data, "audience": "provider"})
        self.assertEqual([a["title"] for a in member["actions"]], ["Check availability", "View doctor"])
        self.assertEqual([a["title"] for a in provider["actions"]], ["Review referral", "View doctor"])
        self.assertEqual(member["body"][1]["text"], "1 matches · Harbor HMO · Within 5 miles of 10013")
        self.assertEqual(member["body"][2]["items"][0]["value"], "prv_19")

    def test_review_template_carries_action_id(self):
        t = TemplateStore(TEMPLATES).templates["booking-review@1"]
        card = expand_template(t, {"actionId": ACT, "providerRef": "prv_19", "slotRef": "slt_1", "facts": [], "notice": ""})
        self.assertEqual(card["actions"][0]["data"]["actionId"], ACT)


if __name__ == "__main__":
    unittest.main()
