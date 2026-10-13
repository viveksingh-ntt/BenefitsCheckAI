# `services/agent-relay/templates/confirmation@1.json`

Source: [`services/agent-relay/templates/confirmation@1.json`](../../../../../../services/agent-relay/templates/confirmation@1.json)

> **Summary:** Adaptive Card template `confirmation@1`. The result of a completed write (*Booked* or *Submitted*): a status badge, a title, reference facts and a notice.

| | |
| --- | --- |
| Layer | Presentation (relay-owned card templates) |
| Bound by | `relay/templating.py` in the relay, everywhere |
| Data built by | `services/mcp-healthgen/app/cards.py`: `confirmation_card() ← submit_appointment_request / submit_referral` |
| Adaptive Cards version | 1.5. `Org.SelectableList` is the widget's custom element, with a standard fallback. |

## Data the template expects

status, title, facts[{title,value}], notice

## Inputs

none

## Actions (`Action.Execute`)

| Button | Verb | Data sent | Handled by |
| --- | --- | --- | --- |
| – | – | – | – |

The widget merges the card inputs into `data`, except where an action has `associatedInputs: none`. The relay then keeps only the allow-listed keys (see `SAFE_DATA` in [`relay/core.py`](../relay/core.py.md)).

## How it's used in the real system

- **Same everywhere:** this file is used unchanged in every environment. The widget's own copy (in the `agent-widget` repo) only drives the widget's mock demo.
- **Allowlist:** the file name (minus `.json`) is the template id that the MCP card store refers to. Only templates in this folder can be rendered, so the folder is also the allowlist.
- **Changing a template:** don't edit a live template in place. Add `confirmation@2`, update the matching builder in `cards.py`, then remove `@1` once no card shown in the last 30 minutes uses it.
