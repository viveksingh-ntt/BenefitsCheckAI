# `services/agent-relay/dev_server.py`

Source: [`services/agent-relay/dev_server.py`](../../../../../services/agent-relay/dev_server.py)

> **Summary:** A local Direct Line 3.0 emulator with the real relay core running in the same process. It lets the real widget and broker run end to end without Azure Bot Service.

| | |
| --- | --- |
| Layer | Direct Line (stand-in) plus Agent relay (real core) |
| Local run | **Used:** `uvicorn dev_server:app --port 8104` (started by `scripts/local_stack.py`) |
| Azure | Not deployed. Azure Bot Service plus `host_m365.py` replace it. |

## What it does

It implements the subset of Direct Line that the widget and the broker use, over HTTP polling (no WebSocket stream, so the widget falls back to polling):

| Endpoint | Auth | Behaviour |
| --- | --- | --- |
| `POST /v3/directline/tokens/generate` | Channel secret | Creates a conversation bound to `user.id`. It requires the `dl_` prefix, as enhanced authentication does. |
| `POST /v3/directline/tokens/refresh` | Token | Issues a new token for the same conversation. |
| `POST /v3/directline/conversations` | Token | Returns the token's own conversation. |
| `GET /v3/directline/conversations/{id}` | Secret, or that conversation's token | Issues a fresh token, used for resume. |
| `POST /v3/directline/conversations/{id}/activities` | Token for that conversation | Stores the activity, **forces `from.id` to the token's user**, and runs `RelayCore.on_activity` in a background task. Bot replies are appended to the same conversation. |
| `GET /v3/directline/conversations/{id}/activities?watermark=N` | Token | Returns activities from index N and the new watermark. |
| `POST …/upload` | – | 501 Not Supported. |

CORS allows only `DEV_CORS_ORIGINS` (the local portal).

## Configuration

`DIRECTLINE_SECRET` (shared with the broker), `DEV_CORS_ORIGINS`, and all [`relay.factory`](relay/factory.py.md) variables.

## How it's used in the real system

It isn't. It is a development and test tool, kept close to the real Direct Line behaviour so that the same widget and broker code work unchanged. Don't expose it on a network: it keeps everything in memory and has no rate limits.

## Related

[Sequence 1](../../../sequences.md#1-start-a-chat-session) · [Sequence 10](../../../sequences.md#10-local-stack-and-automated-tests) · [`tests/e2e/test_local_stack.py`](../../../files/tests/e2e/test_local_stack.py.md) (includes the token-binding test)
