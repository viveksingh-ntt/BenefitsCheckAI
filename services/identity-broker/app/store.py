"""Session bindings and pending actions.

Pilot storage is SQLite (single replica). For more than one replica, swap ``SqliteStore`` for a shared store
(Azure Cache for Redis or Cosmos DB) behind the same methods. Nothing here holds PHI: a binding has refs only.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Binding:
    session_ref: str
    dl_user_id: str
    conversation_id: str
    principal_ref: str
    role: str
    member_ref: str | None
    portal: str
    idm_session: str | None
    display_name: str | None
    created_at: float
    expires_at: float
    revoked: bool = False

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("idm_session", None)
        return d


@dataclass
class Action:
    action_id: str
    session_ref: str
    kind: str
    params: dict[str, Any]
    status: str  # pending | confirmed | consumed | cancelled
    summary: dict[str, Any] | None
    created_at: float
    expires_at: float
    extras: dict[str, Any] | None = None  # free-text inputs from the review card (office note); not part of the hash


def new_ref(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(16)}"


class SqliteStore:
    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS bindings (
                  session_ref TEXT PRIMARY KEY, dl_user_id TEXT UNIQUE NOT NULL, conversation_id TEXT NOT NULL,
                  principal_ref TEXT NOT NULL, role TEXT NOT NULL, member_ref TEXT, portal TEXT NOT NULL,
                  idm_session TEXT, display_name TEXT, created_at REAL NOT NULL, expires_at REAL NOT NULL,
                  revoked INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS bindings_conv ON bindings(conversation_id);
                CREATE INDEX IF NOT EXISTS bindings_idm ON bindings(idm_session);
                CREATE TABLE IF NOT EXISTS actions (
                  action_id TEXT PRIMARY KEY, session_ref TEXT NOT NULL, kind TEXT NOT NULL, params TEXT NOT NULL,
                  status TEXT NOT NULL, summary TEXT, created_at REAL NOT NULL, expires_at REAL NOT NULL, extras TEXT);
                """
            )

    # ---------------------------------------------------------------- bindings

    def put_binding(self, b: Binding) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO bindings VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (b.session_ref, b.dl_user_id, b.conversation_id, b.principal_ref, b.role, b.member_ref, b.portal,
                 b.idm_session, b.display_name, b.created_at, b.expires_at, int(b.revoked)),
            )

    def _binding(self, row: sqlite3.Row | None) -> Binding | None:
        if not row:
            return None
        d = dict(row)
        d["revoked"] = bool(d["revoked"])
        return Binding(**d)

    def binding_by_session(self, session_ref: str) -> Binding | None:
        with self._lock:
            return self._binding(self._db.execute("SELECT * FROM bindings WHERE session_ref=?", (session_ref,)).fetchone())

    def binding_by_dl_user(self, dl_user_id: str) -> Binding | None:
        with self._lock:
            return self._binding(self._db.execute("SELECT * FROM bindings WHERE dl_user_id=?", (dl_user_id,)).fetchone())

    def binding_by_conversation(self, conversation_id: str) -> Binding | None:
        with self._lock:
            return self._binding(self._db.execute("SELECT * FROM bindings WHERE conversation_id=?", (conversation_id,)).fetchone())

    def extend(self, session_ref: str, expires_at: float) -> None:
        with self._lock:
            self._db.execute("UPDATE bindings SET expires_at=? WHERE session_ref=?", (expires_at, session_ref))

    def revoke_idm_session(self, idm_session: str) -> int:
        with self._lock:
            cur = self._db.execute("UPDATE bindings SET revoked=1 WHERE idm_session=?", (idm_session,))
            self._db.execute(
                "UPDATE actions SET status='cancelled' WHERE status IN ('pending','confirmed') AND session_ref IN "
                "(SELECT session_ref FROM bindings WHERE idm_session=?)", (idm_session,))
            return cur.rowcount

    def revoke_session(self, session_ref: str) -> None:
        with self._lock:
            self._db.execute("UPDATE bindings SET revoked=1 WHERE session_ref=?", (session_ref,))
            self._db.execute("UPDATE actions SET status='cancelled' WHERE session_ref=? AND status IN ('pending','confirmed')", (session_ref,))

    # ----------------------------------------------------------------- actions

    def put_action(self, a: Action) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO actions VALUES (?,?,?,?,?,?,?,?,?)",
                (a.action_id, a.session_ref, a.kind, json.dumps(a.params), a.status, json.dumps(a.summary) if a.summary else None,
                 a.created_at, a.expires_at, json.dumps(a.extras) if a.extras else None),
            )

    def get_action(self, action_id: str) -> Action | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM actions WHERE action_id=?", (action_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["params"] = json.loads(d["params"])
        d["summary"] = json.loads(d["summary"]) if d["summary"] else None
        d["extras"] = json.loads(d["extras"]) if d["extras"] else None
        return Action(**d)

    def transition(self, action_id: str, session_ref: str, from_status: str, to_status: str, extras: dict[str, Any] | None = None) -> bool:
        """Atomic compare-and-set so a confirmation can be consumed exactly once."""
        with self._lock:
            if extras is None:
                cur = self._db.execute(
                    "UPDATE actions SET status=? WHERE action_id=? AND session_ref=? AND status=? AND expires_at>?",
                    (to_status, action_id, session_ref, from_status, time.time()))
            else:
                cur = self._db.execute(
                    "UPDATE actions SET status=?, extras=? WHERE action_id=? AND session_ref=? AND status=? AND expires_at>?",
                    (to_status, json.dumps(extras), action_id, session_ref, from_status, time.time()))
            return cur.rowcount == 1

    def cancel_pending(self, session_ref: str, kind: str) -> None:
        with self._lock:
            self._db.execute("UPDATE actions SET status='cancelled' WHERE session_ref=? AND kind=? AND status='pending'", (session_ref, kind))

    def purge(self, now: float | None = None) -> None:
        now = now or time.time()
        with self._lock:
            self._db.execute("DELETE FROM actions WHERE expires_at < ?", (now - 86400,))
            self._db.execute("DELETE FROM bindings WHERE expires_at < ?", (now - 86400,))
