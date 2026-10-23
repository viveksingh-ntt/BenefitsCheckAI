# `services/identity-broker/tests/test_agui_tokens.py`

Source: [`services/identity-broker/tests/test_agui_tokens.py`](../../../../../../services/identity-broker/tests/test_agui_tokens.py)

> **Summary:** Unit tests for the AG-UI chat token endpoint against a real broker app with a fake portal key.

| | |
| --- | --- |
| Layer | Identity broker tests |
| Runs | `python -m unittest discover -s tests` in `services/identity-broker` (5 of 16 tests) |

## What it covers

- The token's claims (`aud`, `sub` prefix, `tid`, `typ`) and that `/v1/sessions/resolve` maps the AG-UI user to the portal principal.
- Resume rules: same user resumes their thread; another user naming it gets a new thread; refresh extends the binding.
- Logout through `/v1/directline/logout` ends AG-UI resumes too.
- Missing or bad portal assertion → 401.
- Direct Line switched off: `/v1/directline/token` answers 502/503 while `/v1/agui/token` works.
