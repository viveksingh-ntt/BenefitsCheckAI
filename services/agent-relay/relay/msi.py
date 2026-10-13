"""Managed identity access tokens (Container Apps identity endpoint, falling back to IMDS). Stdlib only."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request


class ManagedIdentityCredential:
    """Access tokens from the Container Apps / App Service identity endpoint, falling back to IMDS."""

    def __init__(self, client_id: str | None = None):
        self.client_id = client_id
        self._cache: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()
        self._opener = urllib.request.build_opener()

    def token(self, resource: str) -> str:
        with self._lock:
            cached = self._cache.get(resource)
            if cached and cached[1] - 300 > time.time():
                return cached[0]
        endpoint, header = os.getenv("IDENTITY_ENDPOINT"), os.getenv("IDENTITY_HEADER")
        params = {"resource": resource}
        if self.client_id:
            params["client_id"] = self.client_id
        if endpoint and header:
            params["api-version"] = "2019-08-01"
            req = urllib.request.Request(f"{endpoint}?{urllib.parse.urlencode(params)}", headers={"X-IDENTITY-HEADER": header})
        else:
            params["api-version"] = "2018-02-01"
            req = urllib.request.Request(
                f"http://169.254.169.254/metadata/identity/oauth2/token?{urllib.parse.urlencode(params)}", headers={"Metadata": "true"}
            )
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10) as resp:
            body = json.loads(resp.read())
        expires_on = float(body.get("expires_on") or time.time() + 3000)
        with self._lock:
            self._cache[resource] = (body["access_token"], expires_on)
        return body["access_token"]
