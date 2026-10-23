"""AG-UI protocol adapter for the relay core.

The relay core (``core.py``) speaks Bot Framework activity dicts. This module translates in both directions so the
same core, with all its rules, serves an AG-UI client:

    RunAgentInput ──to_activities()──▶ activity dicts ──RelayCore.on_activity()──▶ activity dicts ──EventMapper──▶ AG-UI events

Event and field names follow the AG-UI spec (https://docs.ag-ui.com/concepts/events): wire ``type`` values are
upper snake case (``RUN_STARTED``), fields camelCase. Human confirmation uses AG-UI interrupts: a review card ends
the run with ``outcome: {type: "interrupt"}`` whose interrupt ``id`` is the identity broker's ``act_…`` id, and the
client answers with ``resume`` on the next run.

Client-sent ``messages`` history, ``state`` and ``tools`` are ignored on purpose: history lives in the Foundry
conversation, and the browser must not be able to plant earlier turns or tools.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

ADAPTIVE_CARD = "application/vnd.microsoft.card.adaptive"
REVIEW_VERBS = {"appointment.confirm": "Nothing is booked until you confirm.", "referral.submit": "Nothing is sent until you submit."}
DECLINED = {"appointment.confirm": "Okay, nothing was booked. What would you like to do instead?",
            "referral.submit": "Okay, the referral was not submitted. What would you like to change?"}
INTERRUPT_TTL = 15 * 60  # the broker's pending-action lifetime
MAX_TRANSCRIPT = 200
ACTION_VERB = re.compile(r"^[a-z][a-z0-9_.-]{1,60}$")
ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class InputError(Exception):
    """A RunAgentInput the relay refuses; becomes RUN_ERROR with this code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------- thread state


@dataclass
class ThreadState:
    open_interrupts: dict[str, dict[str, Any]] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    touched: float = field(default_factory=time.time)

    def remember(self, message: dict[str, Any]) -> None:
        self.messages.append(message)
        del self.messages[:-MAX_TRANSCRIPT]


class ThreadStore:
    """In-memory, per replica. For several replicas, back this with Redis behind the same two methods."""

    def __init__(self, ttl: int = 12 * 3600):
        self.ttl = ttl
        self._threads: dict[str, ThreadState] = {}
        self._lock = threading.Lock()

    def get(self, thread_id: str) -> ThreadState:
        now = time.time()
        with self._lock:
            for k in [k for k, v in self._threads.items() if v.touched < now - self.ttl]:
                del self._threads[k]
            st = self._threads.setdefault(thread_id, ThreadState())
            st.touched = now
            return st


# --------------------------------------------------------------------- input


def _base(kind: str, user_id: str, thread_id: str) -> dict[str, Any]:
    return {"type": kind, "id": new_id("in"), "from": {"id": user_id, "role": "user"}, "conversation": {"id": thread_id},
            "channelId": "agui", "timestamp": iso(time.time())}


