"""Builds the relay core from environment variables (shared by the M365 host and the dev server)."""

from __future__ import annotations

import os
from pathlib import Path

from .clients import BrokerClient, CardClient, FoundryClient, token_provider
from .core import RelayConfig, RelayCore, TemplateStore

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


def core_from_env() -> RelayCore:
    return RelayCore(
        broker=BrokerClient(os.environ["BROKER_URL"], token_provider("BROKER")),
        cards=CardClient(os.environ["MCP_URL"], token_provider("MCP_CARDS")),
        foundry=FoundryClient(
            base_url=os.environ["FOUNDRY_BASE_URL"],
            agent_name=os.getenv("FOUNDRY_AGENT_NAME", "healthgen-triage"),
            agent_version=os.getenv("FOUNDRY_AGENT_VERSION") or None,
            credential=token_provider("FOUNDRY"),
            subscription_key=os.getenv("APIM_SUBSCRIPTION_KEY") or None,
            timeout=float(os.getenv("FOUNDRY_TIMEOUT_SECONDS", "120")),
        ),
        templates=TemplateStore(os.getenv("TEMPLATES_DIR", str(TEMPLATES))),
        config=RelayConfig(bot_name=os.getenv("BOT_DISPLAY_NAME", "Care assistant")),
    )
