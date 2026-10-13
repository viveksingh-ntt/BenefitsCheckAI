"""Relay core: Direct Line activity in → Foundry agent turn → Direct Line activities out.

Transport-agnostic. The M365 Agents SDK host (``host_m365.py``) and the local Direct Line emulator
(``dev_server.py``) both call ``RelayCore.on_activity(activity, send)`` with Bot Framework activity dicts.

What the relay guarantees, whatever the model does:
* identity comes from the broker binding of the Direct Line user, never from client-sent context;
* card actions are validated (verb allowlist, ref patterns) and free-text card inputs never reach the model;
* Confirm/Submit in a review card is the only way a write is unlocked (broker confirmation);
* cards are rendered from the MCP card store with allow-listed templates; reply text is masked.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import anyio

from .clients import AgentTurn, BrokerClient, CardClient, FoundryClient, Session, UpstreamError
from .envelope import Envelope, mask_outbound, parse_envelope, redact_for_log
from .templating import expand_template

log = logging.getLogger("healthgen.relay")

ADAPTIVE_CARD = "application/vnd.microsoft.card.adaptive"
Send = Callable[[dict[str, Any]], Awaitable[None]]

# Card inputs/data the model may see, with the shape each value must have.
SAFE_DATA = {
    "serviceRef": ("service_ref", re.compile(r"^svc_[a-z0-9_]{1,60}$")),
    "providerRef": ("provider_ref", re.compile(r"^prv_[a-z0-9_]{1,40}$")),
    "slotRef": ("slot_ref", re.compile(r"^slt_[a-z0-9_]{1,60}$")),
    "zip": ("zip", re.compile(r"^\d{5}$")),
    "distance": ("radius_miles", re.compile(r"^(1|5|10|25)$")),
    "planRef": ("plan_ref", re.compile(r"^pln_[a-z0-9_]{1,60}$")),
    "category": ("category", re.compile(r"^[a-z][a-z -]{1,40}$")),
    "query": ("query", re.compile(r"^[\w ,.'’-]{2,120}$")),
}

AGENT_VERBS = {
    "service.find": ("Find this service", "Matching services to your plan…"),
    "providers.search": ("Find doctors", "Searching in-network doctors…"),
    "providers.back": ("Change doctor", "Searching in-network doctors…"),
    "appointment.availability": ("Check availability", "Checking availability…"),
    "appointment.review": ("Review booking", "Preparing your request…"),
    "referral.review": ("Review referral", "Preparing the referral…"),
}

CONFIRM_VERBS = {
    "appointment.confirm": {"kind": "appointment.request", "tool": "submit_appointment_request", "extras": {"officeNote": "note"},
                            "progress": "Booking your appointment…"},
    "referral.submit": {"kind": "referral.submit", "tool": "submit_referral", "extras": {"clinicalNote": "reason"},
                        "progress": "Submitting the referral…", "attest": True},
}

NAVIGATE_VERBS = {
    "plan.details": ("/plan/benefits", "Opening your plan benefits in the portal."),
    "service.details": ("/care/services/{serviceRef}", "Opening the service details page."),
    "provider.view": ("/providers/{providerRef}", "Opening the doctor's profile."),
}

JOURNEYS = {
    "benefit-check": "check what their plan covers",
    "service-search": "find a covered service",
    "doctor-search": "find an in-network doctor",
}

ROUTE = re.compile(r"^/[A-Za-z0-9/_\-]{0,150}$")
ACTION_ID = re.compile(r"^act_[0-9a-f]{32}$")


class TemplateStore:
    def __init__(self, directory: str | Path):
        self.templates: dict[str, Any] = {}
        for path in sorted(Path(directory).glob("*.json")):
            self.templates[path.stem] = json.loads(path.read_text(encoding="utf-8"))

    def render(self, template_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        template = self.templates.get(template_id)
        return expand_template(template, data) if template is not None else None


@dataclass
class ConversationState:
    foundry_conversation_id: str | None = None
    page_route: str | None = None
    locale: str = "en-US"
    turns: deque = field(default_factory=lambda: deque(maxlen=30))
    lock: anyio.Lock = field(default_factory=anyio.Lock)
    touched: float = field(default_factory=time.time)


@dataclass
class RelayConfig:
    bot_id: str = "care-assistant"
    bot_name: str = "Care assistant"
    max_text_chars: int = 2000
    max_turns_per_minute: int = 20
    conversation_ttl: int = 4 * 3600


@dataclass
class Plan:
    """What to send for one turn."""
    progress: str | None = None
    agent_input: str | None = None
    direct: Envelope | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


class RelayCore:
    def __init__(self, broker: BrokerClient, cards: CardClient, foundry: FoundryClient, templates: TemplateStore, config: RelayConfig | None = None):
        self.broker = broker
        self.cards = cards
        self.foundry = foundry
        self.templates = templates
        self.config = config or RelayConfig()
        self.states: dict[str, ConversationState] = defaultdict(ConversationState)

    # ------------------------------------------------------------------ entry

    async def on_activity(self, activity: dict[str, Any], send: Send) -> None:
        conversation_id = (activity.get("conversation") or {}).get("id") or ""
        user_id = (activity.get("from") or {}).get("id") or ""
        kind = activity.get("type")
        if kind not in ("message", "event") or not conversation_id or not user_id:
            return
        self._gc()
        state = self.states[conversation_id]
        state.touched = time.time()
        async with state.lock:  # one turn at a time per conversation, in arrival order
            try:
                session = await self.broker.resolve(user_id, conversation_id)
            except UpstreamError as exc:
                log.info("session not resolved for conversation %s: %s", conversation_id[:8], exc.code)
                await send(self._message(activity, "Your session has ended. Refresh the page to start a new conversation."))
                return
            if not self._within_rate(state):
                await send(self._message(activity, "You're sending messages quickly. Please wait a moment and try again."))
                return
            plan = await self._plan(activity, session, state)
            if plan is None:
                return
            await self._execute(plan, activity, session, state, send)

    # -------------------------------------------------------------- planning

    async def _plan(self, activity: dict[str, Any], session: Session, state: ConversationState) -> Plan | None:
        value = activity.get("value") if isinstance(activity.get("value"), dict) else {}
        if activity["type"] == "event":
            return self._plan_event(activity.get("name") or "", value, state)
        action = value.get("action") if isinstance(value.get("action"), dict) else None
        if action and action.get("verb"):
            return await self._plan_card_action(str(action["verb"]), action.get("data") or {}, session)
        if activity.get("attachments"):
            return Plan(direct=Envelope(reply="I can't open files in this chat yet. Please describe what you need instead."))
        text = (activity.get("text") or "").strip()
        if not text:
            return None
        if len(text) > self.config.max_text_chars:
            return Plan(direct=Envelope(reply=f"That message is too long. Please keep it under {self.config.max_text_chars} characters."))
        params = self._safe(value.get("params") or {})
        return Plan(progress="Checking…", agent_input=text + (f"\n\n(Selected in the page: {params})" if params else ""))

    def _plan_event(self, name: str, value: dict[str, Any], state: ConversationState) -> Plan | None:
        if name == "context":
            page = value.get("page") if isinstance(value.get("page"), dict) else {}
            route = page.get("route")
            state.page_route = route if isinstance(route, str) and ROUTE.match(route) else None
            if isinstance(value.get("locale"), str) and re.match(r"^[a-z]{2}(-[A-Z]{2})?$", value["locale"]):
                state.locale = value["locale"]
            return None  # member/provider refs in client context are display hints only; identity comes from the broker
        if name == "startJourney":
            journey = str(value.get("journeyId") or "")
            goal = JOURNEYS.get(journey)
            if not goal:
                return Plan(direct=Envelope(reply="How can I help with your plan or care today?"))
            params = self._safe(value.get("params") or {})
            return Plan(progress="Checking your plan…", agent_input=f"The user opened the assistant from the portal to {goal}." + (f" Details from the page: {params}." if params else "") + " Start that task.")
        if name == "handoffRequest":
            return Plan(progress="Connecting you with a care specialist…", agent_input="The user pressed 'Talk to a person'. Hand the conversation to a human care specialist now.")
        return None

    async def _plan_card_action(self, verb: str, data: dict[str, Any], session: Session) -> Plan:
        if verb in NAVIGATE_VERBS:
            template, message = NAVIGATE_VERBS[verb]
            try:
                route = template.format(**{k: v for k, v in data.items() if k in SAFE_DATA and SAFE_DATA[k][1].match(str(v))})
            except KeyError:
                return Plan(direct=Envelope(reply="Select an option in the card first."))
            return Plan(direct=Envelope(reply=message, navigate={"route": route}))
        if verb in CONFIRM_VERBS:
            return await self._plan_confirm(verb, data, session)
        if verb in AGENT_VERBS:
            label, progress = AGENT_VERBS[verb]
            safe = self._safe(data)
            return Plan(progress=progress, agent_input=f"The user pressed “{label}” ({verb}) in the card" + (f" with {safe}." if safe else "."))
        log.info("unknown card verb %s", verb[:40])
        return Plan(direct=Envelope(reply="That option isn't available any more. What would you like to do?"))

    async def _plan_confirm(self, verb: str, data: dict[str, Any], session: Session) -> Plan:
        spec = CONFIRM_VERBS[verb]
        action_id = str(data.get("actionId") or "")
        if not ACTION_ID.match(action_id):
            return Plan(direct=Envelope(reply="This request can't be confirmed. Please review it again."))
        if spec.get("attest") and str(data.get("attest")).lower() != "true":
            return Plan(direct=Envelope(reply="Please confirm medical necessity in the card before submitting."))
        try:
            action = await self.broker.get_action(action_id, session.session_ref)
            if action.get("kind") != spec["kind"] or action.get("status") != "pending" or action.get("expired"):
                return Plan(direct=Envelope(reply="This request was already handled or has expired. Ask me to prepare it again.", suggestions=[]))
            extras = {target: str(data[src])[:300] for src, target in spec["extras"].items() if data.get(src)}
            await self.broker.confirm_action(action_id, session.session_ref, extras)
        except UpstreamError as exc:
            log.info("confirm %s failed: %s", action_id[:12], exc.code)
            return Plan(direct=Envelope(reply="This request was already handled or has expired. Ask me to prepare it again."))
        log.info("action %s confirmed by the user", action_id[:12])
        return Plan(progress=spec["progress"], agent_input=f"The user confirmed request {action_id} in the review card. Call {spec['tool']} with action_id {action_id} now and report the result.")

    @staticmethod
    def _safe(data: dict[str, Any]) -> str:
        parts = []
        for key, (name, pattern) in SAFE_DATA.items():
            v = data.get(key)
            if v is not None and pattern.match(str(v)):
                parts.append(f"{name}={v}")
        return ", ".join(parts)

    # ------------------------------------------------------------- execution

    async def _execute(self, plan: Plan, activity: dict[str, Any], session: Session, state: ConversationState, send: Send) -> None:
        if plan.direct is not None:
            await self._emit(plan.direct, None, activity, session, send)
            return
        if plan.progress:
            await send(self._typing(activity, plan.progress))
        envelope, card = await self._ask_agent(plan.agent_input or "", session, state)
        await self._emit(envelope, card, activity, session, send)

    def _preamble(self, session: Session, state: ConversationState) -> str:
        lines = ["[turn-context]", f"session_ref: {session.session_ref}", f"portal: {session.portal}", f"locale: {state.locale}"]
        if state.page_route:
            lines.append(f"page: {state.page_route}")
        lines.append("[/turn-context]")
        return "\n".join(lines)

    async def _ask_agent(self, text: str, session: Session, state: ConversationState) -> tuple[Envelope, dict[str, Any] | None]:
        started = time.time()
        try:
            if not state.foundry_conversation_id:
                state.foundry_conversation_id = await self.foundry.create_conversation(session.user_context_token, {"portal": session.portal})
            turn = await self.foundry.run(state.foundry_conversation_id, f"{self._preamble(session, state)}\n\n{text}", session.user_context_token)
        except UpstreamError as exc:
            log.warning("agent turn failed: %s (%s)", exc.code, exc.status)
            if exc.status == 403:
                return Envelope(reply="I can't help with that here. I can help with benefits, finding care and appointments.",
                                suggestions=[{"title": "Check benefits"}, {"title": "Find a doctor"}]), None
            if exc.status == 404 and "conversation" in exc.code:
                state.foundry_conversation_id = None
            return Envelope(reply="Sorry, something went wrong on my side. Please try again, or I can connect you with a care specialist.",
                            suggestions=[{"title": "Try again"}, {"title": "Talk to a person"}],
                            result_chip="Assistant unavailable"), None
        envelope, ok = parse_envelope(turn.text)
        log.info("agent turn %.1fs envelope=%s reply=%s", time.time() - started, "ok" if ok else "fallback", redact_for_log(envelope.reply))
        card_ref = envelope.card_ref or last_card_ref(turn)
        card = None
        if card_ref:
            try:
                stored = await self.cards.get(card_ref, session.session_ref)
            except UpstreamError as exc:
                log.warning("card fetch failed: %s", exc.code)
                stored = None
            if stored and stored.get("template_id") in self.templates.templates:
                card = {"template_id": stored["template_id"], "content": self.templates.render(stored["template_id"], stored.get("data") or {})}
            elif card_ref:
                log.info("card %s not available (unknown, foreign session or template)", card_ref[:8])
        return envelope, card

    async def _emit(self, env: Envelope, card: dict[str, Any] | None, activity: dict[str, Any], session: Session, send: Send) -> None:
        suggestions = [{"type": "imBack", "title": mask_outbound(s.title), "value": mask_outbound(s.title),
                        **({"channelData": {"recommended": True}} if s.recommended else {})} for s in env.suggestions[:4]]
        if env.navigate and ROUTE.match(env.navigate.route):
            await send(self._event(activity, "navigate", {"route": env.navigate.route}))
        if env.handoff:
            await send(self._event(activity, "handoff", {"reason": env.handoff.reason, "ticketRef": env.handoff.ticket_ref}))
        has_more = bool(card or env.follow_up)
        lead = self._message(activity, mask_outbound(env.reply))
        cd: dict[str, Any] = {}
        if env.result_chip:
            cd["resultChip"] = {"text": mask_outbound(env.result_chip), "state": "done"}
        if env.breadcrumb:
            cd["breadcrumb"] = env.breadcrumb
        if cd:
            lead["channelData"] = cd
        if suggestions and not has_more:
            lead["suggestedActions"] = {"actions": suggestions}
        await send(lead)
        if card:
            msg = self._base(activity, "message")
            msg["attachments"] = [{"contentType": ADAPTIVE_CARD, "content": card["content"]}]
            msg["channelData"] = {"templateId": card["template_id"], **({"breadcrumb": env.breadcrumb} if env.breadcrumb else {})}
            if suggestions and not env.follow_up:
                msg["suggestedActions"] = {"actions": suggestions}
            await send(msg)
        if env.follow_up:
            follow = self._message(activity, mask_outbound(env.follow_up))
            if suggestions:
                follow["suggestedActions"] = {"actions": suggestions}
            await send(follow)

    # --------------------------------------------------------------- helpers

    def _base(self, activity: dict[str, Any], kind: str) -> dict[str, Any]:
        return {
            "type": kind,
            "from": {"id": self.config.bot_id, "name": self.config.bot_name, "role": "bot"},
            "conversation": {"id": (activity.get("conversation") or {}).get("id")},
            "replyToId": activity.get("id"),
        }

    def _message(self, activity: dict[str, Any], text: str) -> dict[str, Any]:
        return {**self._base(activity, "message"), "text": text, "textFormat": "markdown"}

    def _typing(self, activity: dict[str, Any], text: str) -> dict[str, Any]:
        return {**self._base(activity, "typing"), "text": text, "entities": [{"type": "streaminfo", "streamType": "informative", "streamSequence": 1}]}

    def _event(self, activity: dict[str, Any], name: str, value: Any) -> dict[str, Any]:
        return {**self._base(activity, "event"), "name": name, "value": value}

    def _within_rate(self, state: ConversationState) -> bool:
        now = time.time()
        while state.turns and now - state.turns[0] > 60:
            state.turns.popleft()
        if len(state.turns) >= self.config.max_turns_per_minute:
            return False
        state.turns.append(now)
        return True

    def _gc(self) -> None:
        cutoff = time.time() - self.config.conversation_ttl
        for cid in [c for c, s in self.states.items() if s.touched < cutoff and not s.lock.locked()]:
            self.states.pop(cid, None)


def last_card_ref(turn: AgentTurn) -> str | None:
    """Fallback when the agent forgot card_ref: the newest card_ref in MCP tool outputs of this response."""
    found = None
    for item in turn.raw_output:
        if item.get("type") != "mcp_call" or not item.get("output"):
            continue
        try:
            out = json.loads(item["output"]) if isinstance(item["output"], str) else item["output"]
        except json.JSONDecodeError:
            continue
        if isinstance(out, dict) and isinstance(out.get("card_ref"), str):
            found = out["card_ref"]
    return found
