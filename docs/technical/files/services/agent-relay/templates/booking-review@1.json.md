# `services/agent-relay/templates/booking-review@1.json`

Source: [`services/agent-relay/templates/booking-review@1.json`](../../../../../../services/agent-relay/templates/booking-review@1.json)

> **Summary:** Adaptive Card template `booking-review@1`. Human-in-the-loop review of an appointment request. The facts come from the broker's pending action, and nothing is booked until Confirm.

| | |
| --- | --- |
| Layer | Presentation (relay-owned card templates) |
| Bound by | `relay/templating.py` in the relay, everywhere |
| Data built by | `services/mcp-healthgen/app/cards.py`: `booking_review_card() ← prepare_appointment_request` |
| Adaptive Cards version | 1.5. `Org.SelectableList` is the widget's custom element, with a standard fallback. |

## Data the template expects

actionId, providerRef, slotRef, facts[{title,value}], notice

## Inputs

officeNote (optional, ≤300 chars; goes to the broker as extras.note, never to the model)

## Actions (`Action.Execute`)

| Button | Verb | Data sent | Handled by |
| --- | --- | --- | --- |
| Confirm booking | `appointment.confirm` | providerRef, slotRef, **actionId** + officeNote | Relay: broker confirm, then agent → submit_appointment_request |
| Change time | `appointment.availability` | providerRef | Agent: get_availability |

The widget merges the card inputs into `data`, except where an action has `associatedInputs: none`. The relay then keeps only the allow-listed keys (see `SAFE_DATA` in [`relay/core.py`](../relay/core.py.md)).

## How it's used in the real system

- **Same everywhere:** this file is used unchanged in every environment. The widget's own copy (in the `agent-widget` repo) only drives the widget's mock demo.
- **Allowlist:** the file name (minus `.json`) is the template id that the MCP card store refers to. Only templates in this folder can be rendered, so the folder is also the allowlist.
- **Changing a template:** don't edit a live template in place. Add `booking-review@2`, update the matching builder in `cards.py`, then remove `@1` once no card shown in the last 30 minutes uses it.
