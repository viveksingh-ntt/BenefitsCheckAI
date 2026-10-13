# `handoff/healthgen-handoff.n8n.json`

Source: [`handoff/healthgen-handoff.n8n.json`](../../../../handoff/healthgen-handoff.n8n.json)

> **Summary:** An importable n8n workflow for human hand-off. It verifies the MCP server's signed webhook, creates a ticket, notifies the care team and returns the ticket ref to the agent.

| | |
| --- | --- |
| Local run | Not used: a stub route in `foundry-local` returns a ticket |
| Azure / production | **Real**, on your n8n instance |

## Nodes

1. **Hand-off webhook:** `POST /webhook/healthgen-handoff`, answered by a response node.
2. **Verify signature (Code):**
   - recomputes `sha256=HMAC(HEALTHGEN_HANDOFF_SECRET, timestamp + "." + JSON.stringify(body))`, compares in constant time, and allows a 5-minute window;
   - cleans up the fields: session ref (40 chars), audience, an allow-listed reason, topic (200 chars);
   - sets the priority (`clinical` and `complaint` are high).
3. **Signed? (IF):** valid requests go on; others get **Reject** (401).
4. **Create ticket (Code):** produces an `HO-####` ref and picks the queue (`provider-services` or `care-team`). **Replace this node with your CRM's create-case call.**
5. **Notify care team (HTTP):** posts to `HEALTHGEN_CARE_TEAM_WEBHOOK_URL` (Teams or Slack). It is set to continue on failure.
6. **Return ticket:** `{ticket_ref, queue, expected_response}`.

## n8n host settings

- `HEALTHGEN_HANDOFF_SECRET`
- `HEALTHGEN_CARE_TEAM_WEBHOOK_URL`
- `NODE_FUNCTION_ALLOW_BUILTIN=crypto`

## How it's used in the real system

Care specialists get a session ref, not PHI. They open the conversation in your agent console, or contact the member through normal channels. The Python signer (`HandoffClient`) and this verifier were checked against each other, including non-ASCII text.
