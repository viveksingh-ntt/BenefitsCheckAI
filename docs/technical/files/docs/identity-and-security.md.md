# `docs/identity-and-security.md`

Source: [`docs/identity-and-security.md`](../../../identity-and-security.md)

> **Summary:** The identity and security design: why the in-house IdM identity is carried by the broker and not by the model, the six credentials and their lifetimes, the six rules that don't depend on the model, a threat-and-mitigation table, and production follow-ups.

Use it for security review and threat modelling. The code that implements each rule is linked from the per-file pages for the [broker](../../files/services/identity-broker/app/main.py.md), [MCP tools](../../files/services/mcp-healthgen/app/tools.py.md), [relay core](../../files/services/agent-relay/relay/core.py.md) and [core mock](../../files/services/healthgen-core-mock/app/main.py.md).
