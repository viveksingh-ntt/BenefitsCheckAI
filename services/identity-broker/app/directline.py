"""Server-side Direct Line 3.0 calls that need the channel secret. The secret never reaches the browser.

With Direct Line *enhanced authentication* on (required), a token generated for ``user.id`` binds that id: the
channel rejects or overrides any other ``from.id`` the client sends, which is what lets the relay trust ``from.id``.
Enhanced authentication also requires user ids to start with ``dl_``.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class DirectLineError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class DirectLineClient:
    def __init__(self, secret: str, endpoint: str = "https://directline.botframework.com", timeout: float = 10, opener: Any = None):
        if not secret:
            raise ValueError("DIRECTLINE_SECRET is required")
        self.secret = secret
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        # Local dev points at the emulator on localhost; bypass any environment proxy for it.
        local = self.endpoint.startswith(("http://localhost", "http://127.0.0.1"))
        self._opener = opener or urllib.request.build_opener(*( [urllib.request.ProxyHandler({})] if local else []))

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        req = urllib.request.Request(
            self.endpoint + path,
            data=json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None),
            method=method,
            headers={"Authorization": f"Bearer {self.secret}", "Content-Type": "application/json"},
        )
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            raise DirectLineError(exc.code, f"Direct Line {method} {path} failed: {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise DirectLineError(502, f"Direct Line unreachable: {exc.reason}") from exc

    def generate_token(self, user_id: str, user_name: str | None = None, trusted_origins: list[str] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"user": {"id": user_id, **({"name": user_name} if user_name else {})}}
        if trusted_origins:
            body["trustedOrigins"] = trusted_origins
        return self._call("POST", "/v3/directline/tokens/generate", body)

    def reconnect(self, conversation_id: str, watermark: str | None = None) -> dict[str, Any]:
        """Fresh token and stream URL for an existing conversation (resume after reload or long sleep)."""
        from urllib.parse import quote

        path = f"/v3/directline/conversations/{quote(conversation_id, safe='')}"
        if watermark:
            path += f"?watermark={quote(watermark, safe='')}"
        return self._call("GET", path)
