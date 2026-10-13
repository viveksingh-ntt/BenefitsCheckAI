# `services/agent-relay/relay/templating.py`

Source: [`services/agent-relay/relay/templating.py`](../../../../../../services/agent-relay/relay/templating.py)

> **Summary:** A small, safe implementation of Adaptive Cards Templating in Python. It binds the JSON templates in `templates/` to the card data from the MCP card store.

| | |
| --- | --- |
| Layer | Agent relay |
| Runs in | Everywhere, unchanged |

## What it does

`expand_template(template, data)` walks the template JSON:

- **`"${expr}"`:** a whole-string expression keeps its type (a list stays a list). An interpolated string is converted to text.
- **`"$data"`:** an array repeats the element once per item (`$index` is available). An object changes the scope.
- **`"$when"`:** the element is dropped when the expression is false. A property whose value was dropped disappears, as in the JavaScript SDK.
- **Expressions:** expressions are tokenised and parsed by a recursive-descent parser (never `eval`). They support:
  - member and index access, `$root`, `$data` and `$index`;
  - string, number, boolean and null literals;
  - `== != < > <= >= && || !`;
  - the functions `count`, `if`, `concat` and `toUpper`.

This is the same subset as the widget repo's mock templating (`src/mock/templating.ts`), so a card looks the same in the mock demo and in the real system.

## How it's used in the real system

It runs in the relay for every card. If future templates need more of the templating language (for example `formatDateTime` or `json()`), add the functions to `FUNCTIONS`. Alternatively, switch to Microsoft's templating SDK in a Node sidecar, but the pure-Python version keeps the relay to a single runtime.

## Related

[`templates/`](../templates/benefit-coverage@1.json.md) · Tests: `test_provider_template_audience` and `test_review_template_carries_action_id`.
