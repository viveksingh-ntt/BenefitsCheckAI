import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve()
sys.path[:0] = [str(HERE.parents[3] / "libs" / "testkit"), str(HERE.parents[1])]

import jwt  # noqa: E402
from testkit import RsaKey, http, serve  # noqa: E402

from app.auth import JwtVerifier, PortalAssertionVerifier, ServiceAuthenticator  # noqa: E402
from app.main import Settings  # noqa: E402
from app.main_agui import create_app  # noqa: E402
from app.signer import LocalRsaSigner  # noqa: E402

ISS = "https://broker.test"
PORTAL_ISS = "https://portal.test"


class AgUiTokenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.portal_key = RsaKey()
        cls.signer = LocalRsaSigner()
        app = create_app(
            settings=Settings(issuer=ISS),
            signer=cls.signer,
            portal=PortalAssertionVerifier(JwtVerifier([PORTAL_ISS], [PortalAssertionVerifier.AUDIENCE], jwks=cls.portal_key.jwks)),
            services=ServiceAuthenticator("keys", keys={"agent-relay": "k-relay", "mcp-healthgen": "k-mcp"}),
        )  # no DIRECTLINE_SECRET: AG-UI only
        cls._ctx = serve(app)
        cls.base = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def assertion(self, sub="mbr_7f3a", role="member", **extra):
        return {"Authorization": "Bearer " + self.portal_key.sign(
            {"iss": PORTAL_ISS, "aud": PortalAssertionVerifier.AUDIENCE, "sub": sub, "role": role, "idm_session": f"idm-{sub}", **extra}, ttl=120)}

    def token(self, body=None, **kw):
        return http("POST", self.base + "/v1/agui/token", body or {"reason": "start"}, self.assertion(**kw))

    def claims(self, token):
        return jwt.decode(token, jwt.PyJWK(self.signer.jwks()["keys"][0]).key, algorithms=["RS256"], audience="healthgen-agui", issuer=ISS)

    def test_start_issues_thread_bound_chat_token(self):
        status, body = self.token()
        self.assertEqual(status, 200, body)
        self.assertTrue(body["threadId"].startswith("thr_"))
        self.assertEqual(body["conversationId"], body["threadId"])  # same shape as the Direct Line token response
        self.assertTrue(body["userId"].startswith("agui_"))
        c = self.claims(body["token"])
        self.assertEqual((c["sub"], c["tid"], c["typ"]), (body["userId"], body["threadId"], "agui-chat"))
        self.assertNotIn("mbr_7f3a", str(c))
        self.assertNotIn("sid", c)

    def test_session_resolves_like_direct_line(self):
        _, body = self.token()
        status, ses = http("POST", self.base + "/v1/sessions/resolve", {"dl_user_id": body["userId"], "conversation_id": body["threadId"]}, {"Authorization": "Bearer k-relay"})
        self.assertEqual(status, 200, ses)
        self.assertTrue(ses["session_ref"].startswith("ses_"))
        status, _ = http("POST", self.base + "/v1/sessions/resolve", {"dl_user_id": body["userId"], "conversation_id": "thr_other"}, {"Authorization": "Bearer k-relay"})
        self.assertEqual(status, 403)

    def test_resume_same_member_keeps_thread_other_member_gets_new(self):
        _, first = self.token()
        _, again = self.token({"reason": "resume", "conversationId": first["threadId"]})
        self.assertEqual((again["threadId"], again["userId"]), (first["threadId"], first["userId"]))
        _, other = self.token({"reason": "resume", "conversationId": first["threadId"]}, sub="mbr_2c91")
        self.assertNotEqual(other["threadId"], first["threadId"])

    def test_logout_ends_resume(self):
        _, first = self.token(sub="mbr_2c91", idm_session="idm-out")
        http("POST", self.base + "/v1/directline/logout", {}, self.assertion(sub="mbr_2c91", idm_session="idm-out"))
        _, again = self.token({"reason": "refresh", "conversationId": first["threadId"]}, sub="mbr_2c91")
        self.assertNotEqual(again["threadId"], first["threadId"])

    def test_rejects_missing_assertion_and_direct_line_is_off(self):
        self.assertEqual(http("POST", self.base + "/v1/agui/token", {})[0], 401)
        status, body = http("POST", self.base + "/v1/directline/token", {}, self.assertion())
        self.assertIn(status, (502, 503))
        self.assertEqual(body["error"], "directline_unavailable")


if __name__ == "__main__":
    unittest.main()
