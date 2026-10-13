"""End-to-end over HTTP, exactly as the widget talks: portal BFF → broker → Direct Line → relay → Foundry stand-in
→ MCP → broker token exchange → core. Starts the six local processes on ports 9101-9105 and 9080.

    python -m unittest discover -s tests/e2e -v
"""

import http.cookiejar
import json
import pathlib
import sys
import time
import unittest
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from local_stack import running  # noqa: E402


class Browser:
    """Cookie-keeping HTTP client playing the widget in one browser."""

    def __init__(self, portal: str, directline: str):
        self.portal = portal
        self.dl = directline
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(self.jar))
        self.token = self.conv = None
        self.watermark = "0"

    def req(self, method, url, body=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        r = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers)
        try:
            with self.opener.open(r, timeout=30) as resp:
                raw = resp.read()
                is_json = "json" in (resp.headers.get("Content-Type") or "")
                return resp.status, json.loads(raw) if raw and is_json else None
        except urllib.error.HTTPError as exc:
            return exc.code, None

    def sign_in(self, user):
        self.req("GET", f"{self.portal}/?user={user}")
        status, tok = self.req("POST", f"{self.portal}/api/agent/directline-token", {"reason": "start"})
        assert status == 200, status
        self.token, self.user_id = tok["token"], tok["userId"]
        status, conv = self.req("POST", f"{self.dl}/v3/directline/conversations", token=self.token)
        assert status == 201, status
        self.conv = conv["conversationId"]
        return tok

    def post(self, activity):
        activity = {"from": {"id": "spoofed-user-id", "role": "user"}, **activity}
        status, body = self.req("POST", f"{self.dl}/v3/directline/conversations/{self.conv}/activities", activity, self.token)
        assert status == 200, status
        return body["id"]

    def say(self, text):
        return self.post({"type": "message", "text": text})

    def press(self, verb, **data):
        return self.post({"type": "message", "value": {"action": {"type": "Action.Execute", "verb": verb, "data": data}}})

    def event(self, name, value):
        return self.post({"type": "event", "name": name, "value": value})

    def until(self, predicate, timeout=30):
        """Poll new activities until one satisfies predicate; return all bot activities seen in this wait."""
        seen = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, body = self.req("GET", f"{self.dl}/v3/directline/conversations/{self.conv}/activities?watermark={self.watermark}", token=self.token)
            self.watermark = body["watermark"]
            bot = [a for a in body["activities"] if a.get("from", {}).get("role") == "bot"]
            seen += bot
            if any(predicate(a) for a in bot):
                return seen
            time.sleep(0.15)
        raise AssertionError(f"timed out; saw {[a.get('text') or a.get('name') or a.get('type') for a in seen]}")

    def card(self, template_id, timeout=30):
        seen = self.until(lambda a: a.get("channelData", {}).get("templateId") == template_id, timeout)
        return next(a for a in seen if a.get("channelData", {}).get("templateId") == template_id), seen


def card_action(card, verb):
    return next(a for a in card["attachments"][0]["content"]["actions"] if a.get("verb") == verb)


