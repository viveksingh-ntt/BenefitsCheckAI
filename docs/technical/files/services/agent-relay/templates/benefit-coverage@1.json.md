# `services/agent-relay/templates/benefit-coverage@1.json`

Source: [`services/agent-relay/templates/benefit-coverage@1.json`](../../../../../../services/agent-relay/templates/benefit-coverage@1.json)

> **Summary:** Adaptive Card template `benefit-coverage@1`. Benefit check result (prototype screen 2): the service, the plan and year, a coverage badge, a fact list (network, visit cost, deductible, referral, prior auth, limits) and a notice.

| | |
| --- | --- |
| Layer | Presentation (relay-owned card templates) |
| Bound by | `relay/templating.py` in the relay, everywhere |
| Data built by | `services/mcp-healthgen/app/cards.py`: `benefit_card() ← check_benefits` |
| Adaptive Cards version | 1.5. `Org.SelectableList` is the widget's custom element, with a standard fallback. |

## Data the template expects

service{name,category,ref}, plan{name,year,ref}, coverage.label, facts[{title,value}], notice

## Inputs

none

## Actions (`Action.Execute`)

| Button | Verb | Data sent | Handled by |
| --- | --- | --- | --- |
| Find this service | `service.find` | serviceRef | Agent: searches for doctors for this service |
| View plan details | `plan.details` | planRef, keepActive | Relay: navigate to /plan/benefits |

The widget merges the card inputs into `data`, except where an action has `associatedInputs: none`. The relay then keeps only the allow-listed keys (see `SAFE_DATA` in [`relay/core.py`](../relay/core.py.md)).

## How it's used in the real system

- **Same everywhere:** this file is used unchanged in every environment. The widget's own copy (in the `agent-widget` repo) only drives the widget's mock demo.
- **Allowlist:** the file name (minus `.json`) is the template id that the MCP card store refers to. Only templates in this folder can be rendered, so the folder is also the allowlist.
- **Changing a template:** don't edit a live template in place. Add `benefit-coverage@2`, update the matching builder in `cards.py`, then remove `@1` once no card shown in the last 30 minutes uses it.
