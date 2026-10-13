# `services/agent-relay/templates/service-options@1.json`

Source: [`services/agent-relay/templates/service-options@1.json`](../../../../../../services/agent-relay/templates/service-options@1.json)

> **Summary:** Adaptive Card template `service-options@1`. Service search (prototype screen 3): ZIP and distance inputs plus a selectable list of covered services matching the need.

| | |
| --- | --- |
| Layer | Presentation (relay-owned card templates) |
| Bound by | `relay/templating.py` in the relay, everywhere |
| Data built by | `services/mcp-healthgen/app/cards.py`: `service_card() ← search_services` |
| Adaptive Cards version | 1.5. `Org.SelectableList` is the widget's custom element, with a standard fallback. |

## Data the template expects

title, subtitle, zip, distance, distanceOptions[{title,value}], services[{ref,name,description}], selected, notice

## Inputs

zip (5 digits, required), distance (1/5/10/25), serviceRef (Org.SelectableList, falls back to Input.ChoiceSet)

## Actions (`Action.Execute`)

| Button | Verb | Data sent | Handled by |
| --- | --- | --- | --- |
| Find doctors | `providers.search` | inputs | Agent: find_providers with service_ref, zip, radius_miles |
| Service details | `service.details` | serviceRef, keepActive | Relay: navigate to /care/services/{serviceRef} |

The widget merges the card inputs into `data`, except where an action has `associatedInputs: none`. The relay then keeps only the allow-listed keys (see `SAFE_DATA` in [`relay/core.py`](../relay/core.py.md)).

## How it's used in the real system

- **Same everywhere:** this file is used unchanged in every environment. The widget's own copy (in the `agent-widget` repo) only drives the widget's mock demo.
- **Allowlist:** the file name (minus `.json`) is the template id that the MCP card store refers to. Only templates in this folder can be rendered, so the folder is also the allowlist.
- **Changing a template:** don't edit a live template in place. Add `service-options@2`, update the matching builder in `cards.py`, then remove `@1` once no card shown in the last 30 minutes uses it.