def to_activities(run: dict[str, Any], user_id: str, thread: ThreadState) -> tuple[list[dict[str, Any]], str | None]:
    """Returns (activities for the relay core, a reply to send without calling the core)."""
    thread_id = str(run.get("threadId"))
    props = run.get("forwardedProps") if isinstance(run.get("forwardedProps"), dict) else {}
    activities: list[dict[str, Any]] = []

    # Page hints from `context` (hints only; identity never comes from here).
    ctx: dict[str, Any] = {}
    for item in run.get("context") or []:
        if isinstance(item, dict) and item.get("description") in ("page", "locale") and isinstance(item.get("value"), str):
            ctx[item["description"]] = item["value"][:200]
    if ctx:
        ev = _base("event", user_id, thread_id)
        ev.update({"name": "context", "value": {"locale": ctx.get("locale"), "page": {"route": ctx.get("page")}}})
        activities.append(ev)

    # 1. Answers to open interrupts (every open interrupt must be addressed).
    resume = [r for r in run.get("resume") or [] if isinstance(r, dict)]
    confirm: dict[str, Any] | None = None
    declined_verb: str | None = None
    if thread.open_interrupts or resume:
        answered = {str(r.get("interruptId")) for r in resume}
        missing = set(thread.open_interrupts) - answered
        if missing:
            raise InputError("interrupt_pending", "Answer or cancel the open confirmation before sending new input.")
        for r in resume:
            iid = str(r.get("interruptId"))
            intr = thread.open_interrupts.get(iid)
            if not intr:
                raise InputError("unknown_interrupt", "That confirmation is not open in this thread.")
            payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
            if r.get("status") == "resolved" and payload.get("approved") is True and confirm is None:
                note = payload.get("note")
                data: dict[str, Any] = {"actionId": iid}
                if intr["verb"] == "appointment.confirm" and isinstance(note, str):
                    data["officeNote"] = note[:300]
                if intr["verb"] == "referral.submit":
                    data["attest"] = "true" if payload.get("attest") is True else "false"
                    if isinstance(note, str):
                        data["clinicalNote"] = note[:500]
                confirm = {"verb": intr["verb"], "data": data}
            elif r.get("status") in ("resolved", "cancelled"):
                declined_verb = declined_verb or (intr["verb"] if r.get("status") == "resolved" else None)
            else:
                raise InputError("invalid_resume", "Resume status must be resolved or cancelled.")
        thread.open_interrupts.clear()

    if confirm:
        act = _base("message", user_id, thread_id)
        act["value"] = {"action": {"type": "Action.Execute", **confirm}}
        activities.append(act)
        return activities, None

    # 2. Card buttons and portal journeys.
    action = props.get("action") if isinstance(props.get("action"), dict) else None
    journey = props.get("journey") if isinstance(props.get("journey"), dict) else None
    if action and isinstance(action.get("verb"), str) and ACTION_VERB.match(action["verb"]):
        if action["verb"] == "handoff":
            ev = _base("event", user_id, thread_id)
            ev.update({"name": "handoffRequest", "value": {}})
            activities.append(ev)
        else:
            act = _base("message", user_id, thread_id)
            data = action.get("data") if isinstance(action.get("data"), dict) else {}
            act["value"] = {"action": {"type": "Action.Execute", "verb": action["verb"], "data": data}}
            activities.append(act)
        return activities, None
    if journey and isinstance(journey.get("id"), str):
        ev = _base("event", user_id, thread_id)
        ev.update({"name": "startJourney", "value": {"journeyId": journey["id"][:60], "params": journey.get("params") if isinstance(journey.get("params"), dict) else {}}})
        activities.append(ev)
        return activities, None

    # 3. Typed text: only the newest user message counts.
    text = None
    for m in reversed(run.get("messages") or []):
        if isinstance(m, dict) and m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):  # multimodal parts: keep the text parts only
                text = " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
            break
    if text and text.strip():
        act = _base("message", user_id, thread_id)
        act["text"] = text
        activities.append(act)
        thread.remember({"id": act["id"], "role": "user", "content": text[:2000]})
        return activities, None

    if declined_verb:
        return activities, DECLINED[declined_verb]
    return activities, None


# --------------------------------------------------------------------- output


def _review_action(card: dict[str, Any]) -> tuple[str, str] | None:
    for a in card.get("actions") or []:
        if isinstance(a, dict) and a.get("verb") in REVIEW_VERBS:
            aid = (a.get("data") or {}).get("actionId")
            if isinstance(aid, str) and aid.startswith("act_"):
                return a["verb"], aid
    return None


