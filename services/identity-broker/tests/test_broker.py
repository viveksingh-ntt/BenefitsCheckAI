import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve()
sys.path[:0] = [str(HERE.parents[3] / "libs" / "testkit"), str(HERE.parents[1])]

import jwt  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from testkit import RsaKey, http, serve  # noqa: E402

from app.auth import JwtVerifier, PortalAssertionVerifier, ServiceAuthenticator  # noqa: E402
from app.directline import DirectLineClient  # noqa: E402
from app.main import Settings, create_app, params_sha256  # noqa: E402
from app.signer import KeyVaultSigner, LocalRsaSigner  # noqa: E402

ISS = "https://broker.test"
PORTAL_ISS = "https://member-portal.test"
SECRET = "dl-secret"


def fake_directline():
    convs = {}

    async def generate(request: Request):
        if request.headers.get("authorization") != f"Bearer {SECRET}":
            return JSONResponse({}, status_code=403)
        body = await request.json()
        cid = f"conv{len(convs) + 1}"
        convs[cid] = body
        return JSONResponse({"conversationId": cid, "token": f"tok-{cid}-{body['user']['id']}", "expires_in": 3600})

    async def reconnect(request: Request):
        cid = request.path_params["cid"]
        if cid not in convs:
            return JSONResponse({}, status_code=404)
        return JSONResponse({"conversationId": cid, "token": f"tok2-{cid}", "expires_in": 3600, "streamUrl": f"wss://dl/{cid}"})

    app = Starlette(routes=[Route("/v3/directline/tokens/generate", generate, methods=["POST"]),
                            Route("/v3/directline/conversations/{cid}", reconnect)])
    app.state.convs = convs
    return app


class BrokerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.portal_key = RsaKey()
        cls.signer = LocalRsaSigner()
        cls.dl_app = fake_directline()
        cls._dl = serve(cls.dl_app)
        dl_base = cls._dl.__enter__()
        app = create_app(
            settings=Settings(issuer=ISS, trusted_origins=["https://portal.test"]),
            signer=cls.signer,
            directline=DirectLineClient(SECRET, dl_base),
            portal=PortalAssertionVerifier(JwtVerifier([PORTAL_ISS], [PortalAssertionVerifier.AUDIENCE], jwks=cls.portal_key.jwks)),
            services=ServiceAuthenticator("keys", keys={"agent-relay": "k-relay", "mcp-healthgen": "k-mcp", "apim": "k-apim"}),
        )
        cls._ctx = serve(app)
        cls.base = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)
        cls._dl.__exit__(None, None, None)

    # helpers
    def assertion(self, sub="mbr_7f3a", role="member", ttl=120, **extra):
        return {"Authorization": "Bearer " + self.portal_key.sign(
            {"iss": PORTAL_ISS, "aud": PortalAssertionVerifier.AUDIENCE, "sub": sub, "role": role, "idm_session": f"idm-{sub}", **extra}, ttl=ttl)}

    def svc(self, name):
        return {"Authorization": "Bearer " + {"relay": "k-relay", "mcp": "k-mcp", "apim": "k-apim"}[name]}

    def start(self, **kw):
        status, tok = http("POST", self.base + "/v1/directline/token", {"reason": "start"}, self.assertion(**kw))
        self.assertEqual(status, 200, tok)
        status, ses = http("POST", self.base + "/v1/sessions/resolve", {"dl_user_id": tok["userId"], "conversation_id": tok["conversationId"]}, self.svc("relay"))
        self.assertEqual(status, 200, ses)
        return tok, ses

    def exchange(self, session_ref, **extra):
        form = {"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange", "subject_token": session_ref,
                "subject_token_type": "urn:healthgen:params:oauth:token-type:session-ref", "audience": "healthgen-core", **extra}
        return http("POST", self.base + "/oauth2/token", form, self.svc("mcp"), form=True)

    def decode(self, token, aud):
        key = jwt.PyJWK(self.signer.jwks()["keys"][0]).key
        return jwt.decode(token, key, algorithms=["RS256"], audience=aud, issuer=ISS)

    # tests
    def test_jwks_and_discovery(self):
        status, body = http("GET", self.base + "/.well-known/jwks.json")
        self.assertEqual(body["keys"][0]["kid"], self.signer.kid)
        status, body = http("GET", self.base + "/.well-known/openid-configuration")
        self.assertEqual(body["issuer"], ISS)

    def test_directline_token_binds_dl_user_and_trusted_origins(self):
        tok, ses = self.start()
        self.assertTrue(tok["userId"].startswith("dl_"))
        sent = self.dl_app.state.convs[tok["conversationId"]]
        self.assertEqual(sent["trustedOrigins"], ["https://portal.test"])
        self.assertTrue(ses["session_ref"].startswith("ses_"))
        self.assertNotIn("member_ref", ses)  # relay never learns member ids
        claims = self.decode(ses["user_context_token"], "healthgen-agent-gateway")
        self.assertEqual((claims["sid"], claims["role"]), (ses["session_ref"], "member"))

    def test_rejects_bad_assertions(self):
        url = self.base + "/v1/directline/token"
        self.assertEqual(http("POST", url, {})[0], 401)
        self.assertEqual(http("POST", url, {}, self.assertion(ttl=3600))[0], 401)  # too long-lived
        self.assertEqual(http("POST", url, {}, self.assertion(member_ref="mbr_2c91"))[0], 403)  # member acting for another
        other = RsaKey()
        bad = {"Authorization": "Bearer " + other.sign({"iss": PORTAL_ISS, "aud": PortalAssertionVerifier.AUDIENCE, "sub": "mbr_7f3a", "role": "member"})}
        self.assertEqual(http("POST", url, {}, bad)[0], 401)

    def test_resolve_requires_relay_and_matching_conversation(self):
        tok, _ = self.start()
        url = self.base + "/v1/sessions/resolve"
        self.assertEqual(http("POST", url, {"dl_user_id": tok["userId"], "conversation_id": tok["conversationId"]}, self.svc("mcp"))[0], 403)
        status, body = http("POST", url, {"dl_user_id": tok["userId"], "conversation_id": "other"}, self.svc("relay"))
        self.assertEqual((status, body["error"]), (403, "conversation_mismatch"))
        self.assertEqual(http("POST", url, {"dl_user_id": "dl_unknown", "conversation_id": "x"}, self.svc("relay"))[0], 401)

    def test_resume_same_member_reuses_conversation_other_member_starts_new(self):
        tok, _ = self.start()
        url = self.base + "/v1/directline/token"
        status, again = http("POST", url, {"reason": "resume", "conversationId": tok["conversationId"]}, self.assertion())
        self.assertEqual((again["conversationId"], again["userId"], again["token"]), (tok["conversationId"], tok["userId"], f"tok2-{tok['conversationId']}"))
        status, other = http("POST", url, {"reason": "resume", "conversationId": tok["conversationId"]}, self.assertion(sub="mbr_2c91"))
        self.assertNotEqual(other["conversationId"], tok["conversationId"])

    def test_read_exchange_scopes(self):
        _, ses = self.start()
        status, body = self.exchange(ses["session_ref"], scope="benefits.read providers.read")
        self.assertEqual(status, 200, body)
        claims = self.decode(body["access_token"], "healthgen-core")
        self.assertEqual((claims["sub"], claims["member_ref"], claims["role"]), ("mbr_7f3a", "mbr_7f3a", "member"))
        self.assertEqual(claims["scope"], "benefits.read providers.read")
        self.assertEqual(claims["act"], {"sub": "mcp-healthgen"})
        status, body = self.exchange(ses["session_ref"], scope="appointment.request")
        self.assertEqual((status, body["error"]), (400, "invalid_scope"))
        status, body = self.exchange("ses_nope")
        self.assertEqual((status, body["error"]), (400, "invalid_grant"))

    def test_provider_session_scoped_to_patient(self):
        _, ses = self.start(sub="prv_pcp_01", role="provider", member_ref="mbr_7f3a", portal="provider")
        status, body = self.exchange(ses["session_ref"])
        claims = self.decode(body["access_token"], "healthgen-core")
        self.assertEqual((claims["sub"], claims["member_ref"], claims["role"]), ("prv_pcp_01", "mbr_7f3a", "provider"))

    def test_hitl_action_lifecycle(self):
        _, ses = self.start()
        sref = ses["session_ref"]
        params = {"provider_ref": "prv_19", "slot_ref": "slt_x", "service_ref": "svc_focused_skin_exam"}
        # MCP creates the pending action; the member ref is filled in by the broker.
        status, created = http("POST", self.base + "/v1/actions", {"session_ref": sref, "kind": "appointment.request", "params": params, "summary": {"facts": [{"title": "Doctor", "value": "Dr. Nina Patel"}]}}, self.svc("mcp"))
        self.assertEqual(status, 201, created)
        aid = created["action_id"]
        # Wrong member and wrong role are refused.
        status, _ = http("POST", self.base + "/v1/actions", {"session_ref": sref, "kind": "appointment.request", "params": {**params, "member_ref": "mbr_2c91"}}, self.svc("mcp"))
        self.assertEqual(status, 403)
        status, _ = http("POST", self.base + "/v1/actions", {"session_ref": sref, "kind": "referral.submit", "params": {"to_provider_ref": "prv_42", "service_ref": "s", "visits": 1}}, self.svc("mcp"))
        self.assertEqual(status, 403)
        # Exchange before confirmation fails; the relay can read the authoritative summary.
        self.assertEqual(self.exchange(sref, action_id=aid)[1]["error"], "confirmation_required")
        status, a = http("GET", f"{self.base}/v1/actions/{aid}?session_ref={sref}", headers=self.svc("relay"))
        self.assertEqual((a["status"], a["summary"]["facts"][0]["value"]), ("pending", "Dr. Nina Patel"))
        self.assertEqual(http("GET", f"{self.base}/v1/actions/{aid}?session_ref=ses_other", headers=self.svc("relay"))[0], 404)
        # Only the relay confirms; the confirmation carries the office note.
        self.assertEqual(http("POST", f"{self.base}/v1/actions/{aid}/confirm", {"session_ref": sref}, self.svc("mcp"))[0], 403)
        status, _ = http("POST", f"{self.base}/v1/actions/{aid}/confirm", {"session_ref": sref, "extras": {"note": "left shoulder", "evil": "x"}}, self.svc("relay"))
        self.assertEqual(status, 200)
        self.assertEqual(http("POST", f"{self.base}/v1/actions/{aid}/confirm", {"session_ref": sref}, self.svc("relay"))[0], 409)
        # Exchange yields a one-time write token bound to the exact parameters.
        status, body = self.exchange(sref, action_id=aid)
        self.assertEqual(status, 200, body)
        claims = self.decode(body["access_token"], "healthgen-core")
        full = {**params, "member_ref": "mbr_7f3a"}
        self.assertEqual(claims["scope"], "appointment.request")
        self.assertEqual(claims["confirmed_action"]["params_sha256"], params_sha256(full))
        self.assertEqual(body["action"]["params"], full)
        self.assertEqual(body["action"]["extras"], {"note": "left shoulder"})
        self.assertEqual(self.exchange(sref, action_id=aid)[1]["error"], "invalid_grant")

    def test_new_review_supersedes_old_pending_action(self):
        _, ses = self.start()
        sref = ses["session_ref"]
        p = {"provider_ref": "prv_19", "slot_ref": "a", "service_ref": "s"}
        first = http("POST", self.base + "/v1/actions", {"session_ref": sref, "kind": "appointment.request", "params": p}, self.svc("mcp"))[1]["action_id"]
        http("POST", self.base + "/v1/actions", {"session_ref": sref, "kind": "appointment.request", "params": {**p, "slot_ref": "b"}}, self.svc("mcp"))
        self.assertEqual(http("POST", f"{self.base}/v1/actions/{first}/confirm", {"session_ref": sref}, self.svc("relay"))[0], 409)

    def test_logout_revokes_sessions(self):
        tok, ses = self.start(sub="mbr_2c91", idm_session="idm-logout")
        self.assertEqual(http("POST", self.base + "/v1/directline/logout", {}, self.assertion(sub="mbr_2c91", idm_session="idm-logout"))[1]["revoked"], 1)
        self.assertEqual(self.exchange(ses["session_ref"])[0], 400)
        status, body = http("GET", f"{self.base}/v1/sessions/{ses['session_ref']}/status", headers=self.svc("apim"))
        self.assertFalse(body["active"])


