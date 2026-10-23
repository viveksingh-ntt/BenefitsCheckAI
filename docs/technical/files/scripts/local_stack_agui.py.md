# `scripts/local_stack_agui.py`

Source: [`scripts/local_stack_agui.py`](../../../../scripts/local_stack_agui.py)

> **Summary:** Starts the whole stack locally over AG-UI: core mock, broker (`app.main_agui`), MCP, Foundry stand-in, the relay's `host_agui` on 8106 and `portal-dev-agui` on 8081. No Direct Line emulator.

| | |
| --- | --- |
| Layer | Local tooling |
| Run | `python scripts/local_stack_agui.py [--base 9200]` |

It reuses `plan()` from [`local_stack.py`](../../files/scripts/local_stack.py.md) and changes only what differs: the broker's entry point and portal issuer, the relay's app, port and CORS, and the portal folder. `running()` is a context manager used by the e2e tests.
