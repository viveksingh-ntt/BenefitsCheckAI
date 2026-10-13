# `tests/e2e/test_local_stack.py`

Source: [`tests/e2e/test_local_stack.py`](../../../../../tests/e2e/test_local_stack.py)

> **Summary:** An end-to-end test over HTTP, talking exactly as the widget does. It starts the six local processes on ports 9101–9105 and 9080 and drives the real flows through portal-dev, the broker, the Direct Line emulator, the relay, `foundry-local`, MCP and the core mock.

Run with `python -m unittest discover -s tests/e2e -v` (5 tests).

## `Browser` helper

It keeps cookies and plays one browser tab:

- `sign_in(user)`: portal cookie, then token, then a Direct Line conversation;
- `post` (always with a **spoofed `from.id`**, to prove the emulator overwrites it), `say`, `press(verb, **data)` and `event`;
- `until(predicate)`: watermark polling;
- `card(template_id)`.

## Tests

| Test | Flow |
| --- | --- |
| `test_member_benefit_check_to_booking` | Context event with a spoofed member is ignored; benefit card with Alex's $40 HMO copay; service.find gives Patel and Chen with member actions; provider.view navigates; availability; review gives an `actionId`; confirm with a note gives "Booked"; a second confirm says "already handled". |
| `test_provider_referral` | Provider audience actions; referral review; attest=false refused; attest=true gives "Submitted". |
| `test_member_cannot_use_provider_actions` | A member pressing referral.review gets no referral card. |
| `test_handoff` | `handoffRequest` gives a `handoff` event with an `HO-` ticket. |
| `test_direct_line_token_is_bound_to_its_conversation` | One user's token cannot read or post to another conversation. |

## How it's used in the real system

It guards the contracts between the layers in CI. For a deployed environment, run the runbook's smoke tests and the four prototype journeys manually, or adapt this test to sign in through a test portal.
