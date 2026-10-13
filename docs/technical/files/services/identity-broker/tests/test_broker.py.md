# `services/identity-broker/tests/test_broker.py`

Source: [`services/identity-broker/tests/test_broker.py`](../../../../../../services/identity-broker/tests/test_broker.py)

> **Summary:** Tests the broker over real HTTP, with a fake Direct Line, a test portal key and a fake Key Vault. Run with `cd services/identity-broker && python -m unittest discover -s tests` (11 tests).

| Test | Proves |
| --- | --- |
| `test_jwks_and_discovery` | Public keys and metadata are served. |
| `test_directline_token_binds_dl_user_and_trusted_origins` | The `dl_` id and trusted origins are sent to Direct Line, the relay never sees member ids, and the user-context claims are right. |
| `test_rejects_bad_assertions` | Missing, too long-lived, cross-member and wrongly signed assertions are refused. |
| `test_resolve_requires_relay_and_matching_conversation` | Only the relay may resolve, and the conversation must match. |
| `test_resume_same_member_reuses_conversation_other_member_starts_new` | Resume rules. |
| `test_read_exchange_scopes` | Read-only exchange, write scope refused, unknown session refused. |
| `test_provider_session_scoped_to_patient` | A provider token carries the patient's `member_ref`. |
| `test_hitl_action_lifecycle` | Create, role and member checks, confirmation required, relay-only confirm, extras filtering, one-time write token with the parameter hash. |
| `test_new_review_supersedes_old_pending_action` | Only the latest review card can be confirmed. |
| `test_logout_revokes_sessions` | Logout ends exchange and status. |
| `KeyVaultSignerTest.test_sign_and_jwks` | The Key Vault REST shape (sign and get key) gives verifiable JWTs. |
