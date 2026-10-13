# `services/agent-relay/requirements.txt`

Source: [`services/agent-relay/requirements.txt`](../../../../../services/agent-relay/requirements.txt)

> **Summary:** The pinned dependencies of the relay core and the local Direct Line emulator: `starlette`, `uvicorn[standard]`, `pydantic` and `anyio`.

This is enough for `dev_server.py` and the unit tests. The production host needs [`requirements-host.txt`](requirements-host.txt.md), which includes this file.
