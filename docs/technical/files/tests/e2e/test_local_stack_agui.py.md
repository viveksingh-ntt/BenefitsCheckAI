# `tests/e2e/test_local_stack_agui.py`

Source: [`tests/e2e/test_local_stack_agui.py`](../../../../../tests/e2e/test_local_stack_agui.py)

> **Summary:** End-to-end tests over AG-UI: starts the local AG-UI stack and talks to it the way `AgUiTransport` does (BFF token, `RunAgentInput`, SSE).

| | |
| --- | --- |
| Layer | End-to-end tests |
| Run | `python -m unittest tests.e2e.test_local_stack_agui -v` (7 tests, ports 9181 and 9201–9206) |

## What it covers

- Member benefit check through booking: card data from Alex's plan (the spoofed member in `context` is ignored), navigate, the review card ending in an interrupt, `interrupt_pending` when it is not answered, confirm by resume, and a replay refused.
- Declining the review books nothing.
- Provider referral with the attestation check.
- A member can't use provider actions.
- Hand-off and journeys.
- Token/thread binding, resume after reload, and a different user naming the thread getting a new one.
- CORS allows only the portal origin.
