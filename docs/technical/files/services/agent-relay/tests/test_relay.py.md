# `services/agent-relay/tests/test_relay.py`

Source: [`services/agent-relay/tests/test_relay.py`](../../../../../../services/agent-relay/tests/test_relay.py)

> **Summary:** Unit tests for the relay core, envelope parsing, masking and templates. The broker, card store and Foundry are replaced by in-process fakes, so the tests are fast and deterministic.

Run with `cd services/agent-relay && python -m unittest discover -s tests` (19 tests).

| Test | Proves |
| --- | --- |
| `test_text_turn_with_card_and_follow_up` | The order is typing, lead message (with result chip), card, then follow-up with suggestions. The turn context contains `session_ref`. |
| `test_conversation_is_reused` | One Foundry conversation per Direct Line conversation. |
| `test_card_from_other_session_or_unknown_template_is_dropped` | Cards are session-bound and only allow-listed templates render. |
| `test_card_ref_fallback_from_mcp_output` | The `card_ref` is recovered from `mcp_call` output. |
| `test_card_action_forwards_only_validated_refs` | Free text and malformed refs never reach the model. |
| `test_navigation_verbs_do_not_call_the_agent` | `provider.view` becomes a `navigate` event. |
| `test_unknown_verb` | Unknown verbs are refused without calling the model. |
| `test_confirm_unlocks_write_via_broker` | A confirmation reaches the broker with the note, the note does not reach the model, and a second press is refused. |
| `test_confirm_rejects_wrong_kind_bad_id_and_missing_attestation` | Confirmation edge cases. |
| `test_context_event_sets_page_but_ignores_client_identity` | A spoofed member ref is ignored; locale and page are used. |
| `test_start_journey_and_handoff_events` | Journey and hand-off events, and the `handoff` activity. |
| `test_plain_text_and_masking` | The plain-text fallback, SSN and ID masking, and ref removal. |
| `test_guardrail_and_errors` | 403 and 5xx replies. |
| `test_session_ended` / `test_rate_limit` | Session and rate-limit messages. |
| `EnvelopeAndTemplateTest` | Envelope parsing, masking, `$when` audience actions, and the `actionId` in review cards. |
