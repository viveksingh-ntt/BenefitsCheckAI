"""Identity broker with the AG-UI chat-token endpoint added.

    uvicorn app.main_agui:app --port 8102

Same app as ``app.main`` (every existing route, unchanged) plus ``POST /v1/agui/token`` from ``app.agui``.
``DIRECTLINE_SECRET`` becomes optional: without it the Direct Line routes answer 503 and only AG-UI is offered.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from starlette.applications import Starlette

from .agui import agui_routes
from .auth import PortalAssertionVerifier, ServiceAuthenticator
from .directline import DirectLineClient, DirectLineError
from .main import Settings
from .main import create_app as create_base_app
from .signer import Signer, signer_from_env
from .store import SqliteStore


class NoDirectLine:
    """Stands in for DirectLineClient when the broker serves AG-UI only."""

    def generate_token(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise DirectLineError(503, "Direct Line is not configured on this broker")

    def reconnect(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise DirectLineError(503, "Direct Line is not configured on this broker")


def create_app(
    settings: Settings | None = None,
    signer: Signer | None = None,
    store: SqliteStore | None = None,
    directline: Any = None,
    portal: PortalAssertionVerifier | None = None,
    services: ServiceAuthenticator | None = None,
) -> Starlette:
    settings = settings or Settings.from_env()
    signer = signer or signer_from_env()
    store = store or SqliteStore(os.getenv("BROKER_DB_PATH", ":memory:"))
    portal = portal or PortalAssertionVerifier.from_env()
    if directline is None:
        secret = os.getenv("DIRECTLINE_SECRET")
        directline = DirectLineClient(secret, os.getenv("DIRECTLINE_ENDPOINT", "https://directline.botframework.com")) if secret else NoDirectLine()
    app = create_base_app(settings=settings, signer=signer, store=store, directline=directline, portal=portal, services=services)
    app.router.routes.extend(agui_routes(settings, signer, store, portal))
    return app


class _Lazy:
    def __init__(self) -> None:
        self._app: Starlette | None = None

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if self._app is None:
            logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
            self._app = create_app()
        await self._app(scope, receive, send)


app = _Lazy()
