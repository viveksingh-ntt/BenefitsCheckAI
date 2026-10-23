# `services/agent-relay/relay/agui.py`

Source: [`services/agent-relay/relay/agui.py`](../../../../../../services/agent-relay/relay/agui.py)

> **Summary:** The protocol layer of the relay's AG-UI host: it turns a `RunAgentInput` into the activities `RelayCore` already understands, and turns the core's reply activities into AG-UI events.

| | |
| --- | --- |
| Layer | Agent relay (AG-UI path) |
| Local run | **Real**, used by `host_agui.py` |
| Azure | **Real**, in the `agent-relay-agui` image |

## What it does

**Inbound: `to_activities(run, user_id, thread)`** returns `(activities, direct_reply)`:

- `context` entries `page` / `locale` become a `context` event. Any `member` the client sends is ignored.
- `resume` is checked against the thread's open interrupts. Missing answers → `InputError("interrupt_pending")`, unknown ids → `unknown_interrupt`, a bad shape → `invalid_resume`.
- An approved resume becomes the existing card action: `appointment.confirm` with `{actionId, officeNote}`, or `referral.submit` with `{actionId, attest, clinicalNote}`. A declined resume returns a fixed reply (`DECLINED`) and nothing reaches the core.
- `forwardedProps.action` becomes an `Action.Execute` message (`handoff` becomes a `handoffRequest` event), and `forwardedProps.journey` becomes a `startJourney` event.
- From `messages`, only the newest `user` message is used. Client-sent history, `state` and `tools` are ignored.

**Outbound: `EventMapper(thread_id, run_id, thread)`:**

- `typing` → `STEP_STARTED` / `STEP_FINISHED`.
- A message → `TEXT_MESSAGE_START/CONTENT/END`, plus `ACTIVITY_SNAPSHOT` for the `result_chip`, the Adaptive Card (`adaptive_card`, `{templateId, card}`) and `suggestions`, and `STATE_DELTA` for `/breadcrumb`.
- A review card (an `Action.Execute` whose verb is in `REVIEW_VERBS` and whose `data.actionId` starts with `act_`) becomes an interrupt: `reason: confirmation`, a `responseSchema` requiring `approved`, `expiresAt` in 15 minutes (the broker's action lifetime) and `metadata {verb, templateId}`.
- `navigate` / `handoff` events → `CUSTOM`.
- `finish()` stores the open interrupts on the thread and emits `RUN_FINISHED` with `outcome` `success` or `interrupt`. `error()` emits `RUN_ERROR`.

**`ThreadStore`** keeps, per thread: open interrupts, the transcript (last 200 entries) and state. It is in memory with a 12-hour TTL.

`sse(event)` writes one `data: {json}` frame with a millisecond `timestamp`.

## How it's used in the real system

Only through [`host_agui.py`](../../../../files/services/agent-relay/host_agui.py.md). For more than one replica, back `ThreadStore` with Redis (same interface). The mapping is documented in [AG-UI](../../../../../ag-ui.md).
