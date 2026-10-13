# `services/mcp-healthgen/tests/test_mcp.py`

Source: [`services/mcp-healthgen/tests/test_mcp.py`](../../../../../../services/mcp-healthgen/tests/test_mcp.py)

> **Summary:** An integration test that uses the **real MCP client** against the real MCP server, the real identity broker and the core mock on localhost, with a fake Direct Line and a fake n8n that checks the HMAC signature. Run with `cd services/mcp-healthgen && python -m unittest discover -s tests` (9 tests).

`load_service()` imports each service's `app` package side by side, under separate module trees.

| Test | Proves |
| --- | --- |
| `test_rejects_unauthenticated_mcp` | No credential or a wrong key gives 401. |
| `test_lists_tools_with_annotations` | All tools are listed, `submit_*` is destructive, `session_ref` is required, and no `member_ref` appears in any schema. |
| `test_benefit_check_screen` | The $40 copay and referral rule; the card is stored, session-bound and relay-only. |
| `test_invalid_session_ref_is_a_tool_error` | An unknown session gives `invalid_grant`, and a member id in place of a session ref is rejected by the schema. |
| `test_service_and_provider_search_screens` | Home ZIP default, cosmetic excluded, Patel and Chen in order, member audience. |
| `test_booking_requires_confirmation_in_card` | Slot labels, `actionId` in the card, early submit refused, booking after the relay confirms, single use. |
| `test_provider_referral_flow` | Provider audience, booking refused for providers, referral prepared and submitted. |
| `test_member_cannot_refer` | Role check. |
| `test_handoff_posts_signed_webhook_without_member_ids` | Signature verified; payload has no member ids. |
