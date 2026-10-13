# `services/agent-relay/relay/core.py`

Source: [`services/agent-relay/relay/core.py`](../../../../../../services/agent-relay/relay/core.py)

> **Summary:** The relay's brain. It turns one Direct Line activity into one agent turn and turns the agent's reply into Direct Line activities, enforcing every rule that must not depend on the model.

| | |
| --- | --- |
| Layer | Agent relay |
| Local run | Real code, loaded by `dev_server.py` |
| Azure (pilot and production) | Real code, loaded by `host_m365.py` |
| Depends on | `clients.py` (broker, cards, Foundry), `envelope.py`, `templating.py`, `templates/*.json` |

## What it does

`RelayCore.on_activity(activity, send)` handles one incoming activity:

1. It **identifies the user** by asking the broker to resolve `from.id` plus `conversation.id` into a `session_ref`, role, portal and user-context token. Anything the client sends as identity is ignored.
2. It **rate-limits** each conversation (20 turns a minute by default) and serialises turns per conversation with a lock.
3. It **plans** the turn (`_plan`), which becomes one of:
   - a **direct reply**, which never calls the model: navigation verbs, unknown verbs, oversized text, attachments, expired confirmations;
   - an **agent turn**, with a progress line and a sanitised input sentence;
   - **nothing**, for the `context` event, which only stores the page route and locale.
4. It **asks the triage agent** (`_ask_agent`). It creates the Foundry conversation on the first turn, prefixes a `[turn-context]` block (`session_ref`, `portal`, `locale`, `page`), calls the Responses API and parses the reply envelope.
5. It **fetches the card**. It uses the envelope's `card_ref`, or the newest `card_ref` in the response's `mcp_call` outputs (`last_card_ref`). It reads the card data from the MCP card store, checks the template id against the allowlist and binds the template.
6. It **sends the activities** (`_emit`): optional `navigate` and `handoff` events, then the lead message with `resultChip` and `breadcrumb`, then the card message, then the follow-up message with `suggestedActions`. All text goes through `mask_outbound`.

## Key parts

| Name | Purpose |
| --- | --- |
| `SAFE_DATA` | The allowlist of card and journey keys the model may see, with a regex each, mapped to snake_case names (`serviceRef` → `service_ref`). Anything else, including free-text inputs such as `officeNote`, is dropped. |
| `AGENT_VERBS` | Card verbs forwarded to the agent, each with a button label and a progress line. |
| `CONFIRM_VERBS` | `appointment.confirm` and `referral.submit`: the action kind, the submit tool, the extras mapping (`officeNote` → `note`, `clinicalNote` → `reason`) and whether attestation is required. |
| `NAVIGATE_VERBS` | Verbs answered by a `navigate` event to a route template, with no model call. |
| `JOURNEYS` | `startJourney` ids mapped to a plain-language goal. |
| `TemplateStore` | Loads `templates/*.json` and renders through `templating.expand_template`. The set of loaded ids is the template allowlist. |
| `ConversationState` | Per-conversation Foundry conversation id, page route, locale, rate-limit window and lock. It lives in memory and is garbage-collected after 4 hours idle. |
| `_plan_confirm` | Human in the loop. Checks the action id shape, requires the referral attestation, gets the action from the broker (must be `pending` and the right kind), confirms it with the extras, then tells the agent to call the submit tool. |
| `last_card_ref` | Fallback that finds a `card_ref` in MCP call outputs when the agent forgot to include it. |

## How it's used in the real system

The same file runs in Azure inside `host_m365.py`, behind Azure Bot Service. Production changes:

- **Conversation state:** with more than one relay replica, move `ConversationState` (the Foundry conversation id) to Redis, or use sticky sessions. Losing it only starts a new Foundry conversation.
- **Messages:** the copy (for example "Your session has ended…") lives here. Localise it if the portals need Spanish replies from the relay itself; the agents already answer in the user's locale.
- **New card actions:** a new card button needs its verb added to `AGENT_VERBS`, `CONFIRM_VERBS` or `NAVIGATE_VERBS`, and any new data key added to `SAFE_DATA`. Otherwise the relay answers "That option isn't available any more".

## Related

- Tests: [`tests/test_relay.py`](../tests/test_relay.py.md), which covers all the planning paths, confirmation, masking, rate limiting and errors.
- Flows: [benefit check](../../../../sequences.md#2-a-benefit-check-question), [card buttons](../../../../sequences.md#3-pressing-a-card-button), [booking](../../../../sequences.md#4-booking-with-human-confirmation), [failures](../../../../sequences.md#8-failures-and-guardrails).
