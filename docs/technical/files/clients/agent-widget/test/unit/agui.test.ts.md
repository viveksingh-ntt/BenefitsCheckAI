# `clients/agent-widget/test/unit/agui.test.ts`

Source: [`clients/agent-widget/test/unit/agui.test.ts`](../../../../../../../clients/agent-widget/test/unit/agui.test.ts)

> **Summary:** Unit tests for `AgUiTransport` with a fake `fetch` that returns SSE streams split mid-frame.

| | |
| --- | --- |
| Layer | Agentic Client Widget |
| Package | `clients/agent-widget` |

Covers: the thread from the token response; a text turn's `RunAgentInput` and the event → activity mapping (typing, text, result chip, breadcrumb, card, suggestions, navigate); interrupt → cancel → resume with the office note; referral attestation; journeys and hand-off as `forwardedProps`; 401 refresh-and-retry; restore of transcript and interrupts on resume; turn ordering. Run with `npm test` (8 of 24 tests).
