# `services/agent-relay/requirements-agui.txt`

Source: [`services/agent-relay/requirements-agui.txt`](../../../../../services/agent-relay/requirements-agui.txt)

> **Summary:** Python dependencies of the AG-UI host: the relay core's `requirements.txt` plus PyJWT with crypto, for checking the broker's chat token.

| | |
| --- | --- |
| Layer | Agent relay (AG-UI path) |
| Used by | `Dockerfile.agui`, local runs |

It doesn't include the M365 Agents SDK, which only `host_m365.py` needs.
