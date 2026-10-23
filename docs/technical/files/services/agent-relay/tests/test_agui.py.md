# `services/agent-relay/tests/test_agui.py`

Source: [`services/agent-relay/tests/test_agui.py`](../../../../../../services/agent-relay/tests/test_agui.py)

> **Summary:** HTTP + SSE tests of `host_agui` with the real `RelayCore` and the in-process fakes from `test_relay.py`.

| | |
| --- | --- |
| Layer | Agent relay tests |
| Runs | `python -m unittest discover -s tests` in `services/agent-relay` (8 of 27 tests) |

## What it covers

- A text turn streams steps, text, the bound card, result chip, suggestions, breadcrumb and `RUN_FINISHED`. Planted history is not passed to the agent.
- A review card ends the run in an interrupt. New input without answering it gets `interrupt_pending`. An approved resume confirms at the broker exactly once and tells the agent to submit, without the office note. A replay gets `unknown_interrupt`.
- A declined resume never reaches the broker or the agent.
- A card button with the interrupt cancelled goes through the safe-action filter.
- Referral attestation maps to the existing check (no attestation → nothing confirmed).
- navigate, hand-off and journeys; token audience, thread binding and the thread snapshot; session end still answers.