class KeyVaultSignerTest(unittest.TestCase):
    """Exercises the Key Vault REST shape against a local fake that signs with a local key."""

    def test_sign_and_jwks(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from app.signer import b64url, b64url_decode

        key = RsaKey()
        pub = key.jwks["keys"][0]
        seen = {}

        async def get_key(request: Request):
            seen["auth"] = request.headers.get("authorization")
            seen["api"] = request.query_params.get("api-version")
            return JSONResponse({"key": {"kid": "https://kv/keys/broker/v1", "kty": "RSA-HSM", "n": pub["n"], "e": pub["e"]}})

        async def sign(request: Request):
            body = await request.json()
            assert body["alg"] == "RS256"
            from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
            sig = key.private.sign(b64url_decode(body["value"]), padding.PKCS1v15(), Prehashed(hashes.SHA256()))
            return JSONResponse({"kid": "x", "value": b64url(sig)})

        app = Starlette(routes=[Route("/keys/broker/v1", get_key), Route("/keys/broker/v1/sign", sign, methods=["POST"])])

        class Cred:
            def token(self, resource):
                return "mi-token"

        import urllib.request
        with serve(app) as base:
            signer = KeyVaultSigner(f"{base}/keys/broker/v1", credential=Cred(), opener=urllib.request.build_opener(urllib.request.ProxyHandler({})))
            token = signer.sign({"iss": ISS, "aud": "a", "sub": "s", "iat": 1, "exp": 9999999999})
            jwks = signer.jwks()
        self.assertEqual((seen["auth"], seen["api"]), ("Bearer mi-token", "7.4"))
        self.assertEqual(jwt.get_unverified_header(token)["kid"], "v1")
        claims = jwt.decode(token, jwt.PyJWK(jwks["keys"][0]).key, algorithms=["RS256"], audience="a")
        self.assertEqual(claims["sub"], "s")


if __name__ == "__main__":
    unittest.main()
