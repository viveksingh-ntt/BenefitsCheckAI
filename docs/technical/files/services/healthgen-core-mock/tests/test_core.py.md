# `services/healthgen-core-mock/tests/test_core.py`

Source: [`services/healthgen-core-mock/tests/test_core.py`](../../../../../../services/healthgen-core-mock/tests/test_core.py)

> **Summary:** HTTP tests for the core mock, with a test RSA key acting as the broker and the date pinned to 14 Oct 2026. Run with `cd services/healthgen-core-mock && python -m unittest discover -s tests` (12 tests).

| Test | Proves |
| --- | --- |
| `test_health_is_public` | `/healthz` needs no token. |
| `test_rejects_missing_bad_and_foreign_tokens` | 401 for a missing or foreign-signed token, 403 for a wrong scope. |
| `test_member_scope_is_enforced` | 403 `member_mismatch`. |
| `test_member_profile_and_eligibility` | Profile fields, no date of birth, active coverage. |
| `test_dermatology_benefit_matches_prototype` | $40 copay, referral, no prior auth, cosmetic not covered. |
| `test_accumulators_remaining` | $1,050 remaining. |
| `test_prior_auth` | Mohs needs prior auth. |
| `test_service_search` | "changing mole" finds the focused exam. |
| `test_provider_search_by_network_and_distance` | HMO network filter, distances ≈ 0.6 and 1.3 mi, radius filter, unknown ZIP gives 400. |
| `test_availability_starts_next_business_day` | First slot Thu 15 Oct 10:30. |
| `test_appointment_needs_matching_one_time_confirmation` | Missing, mismatched or replayed confirmations are refused; the slot leaves availability. |
| `test_referral_is_provider_only_and_panel_scoped` | Member refused, off-panel refused, 90-day validity. |