class EventMapper:
    """Turns the relay core's outgoing activities into AG-UI events for one run."""

    def __init__(self, thread_id: str, run_id: str, thread: ThreadState):
        self.thread_id = thread_id
        self.run_id = run_id
        self.thread = thread
        self.step: str | None = None
        self.interrupts: list[dict[str, Any]] = []

    def start(self) -> list[dict[str, Any]]:
        return [{"type": "RUN_STARTED", "threadId": self.thread_id, "runId": self.run_id}]

    def _close_step(self) -> list[dict[str, Any]]:
        if self.step is None:
            return []
        ev = [{"type": "STEP_FINISHED", "stepName": self.step}]
        self.step = None
        return ev

    def text(self, text: str) -> list[dict[str, Any]]:
        mid = new_id("msg")
        self.thread.remember({"id": mid, "role": "assistant", "content": text})
        return [{"type": "TEXT_MESSAGE_START", "messageId": mid, "role": "assistant"},
                {"type": "TEXT_MESSAGE_CONTENT", "messageId": mid, "delta": text},
                {"type": "TEXT_MESSAGE_END", "messageId": mid}]

    def _activity(self, activity_type: str, content: dict[str, Any]) -> dict[str, Any]:
        mid = new_id("act" if activity_type == "adaptive_card" else "ui")
        self.thread.remember({"id": mid, "role": "activity", "activityType": activity_type, "content": content})
        return {"type": "ACTIVITY_SNAPSHOT", "messageId": mid, "activityType": activity_type, "content": content, "replace": True}

    def map(self, a: dict[str, Any]) -> list[dict[str, Any]]:
        kind = a.get("type")
        if kind == "typing":
            out = self._close_step()
            self.step = (a.get("text") or "Working…")[:120]
            return out + [{"type": "STEP_STARTED", "stepName": self.step}]
        if kind == "event":
            if a.get("name") in ("navigate", "handoff"):
                return [{"type": "CUSTOM", "name": a["name"], "value": a.get("value")}]
            return []
        if kind != "message":
            return []
        out = self._close_step()
        cd = a.get("channelData") or {}
        if a.get("text"):
            out += self.text(a["text"])
            if cd.get("resultChip"):
                out.append(self._activity("result_chip", {"text": cd["resultChip"].get("text"), "state": cd["resultChip"].get("state", "done")}))
        if cd.get("breadcrumb") and self.thread.state.get("breadcrumb") != cd["breadcrumb"]:
            self.thread.state["breadcrumb"] = cd["breadcrumb"]
            out.append({"type": "STATE_DELTA", "delta": [{"op": "add", "path": "/breadcrumb", "value": cd["breadcrumb"]}]})
        for att in a.get("attachments") or []:
            if att.get("contentType") != ADAPTIVE_CARD:
                continue
            card = att.get("content") or {}
            out.append(self._activity("adaptive_card", {"templateId": cd.get("templateId"), "card": card}))
            review = _review_action(card)
            if review:
                verb, aid = review
                self.interrupts.append({
                    "id": aid,
                    "reason": "confirmation",
                    "message": REVIEW_VERBS[verb],
                    "responseSchema": {
                        "type": "object",
                        "required": ["approved"],
                        "properties": {"approved": {"type": "boolean"}, "note": {"type": "string", "maxLength": 500},
                                       **({"attest": {"type": "boolean"}} if verb == "referral.submit" else {})},
                    },
                    "expiresAt": iso(time.time() + INTERRUPT_TTL),
                    "metadata": {"verb": verb, "templateId": cd.get("templateId")},
                })
        actions = (a.get("suggestedActions") or {}).get("actions") or []
        if actions:
            chips = [{"title": s.get("title"), "value": s.get("value"), "recommended": bool((s.get("channelData") or {}).get("recommended"))} for s in actions]
            out.append(self._activity("suggestions", {"actions": chips}))
        return out

    def finish(self) -> list[dict[str, Any]]:
        out = self._close_step()
        if self.interrupts:
            for i in self.interrupts:
                self.thread.open_interrupts[i["id"]] = {"verb": i["metadata"]["verb"], **i}
            outcome = {"type": "interrupt", "interrupts": self.interrupts}
        else:
            outcome = {"type": "success"}
        return out + [{"type": "RUN_FINISHED", "threadId": self.thread_id, "runId": self.run_id, "outcome": outcome}]

    def error(self, code: str, message: str) -> list[dict[str, Any]]:
        return self._close_step() + [{"type": "RUN_ERROR", "code": code, "message": message}]


def sse(event: dict[str, Any]) -> bytes:
    event.setdefault("timestamp", int(time.time() * 1000))
    return f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n".encode()


def valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(ID.match(value))
