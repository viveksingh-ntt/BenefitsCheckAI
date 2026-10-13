# `scripts/local_stack.py`

Source: [`scripts/local_stack.py`](../../../../scripts/local_stack.py)

> **Summary:** Starts the whole stack on localhost, as six uvicorn processes wired together with dev keys. The end-to-end tests also use it.

## Usage

```bash
python scripts/local_stack.py              # ports 8101–8105 and portal 8080
python scripts/local_stack.py --base 9100  # ports 9101–9105 and portal 9080
```

## What it does

- **`plan(base)`** returns one entry per process, with the working directory, ASGI app, port and environment:

  | Port | Process |
  | --- | --- |
  | 8101 | Core mock |
  | 8102 | Broker |
  | 8103 | MCP server |
  | 8104 | `dev_server.py` (Direct Line emulator plus relay) |
  | 8105 | `foundry-local` |
  | 8080 | portal-dev |

  It also sets the shared dev keys and secrets (`dev-relay-key`, `local-dev-secret` and so on), sets `NO_PROXY` for localhost, and puts the broker's SQLite file in a temp folder.
- **`running(base, quiet)`** starts the processes, waits until each one answers (`/healthz`, or `/` for the portal) within 30 s, yields the URLs, and stops everything on exit.
- **`main()`** prints the URLs and keeps running until Ctrl-C.

## How it's used in the real system

It isn't. It is for development, demos and CI. The keys in it only work against these local processes. The Azure configuration is in the runbook.

## Related

[sequence 10](../../sequences.md#10-local-stack-and-automated-tests) · [`tests/e2e/test_local_stack.py`](../tests/e2e/test_local_stack.py.md)
