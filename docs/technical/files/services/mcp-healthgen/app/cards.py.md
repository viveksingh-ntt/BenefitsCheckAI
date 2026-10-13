# `services/mcp-healthgen/app/cards.py`

Source: [`services/mcp-healthgen/app/cards.py`](../../../../../../services/mcp-healthgen/app/cards.py)

> **Summary:** Builds Adaptive Card data from core responses and stores it under short, session-bound `card_ref`s, so the relay renders cards from system-of-record data instead of model text.

## What it does

- **`CardStore`:**
  - in memory, with a 30-minute TTL and a cap of 50,000 cards (evicting expired cards first);
  - `put(session_ref, template_id, data)` returns `crd_<16 hex>`;
  - `get(card_ref, session_ref)` returns `None` for an unknown, expired or other-session card.
- **Formatting helpers:** `money` ("$40"), `cost_text` ("$40 specialist copay per visit", "20% coinsurance"), `slot_label` ("Thu, Oct 15 · 10:30 AM") and `initials`.
- **Builders, one per template:** `benefit_card`, `service_card` (with `DISTANCE_OPTIONS`), `providers_card` (audience-aware network text), `availability_card`, `booking_review_card` and `referral_review_card` (with `actionId`), and `confirmation_card`.

The output shapes match the relay's [templates](../../../../files/services/agent-relay/templates/benefit-coverage@1.json.md).

## How it's used in the real system

The relay reads cards through `GET /internal/cards/{ref}?session_ref=` (see `main.py`).

- **Scaling:** the store is in memory, so the pilot runs **one replica**. Move it to Redis, keyed by `card_ref` with the session ref in the value and a TTL, before scaling.
- **Copy:** the notice texts (the cost disclaimer, "Nothing is booked until you confirm") are compliance copy. Have them reviewed and keep them here, not in prompts.
