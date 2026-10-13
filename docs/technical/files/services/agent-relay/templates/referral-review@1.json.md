# `services/agent-relay/templates/referral-review@1.json`

Source: [`services/agent-relay/templates/referral-review@1.json`](../../../../../../services/agent-relay/templates/referral-review@1.json)

> **Summary:** Adaptive Card template `referral-review@1`. Provider review of a drafted referral, with a required medical-necessity attestation.

| | |
| --- | --- |
| Layer | Presentation (relay-owned card templates) |
| Bound by | `relay/templating.py` in the relay, everywhere |
| Data built by | `services/mcp-healthgen/app/cards.py`: `referral_review_card() ← prepare_referral` |
| Adaptive Cards version | 1.5. `Org.SelectableList` is the widget's custom element, with a standard fallback. |

## Data the template expects

actionId, memberName, providerRef, serviceRef, facts[{title,value}], notice

## Inputs

clinicalNote (optional; broker extras.reason, never to the model), attest (required toggle, must be 'true')

## Actions (`Action.Execute`)

| Button | Verb | Data sent | Handled by |
| --- | --- | --- | --- |
| Submit referral | `referral.submit` | providerRef, serviceRef, **actionId** + inputs | Relay: checks attest, broker confirm, then agent → submit_referral |
| Change doctor | `providers.back` | (no inputs) | Agent: find_providers again |

The widget merges the card inputs into `data`, except where an action has `associatedInputs: none`. The relay then keeps only the allow-listed keys (see `SAFE_DATA` in [`relay/core.py`](../relay/core.py.md)).

## How it's used in the real system

- **Same everywhere:** this file is used unchanged in every environment. The widget's own copy (in the `agent-widget` repo) only drives the widget's mock demo.
- **Allowlist:** the file name (minus `.json`) is the template id that the MCP card store refers to. Only templates in this folder can be rendered, so the folder is also the allowlist.
- **Changing a template:** don't edit a live template in place. Add `referral-review@2`, update the matching builder in `cards.py`, then remove `@1` once no card shown in the last 30 minutes uses it.