class LocalStackE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = running(base=9100, quiet=True)
        cls.urls = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def browser(self, user):
        b = Browser(self.urls["portal"], self.urls["relay"])
        b.sign_in(user)
        return b

    def test_member_benefit_check_to_booking(self):
        b = self.browser("alex")
        b.event("context", {"locale": "en-US", "member": {"ref": "mbr_2c91"}, "page": {"route": "/benefits"}})  # spoofed member ignored
        b.say("Is a skin check covered?")
        card, seen = b.card("benefit-coverage@1")
        self.assertEqual(seen[0]["type"], "typing")
        facts = {f["title"]: f["value"] for f in card["attachments"][0]["content"]["body"][3]["facts"]}
        self.assertEqual(facts["Visit cost"], "$40 specialist copay per visit")  # Alex's HMO, not Jordan's PPO
        lead = next(a for a in seen if a["type"] == "message" and a.get("text"))
        self.assertIn("covered", lead["text"])
        self.assertEqual(lead["channelData"]["resultChip"]["text"], "Plan eligibility and benefits reviewed")

        b.press("service.find", serviceRef="svc_focused_skin_exam", zip="10013", distance="5")
        card, _ = b.card("provider-results@1")
        content = card["attachments"][0]["content"]
        self.assertEqual([i["value"] for i in content["body"][2]["items"]], ["prv_19", "prv_42"])
        self.assertEqual([a["title"] for a in content["actions"]], ["Check availability", "View doctor"])

        b.press("provider.view", providerRef="prv_19")
        nav = b.until(lambda a: a["type"] == "event" and a["name"] == "navigate")
        self.assertEqual(next(a for a in nav if a["type"] == "event")["value"], {"route": "/providers/prv_19"})

        b.press("appointment.availability", providerRef="prv_19", serviceRef="svc_focused_skin_exam")
        card, _ = b.card("availability-slots@1")
        slot = card["attachments"][0]["content"]["body"][2]["items"][0]["value"]

        review_action = card_action(card, "appointment.review")
        b.press("appointment.review", **review_action["data"], slotRef=slot)
        card, _ = b.card("booking-review@1")
        confirm = card_action(card, "appointment.confirm")
        action_id = confirm["data"]["actionId"]
        self.assertTrue(action_id.startswith("act_"))

        b.press("appointment.confirm", **confirm["data"], officeNote="left shoulder")
        card, _ = b.card("confirmation@1")
        content = card["attachments"][0]["content"]
        self.assertEqual(content["body"][0]["text"], "Booked")

        b.press("appointment.confirm", **confirm["data"])
        again = b.until(lambda a: "already handled" in (a.get("text") or ""))
        self.assertTrue(again)

    def test_provider_referral(self):
        b = self.browser("raman")
        b.say("Find an in-network dermatologist for Alex")
        card, _ = b.card("provider-results@1")
        self.assertEqual([a["title"] for a in card["attachments"][0]["content"]["actions"]], ["Review referral", "View doctor"])
        b.press("referral.review", serviceRef="svc_focused_skin_exam", providerRef="prv_42")
        card, _ = b.card("referral-review@1")
        submit = card_action(card, "referral.submit")
        b.press("referral.submit", **submit["data"], attest="false")
        b.until(lambda a: "medical necessity" in (a.get("text") or ""))
        b.press("referral.submit", **submit["data"], attest="true", clinicalNote="changing mole, 3 months")
        card, _ = b.card("confirmation@1")
        self.assertEqual(card["attachments"][0]["content"]["body"][0]["text"], "Submitted")

    def test_member_cannot_use_provider_actions(self):
        b = self.browser("jordan")
        b.press("referral.review", serviceRef="svc_focused_skin_exam", providerRef="prv_42")
        seen = b.until(lambda a: a["type"] == "message" and a.get("text"))
        self.assertFalse(any(a.get("channelData", {}).get("templateId") == "referral-review@1" for a in seen))

    def test_handoff(self):
        b = self.browser("jordan")
        b.event("handoffRequest", {})
        seen = b.until(lambda a: a["type"] == "event" and a["name"] == "handoff")
        ev = next(a for a in seen if a["type"] == "event")
        self.assertTrue(ev["value"]["ticketRef"].startswith("HO-"))

    def test_direct_line_token_is_bound_to_its_conversation(self):
        a, b = self.browser("alex"), self.browser("jordan")
        status, _ = a.req("GET", f"{a.dl}/v3/directline/conversations/{b.conv}/activities", token=a.token)
        self.assertEqual(status, 403)
        status, _ = a.req("POST", f"{a.dl}/v3/directline/conversations/{b.conv}/activities", {"type": "message", "text": "hi"}, a.token)
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
