# `services/identity-broker/app/store.py`

Source: [`services/identity-broker/app/store.py`](../../../../../../services/identity-broker/app/store.py)

> **Summary:** The broker's state: session bindings and pending actions, in SQLite for the pilot. It holds refs only and no PHI.

## What it does

- **`Binding`:** `session_ref`, `dl_user_id`, `conversation_id`, `principal_ref`, `role`, `member_ref`, `portal`, `idm_session`, `display_name`, timestamps and `revoked`. `public()` hides `idm_session`.
- **`Action`:** `action_id`, `session_ref`, `kind`, the original `params`, `status` (`pending`, `confirmed`, `consumed` or `cancelled`), `summary` (review facts), `extras` (note or reason) and expiry. The parameters are stored as JSON; `main.py` computes their canonical SHA-256 digest when issuing a confirmed-action token.
- **`SqliteStore`:**
  - bindings: put, and look up by session, Direct Line user or conversation; `extend`; `revoke_session`; `revoke_idm_session`;
  - actions: put, get, `cancel_pending`, `purge`;
  - **`transition(action_id, session_ref, from, to, extras?)`:** an atomic compare-and-set that also checks expiry. This is what makes "confirm once, consume once" safe under concurrency.
- **`new_ref(prefix)`:** a 128-bit random ref (`ses_…`, `act_…`).

The SQLite connection is shared across threads with a process-local lock around database operations. Tables and indexes are created when the store is constructed. `Binding.public()` removes `idm_session` before exposing a binding dictionary; the API normally returns narrower response objects instead.

## How it's used in the real system

SQLite in `/tmp` means **one replica** and loss of sessions on restart (users simply start a new conversation). The store also provides `purge(now)`, which deletes expired actions and bindings after an additional 24-hour retention window; it is not scheduled by this module. Before scaling out, implement the same methods on Azure Cache for Redis (`SET NX` and Lua or `WATCH` for `transition`) or Cosmos DB (ETag-conditional updates). `main.py` only uses these methods.

## Related

[operations](../../../../../operations.md) · tests: `test_hitl_action_lifecycle`, `test_new_review_supersedes_old_pending_action` and `test_logout_revokes_sessions`.
