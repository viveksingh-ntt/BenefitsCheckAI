"""HTTP clients for the identity broker and HealthGen core (stdlib urllib, run in worker threads)."""

from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


class UpstreamError(Exception):
    def __init__(self, status: int, code: str, message: str = ""):
        super().__init__(message or code)
        self.status = status
        self.code = code


def _opener_for(url: str) -> urllib.request.OpenerDirector:
    local = urllib.parse.urlparse(url).hostname in ("localhost", "127.0.0.1")
    return urllib.request.build_opener(urllib.request.ProxyHandler({})) if local else urllib.request.build_opener()


def _request(opener: urllib.request.OpenerDirector, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float) -> Any:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read() or b"{}")
        except json.JSONDecodeError:
            payload = {}
        e = payload.get("error")
        code = e.get("code") if isinstance(e, dict) else (e or f"http_{exc.code}")
        raise UpstreamError(exc.code, str(code), str(payload.get("error_description") or (e.get("message") if isinstance(e, dict) else "")))
    except urllib.error.URLError as exc:
        raise UpstreamError(503, "upstream_unreachable", str(exc.reason))


@dataclass
class Grant:
    token: str
    expires_at: float
    claims: dict[str, Any]
    action: dict[str, Any] | None = None


def _unverified_claims(token: str) -> dict[str, Any]:
    # Our own token, just received from the broker over TLS; the core verifies the signature.
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


class BrokerClient:
    def __init__(self, base_url: str, credential: Callable[[], str], timeout: float = 10):
        self.base = base_url.rstrip("/")
        self.credential = credential  # returns the bearer token/key this service authenticates with
        self.timeout = timeout
        self._opener = _opener_for(self.base)
        self._cache: dict[str, Grant] = {}
        self._lock = threading.Lock()

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.credential()}"}

    def exchange(self, session_ref: str, scope: str | None = None, action_id: str | None = None) -> Grant:
        """RFC 8693 exchange of a session ref for a downstream core token. Read grants are cached briefly."""
        key = f"{session_ref}|{scope}"
        if not action_id:
            with self._lock:
                g = self._cache.get(key)
                if g and g.expires_at - 30 > time.time():
                    return g
        form = {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": session_ref,
            "subject_token_type": "urn:healthgen:params:oauth:token-type:session-ref",
            "audience": "healthgen-core",
        }
        if scope:
            form["scope"] = scope
        if action_id:
            form["action_id"] = action_id
        body = _request(self._opener, "POST", f"{self.base}/oauth2/token",
                        {**self._auth(), "Content-Type": "application/x-www-form-urlencoded"},
                        urllib.parse.urlencode(form).encode(), self.timeout)
        g = Grant(body["access_token"], time.time() + int(body.get("expires_in", 300)), _unverified_claims(body["access_token"]), body.get("action"))
        if not action_id:
            with self._lock:
                self._cache[key] = g
        return g

    def create_action(self, session_ref: str, kind: str, params: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
        return _request(self._opener, "POST", f"{self.base}/v1/actions", {**self._auth(), "Content-Type": "application/json"},
                        json.dumps({"session_ref": session_ref, "kind": kind, "params": params, "summary": summary}).encode(), self.timeout)


class CoreClient:
    def __init__(self, base_url: str, timeout: float = 10):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self._opener = _opener_for(self.base)

    def get(self, grant: Grant, path: str, **query: Any) -> Any:
        q = {k: ("true" if v is True else "false" if v is False else v) for k, v in query.items() if v is not None}
        url = f"{self.base}{path}" + (f"?{urllib.parse.urlencode(q)}" if q else "")
        return _request(self._opener, "GET", url, {"Authorization": f"Bearer {grant.token}"}, None, self.timeout)

    def post(self, grant: Grant, path: str, body: dict[str, Any]) -> Any:
        return _request(self._opener, "POST", f"{self.base}{path}",
                        {"Authorization": f"Bearer {grant.token}", "Content-Type": "application/json"}, json.dumps(body).encode(), self.timeout)


class HandoffClient:
    """Posts hand-off requests to the n8n webhook, signed with HMAC-SHA256 over the raw body."""

    def __init__(self, url: str | None, secret: str | None, timeout: float = 10):
        self.url = url
        self.secret = secret or ""
        self.timeout = timeout
        self._opener = _opener_for(url or "")

    def send(self, payload: dict[str, Any]) -> dict[str, Any]:
        import hashlib
        import hmac

        if not self.url:
            raise UpstreamError(503, "handoff_not_configured")
        raw = json.dumps(payload, separators=(",", ":")).encode()
        ts = str(int(time.time()))
        sig = hmac.new(self.secret.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
        return _request(self._opener, "POST", self.url, {"Content-Type": "application/json", "X-HealthGen-Timestamp": ts,
                                                          "X-HealthGen-Signature": f"sha256={sig}"}, raw, self.timeout) or {}
