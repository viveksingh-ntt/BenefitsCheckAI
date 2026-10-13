# `services/healthgen-core-mock/app/main.py`

Source: [`services/healthgen-core-mock/app/main.py`](../../../../../../services/healthgen-core-mock/app/main.py)

> **Summary:** The HealthGen core mock's HTTP API: member, eligibility, accumulators, benefits, prior auth, service catalogue, providers, availability, and the two write endpoints (appointments, referrals). It enforces the same authorization rules the real core must enforce.

| | |
| --- | --- |
| Layer | System of record (**mock**) |
| Local run and pilot | Used, run with `uvicorn app.main:app --port 8101` |
| Production | **Replaced** by the real HealthGen core APIs. Only `CORE_URL` in the MCP server changes, if the real APIs follow this contract. |

## What it does

Every route except `/healthz` goes through `authed(scope)`:

1. Validates the broker's downstream JWT (`auth.TokenValidator`).
2. Requires the route's scope.
3. Maps errors to JSON `{"error": {"code", "message"}}`: 401, 403, 404 or 400.

`member_for(principal, member_ref)` enforces two rules:

- the path member equals the token's `member_ref`;
- for provider tokens, the member is on the provider's panel (`PROVIDER_PANELS`).

| Route | Behaviour |
| --- | --- |
| `GET /v1/members/{ref}` | Profile without date of birth: first name, display name, last 4 of the id, plan, home ZIP, PCP. |
| `…/eligibility` | Status, dates, and `active_on_date` for today. |
| `…/accumulators` | Deductible and out-of-pocket, limit, met and remaining. |
| `…/benefits?service_ref=&category=` | Benefit rows for the member's plan. |
| `…/prior-auth?service_ref=` | Prior-auth and referral flags. |
| `GET /v1/services?q=&category=` | Keyword match over names, descriptions and keywords. |
| `GET /v1/providers?…` | Filters by specialty, service, plan network (default in-network only), accepting new patients, and ZIP radius. Uses haversine distance, nearest first. Unknown ZIP gives 400. |
| `GET /v1/providers/{ref}`, `…/availability` | Provider, and open slots (booked ones removed). |
| `POST /v1/appointments/requests` | Checks the member, **consumes the confirmation** (kind and parameter hash, single-use `jti`), checks the slot, books it (409 if taken), and returns `APT-…`. |
| `POST /v1/referrals` | Providers only, panel check, consumes the confirmation, creates `REF-…`, valid 90 days. |

`Store` holds bookings and referrals in memory. `create_app(validator?, today?)` lets tests pin the date.

## How it's used in the real system

This file is the **contract** the real core needs to meet, or that an adapter in front of it must provide. The rules above are the minimum the real core must enforce:

- the member scope from the token;
- the provider panel;
- the one-time confirmed action, with its parameter hash.

Then a compromised MCP server or model still cannot reach other members' data or write without a person's confirmation.

## Related

[`auth.py`](auth.py.md) · [`data.py`](data.py.md) · [`README.md`](../README.md.md) · [`tests/test_core.py`](../tests/test_core.py.md)
