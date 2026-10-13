"""Outbound calls of the relay: identity broker, MCP card store, Foundry (through APIM). Stdlib HTTP in threads."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

import anyio

log = logging.getLogger("healthgen.relay")


class UpstreamError(Exception):
    def __init__(self, status: int, code: str, message: str = ""):
        super().__init__(f"{code}: {message}" if message else code)
        self.status = status
        self.code = code


def _opener(url: str) -> urllib.request.OpenerDirector:
    host = urllib.parse.urlparse(url).hostname
    return urllib.request.build_opener(urllib.request.ProxyHandler({})) if host in ("localhost", "127.0.0.1") else urllib.request.build_opener()


def _call(opener: urllib.request.OpenerDirector, method: str, url: str, headers: dict[str, str], body: Any = None, timeout: float = 15) -> tuple[int, Any, dict[str, str]]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={**headers, **({"Content-Type": "application/json"} if data else {})})
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"error": raw[:200].decode(errors="replace")}
        return exc.code, payload, dict(exc.headers or {})
    except (urllib.error.URLError, TimeoutError) as exc:
        raise UpstreamError(503, "upstream_unreachable", str(getattr(exc, "reason", exc))) from exc


def _code(payload: Any, status: int) -> str:
    if isinstance(payload, dict):
        e = payload.get("error")
        if isinstance(e, dict):
            return str(e.get("code") or e.get("type") or f"http_{status}")
        if e:
            return str(e)
    return f"http_{status}"


@dataclass
class Session:
    session_ref: str
    role: str
    portal: str
    display_name: str | None
    user_context_token: str
    expires_at: float


class BrokerClient:
    def __init__(self, base_url: str, credential: Callable[[], str], timeout: float = 10):
        self.base = base_url.rstrip("/")
        self.credential = credential
        self.timeout = timeout
        self._opener = _opener(self.base)
        self._sessions: dict[tuple[str, str], Session] = {}
        self._lock = threading.Lock()

    def _req(self, method: str, path: str, body: Any = None) -> Any:
        status, payload, _ = _call(self._opener, method, self.base + path, {"Authorization": f"Bearer {self.credential()}"}, body, self.timeout)
        if status >= 400:
            raise UpstreamError(status, _code(payload, status), str((payload or {}).get("error_description", "")) if isinstance(payload, dict) else "")
        return payload

    async def resolve(self, dl_user_id: str, conversation_id: str) -> Session:
        key = (dl_user_id, conversation_id)
        with self._lock:
            s = self._sessions.get(key)
        if s and s.expires_at - 60 > time.time():
            return s
        body = await anyio.to_thread.run_sync(lambda: self._req("POST", "/v1/sessions/resolve", {"dl_user_id": dl_user_id, "conversation_id": conversation_id}))
        s = Session(body["session_ref"], body["role"], body["portal"], body.get("display_name"), body["user_context_token"], time.time() + int(body.get("expires_in", 600)))
        with self._lock:
            self._sessions[key] = s
        return s

    def forget(self, dl_user_id: str, conversation_id: str) -> None:
        with self._lock:
            self._sessions.pop((dl_user_id, conversation_id), None)

    async def get_action(self, action_id: str, session_ref: str) -> dict[str, Any]:
        q = urllib.parse.urlencode({"session_ref": session_ref})
        return await anyio.to_thread.run_sync(lambda: self._req("GET", f"/v1/actions/{urllib.parse.quote(action_id)}?{q}"))

    async def confirm_action(self, action_id: str, session_ref: str, extras: dict[str, str]) -> dict[str, Any]:
        return await anyio.to_thread.run_sync(lambda: self._req("POST", f"/v1/actions/{urllib.parse.quote(action_id)}/confirm", {"session_ref": session_ref, "extras": extras}))


class CardClient:
    def __init__(self, base_url: str, credential: Callable[[], str], timeout: float = 10):
        self.base = base_url.rstrip("/")
        self.credential = credential
        self.timeout = timeout
        self._opener = _opener(self.base)

    async def get(self, card_ref: str, session_ref: str) -> dict[str, Any] | None:
        url = f"{self.base}/internal/cards/{urllib.parse.quote(card_ref)}?{urllib.parse.urlencode({'session_ref': session_ref})}"
        status, payload, _ = await anyio.to_thread.run_sync(lambda: _call(self._opener, "GET", url, {"Authorization": f"Bearer {self.credential()}"}, None, self.timeout))
        if status == 404:
            return None
        if status >= 400:
            raise UpstreamError(status, _code(payload, status))
        return payload


@dataclass
class AgentTurn:
    text: str
    response_id: str | None
    raw_output: list[dict[str, Any]]


class FoundryClient:
    """Foundry Agent Service via the Responses API, normally through APIM (which validates X-User-Context).

    base_url is the project endpoint as exposed by APIM, e.g.
    https://apim-healthgen.azure-api.net/foundry/api/projects/healthgen  (or the project endpoint directly in dev)
    """

    def __init__(self, base_url: str, agent_name: str, credential: Callable[[], str], subscription_key: str | None = None,
                 agent_version: str | None = None, timeout: float = 120, retries: int = 2):
        self.base = base_url.rstrip("/")
        self.agent_name = agent_name
        self.agent_version = agent_version
        self.credential = credential
        self.subscription_key = subscription_key
        self.timeout = timeout
        self.retries = retries
        self._opener = _opener(self.base)

    def _headers(self, user_context: str) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self.credential()}", "X-User-Context": user_context}
        if self.subscription_key:
            h["Ocp-Apim-Subscription-Key"] = self.subscription_key
        return h

    def _post(self, path: str, body: dict[str, Any], user_context: str) -> Any:
        for attempt in range(self.retries + 1):
            status, payload, headers = _call(self._opener, "POST", f"{self.base}{path}", self._headers(user_context), body, self.timeout)
            if status in (429, 502, 503, 504) and attempt < self.retries:
                delay = min(float(headers.get("Retry-After") or headers.get("retry-after") or 2 ** attempt), 10)
                log.warning("foundry %s returned %s; retrying in %.1fs", path, status, delay)
                time.sleep(delay)
                continue
            if status >= 400:
                code = _code(payload, status)
                raise UpstreamError(status, code, "blocked by the gateway guardrail" if status == 403 else "")
            return payload
        raise UpstreamError(503, "retries_exhausted")

    async def create_conversation(self, user_context: str, metadata: dict[str, str] | None = None) -> str:
        body = await anyio.to_thread.run_sync(lambda: self._post("/openai/v1/conversations", {"metadata": metadata or {}}, user_context))
        return body["id"]

    async def run(self, conversation_id: str, text: str, user_context: str) -> AgentTurn:
        ref: dict[str, Any] = {"type": "agent_reference", "name": self.agent_name}
        if self.agent_version:
            ref["version"] = self.agent_version
        body = {"agent_reference": ref, "conversation": conversation_id, "input": [{"type": "message", "role": "user", "content": text}]}
        payload = await anyio.to_thread.run_sync(lambda: self._post("/openai/v1/responses", body, user_context))
        return AgentTurn(output_text(payload), payload.get("id"), payload.get("output") or [])


def output_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    parts: list[str] = []
    for item in payload.get("output") or []:
        if item.get("type") == "message" and item.get("role", "assistant") == "assistant":
            parts = [c.get("text", "") for c in item.get("content") or [] if c.get("type") in ("output_text", "text")]
    return "".join(parts)


def token_provider(prefix: str) -> Callable[[], str]:
    """``{prefix}_KEY`` for dev, else a managed identity token for ``{prefix}_RESOURCE``."""
    key = os.getenv(f"{prefix}_KEY")
    if key:
        return lambda: key
    resource = os.environ[f"{prefix}_RESOURCE"]
    from .msi import ManagedIdentityCredential

    cred = ManagedIdentityCredential(os.getenv("AZURE_CLIENT_ID"))
    return lambda: cred.token(resource)
