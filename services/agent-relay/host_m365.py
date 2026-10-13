"""Agent relay host on the Microsoft 365 Agents SDK (Python), behind Azure Bot Service + Direct Line.

    pip install -r requirements-host.txt
    python host_m365.py            # listens on $PORT (default 3978), POST /api/messages

Azure Bot Service delivers Direct Line activities to /api/messages with a channel JWT that
``jwt_authorization_middleware`` validates against the bot's Entra app (CONNECTIONS__SERVICE_CONNECTION__* env vars).
Everything HealthGen-specific lives in ``relay.core.RelayCore``; this file only adapts the SDK's TurnContext.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from aiohttp.web import Application, Request, Response, json_response, run_app
from microsoft_agents.activity import Activity, load_configuration_from_env
from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.aiohttp import CloudAdapter, jwt_authorization_middleware, start_agent_process
from microsoft_agents.hosting.core import AgentApplication, MemoryStorage, TurnContext, TurnState

from relay.factory import core_from_env

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("healthgen.relay.host")

SDK_CONFIG = load_configuration_from_env(os.environ)
CONNECTIONS = MsalConnectionManager(**SDK_CONFIG)
ADAPTER = CloudAdapter(connection_manager=CONNECTIONS)
AGENT_APP = AgentApplication[TurnState](storage=MemoryStorage(), adapter=ADAPTER, **SDK_CONFIG)
RELAY = core_from_env()

# Fields the SDK fills from the incoming turn's conversation reference.
_SDK_OWNED = ("from", "recipient", "conversation", "serviceUrl", "channelId")


def _incoming(context: TurnContext) -> dict[str, Any]:
    return context.activity.model_dump(mode="json", by_alias=True, exclude_none=True)


def _sender(context: TurnContext):
    async def send(out: dict[str, Any]) -> None:
        payload = {k: v for k, v in out.items() if k not in _SDK_OWNED}
        await context.send_activity(Activity.model_validate(payload))
    return send


@AGENT_APP.activity("message")
async def on_message(context: TurnContext, _state: TurnState) -> None:
    await RELAY.on_activity(_incoming(context), _sender(context))


@AGENT_APP.activity("event")
async def on_event(context: TurnContext, _state: TurnState) -> None:
    await RELAY.on_activity(_incoming(context), _sender(context))


@AGENT_APP.error
async def on_error(context: TurnContext, error: Exception) -> None:
    log.exception("unhandled relay error: %s", type(error).__name__)
    await context.send_activity("Sorry, something went wrong. Please try again.")


async def messages(req: Request) -> Response:
    return await start_agent_process(req, req.app["agent_app"], req.app["adapter"])


async def healthz(_req: Request) -> Response:
    return json_response({"status": "ok", "service": "agent-relay"})


def create_app() -> Application:
    app = Application(middlewares=[jwt_authorization_middleware])
    app.router.add_post("/api/messages", messages)
    app.router.add_get("/healthz", healthz)
    app["agent_configuration"] = CONNECTIONS.get_default_connection_configuration()
    app["agent_app"] = AGENT_APP
    app["adapter"] = AGENT_APP.adapter
    return app


if __name__ == "__main__":
    run_app(create_app(), host="0.0.0.0", port=int(os.getenv("PORT", "3978")))
