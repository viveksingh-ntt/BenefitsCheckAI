"""The reply envelope agents return, and output hygiene (PHI masking) applied before anything reaches the widget.

Agents answer with one JSON object (see agents/README.md):

    {"reply": "markdown", "card_ref": "crd_…", "follow_up": "…", "result_chip": "…", "breadcrumb": "…",
     "suggestions": [{"title": "Find dermatologists", "recommended": true}],
     "handoff": {"ticket_ref": "HO-1001", "reason": "user_request"}, "navigate": {"route": "/plan/benefits"}}

Only ``reply`` is required. Anything that is not valid JSON is treated as a plain ``reply``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator


class Suggestion(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    recommended: bool = False


class Handoff(BaseModel):
    ticket_ref: str | None = Field(default=None, max_length=40)
    reason: str = Field(default="user_request", max_length=40)


class Navigate(BaseModel):
    route: str = Field(max_length=200)


class Envelope(BaseModel):
    model_config = {"extra": "ignore"}

    reply: str = Field(min_length=1, max_length=4000)
    card_ref: str | None = Field(default=None, pattern=r"^crd_[0-9a-f]{16}$")
    follow_up: str | None = Field(default=None, max_length=600)
    result_chip: str | None = Field(default=None, max_length=80)
    breadcrumb: str | None = Field(default=None, max_length=60)
    suggestions: list[Suggestion] = Field(default_factory=list, max_length=6)
    handoff: Handoff | None = None
    navigate: Navigate | None = None

    @field_validator("card_ref", "follow_up", "result_chip", "breadcrumb", mode="before")
    @classmethod
    def blank_is_none(cls, v: Any) -> Any:
        return None if v in ("", "null") else v

    @field_validator("suggestions", mode="before")
    @classmethod
    def strings_are_titles(cls, v: Any) -> Any:
        if isinstance(v, list):
            return [{"title": s} if isinstance(s, str) else s for s in v][:6]
        return v


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


def _json_candidate(text: str) -> Any:
    t = text.strip()
    m = _FENCE.match(t)
    if m:
        t = m.group(1)
    if not t.startswith("{"):
        start, end = t.find("{"), t.rfind("}")
        if start < 0 or end <= start:
            return None
        t = t[start:end + 1]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return None


def parse_envelope(text: str) -> tuple[Envelope, bool]:
    """Returns the envelope and whether the agent followed the contract."""
    raw = _json_candidate(text or "")
    if isinstance(raw, dict):
        try:
            return Envelope.model_validate(raw), True
        except ValidationError:
            if isinstance(raw.get("reply"), str) and raw["reply"].strip():
                return Envelope(reply=raw["reply"][:4000]), False
    plain = (text or "").strip() or "Sorry, I couldn't complete that. Please try again."
    return Envelope(reply=plain[:4000]), False


# ------------------------------------------------------------------ masking

_SSN = re.compile(r"\b(\d{3})[- ]?(\d{2})[- ]?(\d{4})\b")
_LONG_DIGITS = re.compile(r"\b\d{9,}\b")
_INTERNAL_REF = re.compile(r"\b(?:ses|act|crd|mbr|dl)_[0-9a-zA-Z]{4,}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


def mask_outbound(text: str) -> str:
    """Hygiene for text going to the widget: no internal refs, SSN-shaped or long ID numbers (last 4 kept)."""
    if not text:
        return text
    text = _INTERNAL_REF.sub("[ref]", text)
    text = _SSN.sub(lambda m: f"***-**-{m.group(3)}", text)
    text = _LONG_DIGITS.sub(lambda m: "•" * 4 + m.group(0)[-4:], text)
    return text


def redact_for_log(text: str | None, keep: int = 0) -> str:
    """Logs never get conversation content: only its size, plus an optional short prefix in dev."""
    if not text:
        return "<empty>"
    prefix = mask_outbound(_EMAIL.sub("[email]", text[:keep])) if keep else ""
    return f"<{len(text)} chars>{(' ' + prefix) if prefix else ''}"
