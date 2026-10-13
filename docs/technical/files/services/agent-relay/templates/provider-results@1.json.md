# `services/agent-relay/templates/provider-results@1.json`

Source: [`services/agent-relay/templates/provider-results@1.json`](../../../../../../services/agent-relay/templates/provider-results@1.json)

> **Summary:** Adaptive Card template `provider-results@1`. In-network doctors (prototype screens 1 and 4). The actions differ by audience: members get *Check availability*, providers get *Review referral*.

| | |
| --- | --- |
| Layer | Presentation (relay-owned card templates) |
| Bound by | `relay/templating.py` in the relay, everywhere |
| Data built by | `services/mcp-healthgen/app/cards.py`: `providers_card() ← find_providers` |
| Adaptive Cards version | 1.5. `Org.SelectableList` is the widget's custom element, with a standard fallback. |

## Data the template expects

title, doctors[{ref,initials,name,specialty,practice,services,network,address,distanceText}], plan, radius, zip, selected, audience ('member'|'provider'), serviceRef, notice

## Inputs

providerRef (Org.SelectableList)

## Actions (`Action.Execute`)

| Button | Verb | Data sent | Handled by |
| --- | --- | --- | --- |
| Check availability (members) | `appointment.availability` | serviceRef + providerRef | Agent: get_availability |
| Review referral (providers) | `referral.review` | serviceRef + providerRef | Agent: prepare_referral |
| View doctor | `provider.view` | providerRef, keepActive | Relay: navigate to /providers/{providerRef} |

The widget merges the card inputs into `data`, except where an action has `associatedInputs: none`. The relay then keeps only the allow-listed keys (see `SAFE_DATA` in [`relay/core.py`](../relay/core.py.md)).

## How it's used in the real system

- **Same everywhere:** this file is used unchanged in every environment. The widget's own copy (in the `agent-widget` repo) only drives the widget's mock demo.
- **Allowlist:** the file name (minus `.json`) is the template id that the MCP card store refers to. Only templates in this folder can be rendered, so the folder is also the allowlist.
- **Changing a template:** don't edit a live template in place. Add `provider-results@2`, update the matching builder in `cards.py`, then remove `@1` once no card shown in the last 30 minutes uses it.
