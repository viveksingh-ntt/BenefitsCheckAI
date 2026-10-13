# `services/agent-relay/templates/availability-slots@1.json`

Source: [`services/agent-relay/templates/availability-slots@1.json`](../../../../../../services/agent-relay/templates/availability-slots@1.json)

> **Summary:** Adaptive Card template `availability-slots@1`. Open appointment times with the chosen doctor. Choosing a time does not book it.

| | |
| --- | --- |
| Layer | Presentation (relay-owned card templates) |
| Bound by | `relay/templating.py` in the relay, everywhere |
| Data built by | `services/mcp-healthgen/app/cards.py`: `availability_card() ← get_availability` |
| Adaptive Cards version | 1.5. `Org.SelectableList` is the widget's custom element, with a standard fallback. |

## Data the template expects

doctor{name,practice,ref}, service, slots[{ref,label,detail}], selected, serviceRef, notice

## Inputs

slotRef (Org.SelectableList)

## Actions (`Action.Execute`)

| Button | Verb | Data sent | Handled by |
| --- | --- | --- | --- |
| Review booking | `appointment.review` | providerRef, serviceRef + slotRef | Agent: prepare_appointment_request |
| Change doctor | `providers.back` | (no inputs) | Agent: find_providers again |

The widget merges the card inputs into `data`, except where an action has `associatedInputs: none`. The relay then keeps only the allow-listed keys (see `SAFE_DATA` in [`relay/core.py`](../relay/core.py.md)).

## How it's used in the real system

- **Same everywhere:** this file is used unchanged in every environment. The widget's own copy (in the `agent-widget` repo) only drives the widget's mock demo.
- **Allowlist:** the file name (minus `.json`) is the template id that the MCP card store refers to. Only templates in this folder can be rendered, so the folder is also the allowlist.
- **Changing a template:** don't edit a live template in place. Add `availability-slots@2`, update the matching builder in `cards.py`, then remove `@1` once no card shown in the last 30 minutes uses it.
