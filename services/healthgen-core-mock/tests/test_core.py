import datetime as dt
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "libs" / "testkit"), str(pathlib.Path(__file__).resolve().parents[1])]

from testkit import RsaKey, http, serve  # noqa: E402

from app.auth import TokenValidator, params_sha256  # noqa: E402
from app.main import create_app  # noqa: E402

ISS = "https://broker.test"
TODAY = dt.date(2026, 10, 14)  # Wednesday


class CoreMockTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = RsaKey()
        cls.other = RsaKey()
        app = create_app(TokenValidator(issuer=ISS, jwks=cls.key.jwks), today=lambda: TODAY)
        cls._ctx = serve(app)
        cls.base = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def token(self, scope, member_ref="mbr_7f3a", sub=None, role="member", key=None, **extra):
        claims = {"iss": ISS, "aud": "healthgen-core", "sub": sub or member_ref, "role": role, "member_ref": member_ref, "scope": scope, "sid": "ses_test", **extra}
        return {"Authorization": "Bearer " + (key or self.key).sign(claims)}

    def get(self, path, scope, **kw):
        return http("GET", self.base + path, headers=self.token(scope, **kw))

    def test_health_is_public(self):
        self.assertEqual(http("GET", self.base + "/healthz")[0], 200)

    def test_rejects_missing_bad_and_foreign_tokens(self):
        self.assertEqual(http("GET", self.base + "/v1/members/mbr_7f3a")[0], 401)
        status, body = self.get("/v1/members/mbr_7f3a", "members.read", key=self.other)
        self.assertEqual((status, body["error"]["code"]), (401, "invalid_token"))
        status, body = self.get("/v1/members/mbr_7f3a", "benefits.read")
        self.assertEqual((status, body["error"]["code"]), (403, "insufficient_scope"))

    def test_member_scope_is_enforced(self):
        status, body = self.get("/v1/members/mbr_2c91/benefits", "benefits.read", member_ref="mbr_7f3a")
        self.assertEqual((status, body["error"]["code"]), (403, "member_mismatch"))

    def test_member_profile_and_eligibility(self):
        status, body = self.get("/v1/members/mbr_7f3a", "members.read")
        self.assertEqual(status, 200)
        self.assertEqual(body["display_name"], "Alex Morgan")
        self.assertEqual(body["plan"]["name"], "Harbor HMO")
        self.assertEqual(body["pcp"]["name"], "Dr. Priya Raman")
        self.assertNotIn("date_of_birth", body)
        status, body = self.get("/v1/members/mbr_7f3a/eligibility", "eligibility.read")
        self.assertTrue(body["active_on_date"])

    def test_dermatology_benefit_matches_prototype(self):
        status, body = self.get("/v1/members/mbr_7f3a/benefits?service_ref=svc_focused_skin_exam", "benefits.read")
        self.assertEqual(status, 200)
        row = body["benefits"][0]
        self.assertEqual(row["in_network"]["copay"], 40.0)
        self.assertTrue(row["referral_required"])
        self.assertFalse(row["prior_auth_required"])
        status, body = self.get("/v1/members/mbr_7f3a/benefits?category=dermatology", "benefits.read")
        cosmetic = next(r for r in body["benefits"] if r["service"]["ref"] == "svc_cosmetic_skin_screening")
        self.assertFalse(cosmetic["covered"])

    def test_accumulators_remaining(self):
        _, body = self.get("/v1/members/mbr_7f3a/accumulators", "accumulators.read")
        self.assertEqual(body["deductible"]["individual_remaining"], 1050.0)

    def test_prior_auth(self):
        _, body = self.get("/v1/members/mbr_7f3a/prior-auth?service_ref=svc_mohs_surgery", "priorauth.read")
        self.assertTrue(body["prior_auth_required"])

    def test_service_search(self):
        _, body = self.get("/v1/services?q=changing%20mole", "services.read")
        self.assertIn("svc_focused_skin_exam", [s["ref"] for s in body["services"]])

    def test_provider_search_by_network_and_distance(self):
        q = "/v1/providers?specialty=dermatology&service_ref=svc_focused_skin_exam&plan_ref=pln_harbor_hmo_2026&zip=10013&radius_miles=5"
        _, body = self.get(q, "providers.read")
        refs = [p["ref"] for p in body["providers"]]
        self.assertEqual(refs, ["prv_19", "prv_42"])  # prv_57 is PPO only
        self.assertAlmostEqual(body["providers"][0]["distance_miles"], 0.6, delta=0.2)
        self.assertAlmostEqual(body["providers"][1]["distance_miles"], 1.3, delta=0.2)
        _, body = self.get(q.replace("radius_miles=5", "radius_miles=1"), "providers.read")
        self.assertEqual([p["ref"] for p in body["providers"]], ["prv_19"])
        status, _ = self.get("/v1/providers?zip=99999", "providers.read")
        self.assertEqual(status, 400)

    def test_availability_starts_next_business_day(self):
        _, body = self.get("/v1/providers/prv_19/availability", "providers.read")
        self.assertTrue(body["slots"])
        self.assertTrue(body["slots"][0]["start"].startswith("2026-10-15T10:30"))

    def _appointment(self, slot_ref):
        return {"member_ref": "mbr_7f3a", "provider_ref": "prv_19", "slot_ref": slot_ref, "service_ref": "svc_focused_skin_exam"}

    def test_appointment_needs_matching_one_time_confirmation(self):
        _, avail = self.get("/v1/providers/prv_19/availability", "providers.read")
        slot = avail["slots"][1]["ref"]
        params = self._appointment(slot)
        url = self.base + "/v1/appointments/requests"
        # No confirmation at all.
        status, body = http("POST", url, params, self.token("appointment.request"))
        self.assertEqual((status, body["error"]["code"]), (403, "confirmation_required"))
        # Confirmation for different parameters.
        other = {**params, "slot_ref": avail["slots"][0]["ref"]}
        ca = {"id": "act_1", "kind": "appointment.request", "params_sha256": params_sha256(other)}
        status, body = http("POST", url, params, self.token("appointment.request", confirmed_action=ca))
        self.assertEqual((status, body["error"]["code"]), (403, "confirmation_mismatch"))
        # Matching confirmation books; the same token cannot be replayed.
        ca = {"id": "act_2", "kind": "appointment.request", "params_sha256": params_sha256(params)}
        headers = self.token("appointment.request", confirmed_action=ca)
        status, body = http("POST", url, {**params, "note": "left shoulder"}, headers)
        self.assertEqual(status, 201, body)
        self.assertEqual(body["status"], "booked")
        self.assertEqual(body["confirmation_id"], "act_2")
        status, body = http("POST", url, params, headers)
        self.assertEqual(status, 409)
        # The slot is gone from availability.
        _, avail2 = self.get("/v1/providers/prv_19/availability", "providers.read")
        self.assertNotIn(slot, [s["ref"] for s in avail2["slots"]])

    def test_referral_is_provider_only_and_panel_scoped(self):
        params = {"member_ref": "mbr_7f3a", "to_provider_ref": "prv_42", "service_ref": "svc_focused_skin_exam", "visits": 1}
        ca = {"id": "act_r", "kind": "referral.submit", "params_sha256": params_sha256(params)}
        url = self.base + "/v1/referrals"
        status, body = http("POST", url, params, self.token("referral.submit", confirmed_action=ca))
        self.assertEqual((status, body["error"]["code"]), (403, "provider_only"))
        status, body = http("POST", url, {**params, "member_ref": "mbr_2c91"}, self.token("referral.submit", member_ref="mbr_2c91", sub="prv_pcp_01", role="provider", confirmed_action=ca))
        self.assertEqual((status, body["error"]["code"]), (403, "not_on_panel"))
        status, body = http("POST", url, params, self.token("referral.submit", sub="prv_pcp_01", role="provider", confirmed_action=ca))
        self.assertEqual(status, 201, body)
        self.assertEqual(body["referring_provider_ref"], "prv_pcp_01")
        self.assertEqual(body["valid_to"], "2027-01-12")


if __name__ == "__main__":
    unittest.main()
