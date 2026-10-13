# HealthGen core mock

This service has synthetic data only. It stands in for the HealthGen core APIs, and the MCP data spoke depends only on this HTTP contract. Every route except `/healthz` needs the broker's downstream JWT (`aud=healthgen-core`), and the token's scope must include the route's scope.

| Method and path | Scope |
| --- | --- |
| `GET /v1/members/{member_ref}` | `members.read` |
| `GET /v1/members/{member_ref}/eligibility` | `eligibility.read` |
| `GET /v1/members/{member_ref}/accumulators` | `accumulators.read` |
| `GET /v1/members/{member_ref}/benefits?service_ref=&category=` | `benefits.read` |
| `GET /v1/members/{member_ref}/prior-auth?service_ref=` | `priorauth.read` |
| `GET /v1/services?q=&category=` | `services.read` |
| `GET /v1/providers?specialty=&service_ref=&plan_ref=&zip=&radius_miles=&accepting_only=` | `providers.read` |
| `GET /v1/providers/{ref}` and `/availability?service_ref=` | `providers.read` |
| `POST /v1/appointments/requests` | `appointment.request` plus `confirmed_action` |
| `POST /v1/referrals` | `referral.submit` plus `confirmed_action` (provider tokens only) |

Rules the mock enforces:

- `member_ref` in the path must equal the token's `member_ref`.
- Provider tokens also need the member on the provider's panel.
- Writes need a `confirmed_action` whose `params_sha256` matches the request body, and each one can be used only once.
