# `clients/agent-widget/src/core/agui.ts`

Source: [`clients/agent-widget/src/core/agui.ts`](../../../../../../../clients/agent-widget/src/core/agui.ts)

> **Summary:** `AgUiTransport`: the widget's AG-UI transport. It implements the same `Transport` interface as `DirectLineTransport`, so the UI, card renderer and host events don't change.

| | |
| --- | --- |
| Layer | Agentic Client Widget |
| Package | `clients/agent-widget` |

## What it does

- **`connect()`** gets a chat token (`reason: start`, or `resume` with the stored thread id). When resuming the same thread, it loads `GET {endpoint}/threads/{id}` and replays the transcript as activities and keeps the open interrupts. It schedules a token refresh 60 s before expiry.
- **`post(activity)`** builds one `RunAgentInput` per user turn:
  - a `context` event is stored and sent as `context` with the next run;
  - text → `messages`; card buttons → `forwardedProps.action`; `startJourney` → `forwardedProps.journey`; `handoffRequest` → `forwardedProps.action {verb: 'handoff'}`;
  - Confirm/Submit on a review card whose `actionId` is an open interrupt → `resume` resolved with `{approved: true, note, attest}`;
  - every other open interrupt is sent as `cancelled`, as the protocol requires.
  Runs are serialized, so turns stay in order. On 401 it refreshes the token once and retries; a second 401/403 sets status `expiredToken`.
- **The stream** is read with `fetch` (so the token stays in a header, not a URL) and parsed as SSE. Events map back onto activities: steps → informative typing, text → streaming typing then a final message, snapshots → card, suggestions and result chip on that message, `STATE_DELTA` → breadcrumb, `CUSTOM` → navigate/handoff events, `RUN_FINISHED` → open interrupts are replaced by the run's, `RUN_ERROR` → a warning message.

## How it's used in the real system

```js
widget.init({ transport: () => new AgentWidget.AgUiTransport({ getToken: AgentWidget.tokenUrlFetcher('/api/agent/agui-token'), endpoint: 'https://<relay>/agui' }) })
```

See [AG-UI](../../../../../../ag-ui.md) and [`agui.test.ts`](../../../../../files/clients/agent-widget/test/unit/agui.test.ts.md).
