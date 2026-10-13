# `services/agent-relay/relay/envelope.py`

Source: [`services/agent-relay/relay/envelope.py`](../../../../../../services/agent-relay/relay/envelope.py)

> **Summary:** Parses and validates the JSON reply envelope that agents return, and masks sensitive patterns in all outbound text and logs.

| | |
| --- | --- |
| Layer | Agent relay |
| Runs in | Everywhere, unchanged |

## What it does

- **`Envelope`**
  - A Pydantic model of the agent contract: `reply` (required, ≤ 4,000 chars), `card_ref` (must match `crd_` + 16 hex), `follow_up`, `result_chip`, `breadcrumb`, `suggestions` (≤ 6; plain strings are accepted and converted), `handoff {ticket_ref, reason}` and `navigate {route}`.
  - Unknown fields are ignored. Empty strings and `"null"` become `None`.
- **`parse_envelope(text) → (Envelope, followed_contract)`**
  - Strips a code fence, or finds the outermost `{…}` in the text.
  - If validation fails but a `reply` string exists, it keeps just the reply.
  - Otherwise the whole text becomes the reply. A turn therefore always produces something to show.
- **`mask_outbound(text)`**
  - Replaces internal refs (`ses_`, `act_`, `crd_`, `mbr_`, `dl_`) with `[ref]`.
  - Masks SSN-shaped numbers to `***-**-1234`.
  - Masks digit runs of 9 or more to `••••` plus the last 4.
- **`redact_for_log(text)`** logs only the length, optionally with a masked prefix in dev.

## How it's used in the real system

The masking is a last line of defence, not the main control. The main controls are that the model gets no member identifiers and that cards come from data. Add patterns here if your member ID format differs: HealthGen IDs shorter than 9 digits would not be caught by `_LONG_DIGITS`.

The envelope contract is shared with the agents through [`agents/partials/envelope.md`](../../../../files/agents/partials/envelope.md.md). Change both together.

## Related

Tests: `EnvelopeAndTemplateTest` and `test_plain_text_and_masking` in [`tests/test_relay.py`](../tests/test_relay.py.md).
