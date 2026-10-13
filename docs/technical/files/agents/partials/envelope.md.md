# `agents/partials/envelope.md`

Source: [`agents/partials/envelope.md`](../../../../../agents/partials/envelope.md)

> **Summary:** The shared "how to answer" contract, inserted into every agent's instructions with `{{> envelope}}`. Agents answer with one JSON reply envelope that the relay renders.

## Contract

`{"reply", "card_ref", "follow_up", "result_chip", "breadcrumb", "suggestions", "handoff", "navigate"}`, with rules on length and tone, on copying `card_ref` exactly, on suggestion phrasing (with one marked recommended), and on when `handoff` or `navigate` may be set.

**Always-on rules:**

- no ids, refs, dates of birth or full ID numbers in text;
- costs are estimates;
- no diagnosis;
- urgent symptoms go to 911 or the person's doctor.

## How it's used in the real system

The relay parses the envelope with [`relay/envelope.py`](../../../files/services/agent-relay/relay/envelope.py.md). The two must change together. A field added here and not in `Envelope` is silently ignored.
