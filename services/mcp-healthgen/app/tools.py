"""MCP tools of the HealthGen data spoke.

Every tool takes ``session_ref`` (given to the agent by the relay at the start of each turn) and nothing that
identifies a person. The server exchanges the session ref for a member-scoped core token, so a prompt-injected
"show me member X" cannot reach anyone else's data. Writes are two-step: ``prepare_*`` creates a pending action
and a review card; ``submit_*`` only succeeds after the user pressed Confirm in that card (enforced by the
broker and the core, not by the model).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated, Any

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import cards as C
from .clients import BrokerClient, CoreClient, Grant, HandoffClient, UpstreamError

log = logging.getLogger("healthgen.mcp")

SessionRef = Annotated[str, Field(description="The session_ref given to you for this conversation. Never invent one.", pattern=r"^ses_[0-9a-f]{32}$")]
ServiceRef = Annotated[str, Field(description="Service ref from search_services or check_benefits, e.g. svc_focused_skin_exam", pattern=r"^svc_[a-z0-9_]+$")]
ProviderRef = Annotated[str, Field(description="Provider ref from find_providers, e.g. prv_19", pattern=r"^prv_[a-z0-9_]+$")]
ActionRef = Annotated[str, Field(description="action_id returned by the matching prepare_* tool", pattern=r"^act_[0-9a-f]{32}$")]
Zip = Annotated[str | None, Field(description="5-digit ZIP; defaults to the member's home ZIP", pattern=r"^\d{5}$")]
Radius = Annotated[int, Field(description="Search radius in miles", ge=1, le=50)]

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
PREPARE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)

FRIENDLY = {
    "invalid_grant": "The conversation session is no longer active. Ask the user to refresh the page.",
    "session_inactive": "The conversation session is no longer active. Ask the user to refresh the page.",
    "confirmation_required": "The user has not confirmed this request yet. Show the review card and wait for Confirm.",
    "member_mismatch": "That record is not available in this conversation.",
    "not_on_panel": "This patient is not attributed to the signed-in provider.",
    "slot_taken": "That time was just taken. Offer to show availability again.",
    "not_found": "Not found. Use refs returned by earlier tool calls.",
    "role_not_allowed": "That action is not available in this portal.",
    "provider_only": "Only a provider can submit a referral.",
    "upstream_unreachable": "The member system is temporarily unavailable. Offer a hand-off to a care specialist.",
}


def fail(exc: UpstreamError) -> ToolError:
    log.info("tool upstream error %s %s", exc.status, exc.code)
    return ToolError(f"{exc.code}: {FRIENDLY.get(exc.code, 'The request could not be completed.')}")


@dataclass
class Deps:
    broker: BrokerClient
    core: CoreClient
    cards: C.CardStore
    handoff: HandoffClient


def register(server: MCPServer, deps: Deps) -> None:
    async def call(fn, *args, **kwargs):
        try:
            return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))
        except UpstreamError as exc:
            raise fail(exc) from exc

    async def grant(session_ref: str, scope: str | None = None) -> Grant:
        return await call(deps.broker.exchange, session_ref, scope)

    async def member_context(g: Grant) -> dict[str, Any]:
        return await call(deps.core.get, g, f"/v1/members/{g.claims['member_ref']}")

    async def benefit_row(g: Grant, service_ref: str) -> dict[str, Any] | None:
        body = await call(deps.core.get, g, f"/v1/members/{g.claims['member_ref']}/benefits", service_ref=service_ref)
        return body["benefits"][0] if body["benefits"] else None

    @server.tool(annotations=READ, structured_output=True)
    async def get_member_summary(session_ref: SessionRef) -> dict[str, Any]:
        """Plan, coverage status and primary care doctor of the member in this conversation (the signed-in member,
        or the patient in context in the provider portal). Use the first name only when addressing the member."""
        g = await grant(session_ref, "members.read eligibility.read")
        m = await member_context(g)
        e = await call(deps.core.get, g, f"/v1/members/{g.claims['member_ref']}/eligibility")
        return {
            "audience": g.claims["role"],
            "first_name": m["first_name"],
            "plan": m["plan"],
            "coverage_active": e["active_on_date"],
            "coverage_period": {"from": e["effective_date"], "to": e["termination_date"]},
            "pcp": m["pcp"],
            "home_zip": m["home_zip"],
        }

    @server.tool(annotations=READ, structured_output=True)
    async def check_benefits(
        session_ref: SessionRef,
        service_ref: Annotated[str | None, Field(description="A service ref; omit to list the whole category", pattern=r"^svc_[a-z0-9_]+$")] = None,
        category: Annotated[str | None, Field(description="Benefit category, e.g. dermatology")] = None,
    ) -> dict[str, Any]:
        """Coverage for a service on the member's plan: copay or coinsurance, deductible, referral and prior-auth
        rules. With one service_ref it also returns a card_ref for the benefit card."""
        if not service_ref and not category:
            raise ToolError("Give a service_ref or a category. Use search_services to find the service first.")
        g = await grant(session_ref, "members.read benefits.read")
        body = await call(deps.core.get, g, f"/v1/members/{g.claims['member_ref']}/benefits", service_ref=service_ref, category=category)
        out: dict[str, Any] = {"plan": body["plan"], "benefits": body["benefits"]}
        if service_ref and body["benefits"]:
            m = await member_context(g)
            out["card_ref"] = deps.cards.put(session_ref, "benefit-coverage@1", C.benefit_card(body["benefits"][0], body["plan"], m["plan"]["year"]))
        return out

    @server.tool(annotations=READ, structured_output=True)
    async def get_accumulators(session_ref: SessionRef) -> dict[str, Any]:
        """Deductible and out-of-pocket amounts met and remaining for the plan year."""
        g = await grant(session_ref, "accumulators.read")
        return await call(deps.core.get, g, f"/v1/members/{g.claims['member_ref']}/accumulators")

    @server.tool(annotations=READ, structured_output=True)
    async def search_services(
        session_ref: SessionRef,
        query: Annotated[str, Field(description="What the person needs, in plain words, e.g. 'changing mole'", min_length=2, max_length=120)],
        zip: Zip = None,
        radius_miles: Radius = 5,
    ) -> dict[str, Any]:
        """Match a need to covered services and return a card_ref for the service options card (ZIP and distance
        inputs included)."""
        g = await grant(session_ref, "members.read services.read benefits.read")
        body = await call(deps.core.get, g, "/v1/services", q=query)
        services = body["services"]
        if not services:
            return {"services": [], "message": "No matching service. Ask a clarifying question."}
        m = await member_context(g)
        first = await benefit_row(g, services[0]["ref"])
        hint = None
        if first and first.get("covered"):
            hint = f"Covered office exam: {C.cost_text(first.get('in_network'))}." + (" PCP referral required." if first.get("referral_required") else "")
        covered = [s for s in services if s["ref"] != "svc_cosmetic_skin_screening"] or services
        card = C.service_card(covered, zip or m["home_zip"], radius_miles, covered[0]["ref"], hint)
        return {"services": services, "card_ref": deps.cards.put(session_ref, "service-options@1", card)}

    @server.tool(annotations=READ, structured_output=True)
    async def check_prior_auth(session_ref: SessionRef, service_ref: ServiceRef) -> dict[str, Any]:
        """Whether prior authorization and/or a referral is needed for a service on the member's plan."""
        g = await grant(session_ref, "priorauth.read")
        return await call(deps.core.get, g, f"/v1/members/{g.claims['member_ref']}/prior-auth", service_ref=service_ref)

    @server.tool(annotations=READ, structured_output=True)
    async def find_providers(
        session_ref: SessionRef,
        service_ref: ServiceRef,
        zip: Zip = None,
        radius_miles: Radius = 5,
        accepting_new_patients_only: bool = False,
    ) -> dict[str, Any]:
        """In-network doctors for a service near a ZIP, nearest first, with a card_ref for the doctor list."""
        g = await grant(session_ref, "members.read providers.read benefits.read services.read")
        m = await member_context(g)
        zip_code = zip or m["home_zip"]
        body = await call(deps.core.get, g, "/v1/providers", service_ref=service_ref, plan_ref=m["plan"]["ref"], zip=zip_code,
                          radius_miles=radius_miles, accepting_only=accepting_new_patients_only)
        row = await benefit_row(g, service_ref)
        svc = (row or {}).get("service") or {"ref": service_ref, "name": service_ref}
        out: dict[str, Any] = {"providers": body["providers"], "zip": zip_code, "radius_miles": radius_miles}
        if body["providers"]:
            card = C.providers_card(body["providers"], m["plan"]["name"], radius_miles, zip_code, svc, g.claims["role"], bool((row or {}).get("referral_required")))
            out["card_ref"] = deps.cards.put(session_ref, "provider-results@1", card)
        else:
            out["message"] = "No in-network doctors in that radius. Suggest a larger radius."
        return out

    @server.tool(annotations=READ, structured_output=True)
    async def get_availability(session_ref: SessionRef, provider_ref: ProviderRef, service_ref: ServiceRef) -> dict[str, Any]:
        """Open appointment times with a doctor for a service, with a card_ref for the time picker. Does not book."""
        g = await grant(session_ref, "providers.read benefits.read members.read")
        provider = await call(deps.core.get, g, f"/v1/providers/{provider_ref}")
        body = await call(deps.core.get, g, f"/v1/providers/{provider_ref}/availability", service_ref=service_ref)
        row = await benefit_row(g, service_ref)
        svc = (row or {}).get("service") or {"ref": service_ref, "name": service_ref}
        out: dict[str, Any] = {"provider_ref": provider_ref, "accepting_new_patients": body["accepting_new_patients"], "slots": body["slots"]}
        if body["slots"]:
            out["card_ref"] = deps.cards.put(session_ref, "availability-slots@1", C.availability_card(provider, svc, body["slots"]))
        return out

    @server.tool(annotations=PREPARE, structured_output=True)
    async def prepare_appointment_request(session_ref: SessionRef, provider_ref: ProviderRef, slot_ref: Annotated[str, Field(pattern=r"^slt_[a-z0-9_]+$")], service_ref: ServiceRef) -> dict[str, Any]:
        """Step 1 of booking (members only): checks the time is still open and creates a review card. Nothing is
        booked. Show the card_ref and wait; the user confirms in the card."""
        g = await grant(session_ref, "members.read providers.read benefits.read")
        if g.claims["role"] != "member":
            raise ToolError("role_not_allowed: Booking is only available in the member portal.")
        provider = await call(deps.core.get, g, f"/v1/providers/{provider_ref}")
        body = await call(deps.core.get, g, f"/v1/providers/{provider_ref}/availability", service_ref=service_ref)
        slot = next((s for s in body["slots"] if s["ref"] == slot_ref), None)
        if not slot:
            raise ToolError("slot_taken: That time is no longer available. Call get_availability again.")
        row = await benefit_row(g, service_ref)
        if not row or not row.get("covered"):
            raise ToolError("not_covered: This service is not covered on the member's plan.")
        params = {"provider_ref": provider_ref, "slot_ref": slot_ref, "service_ref": service_ref}
        card = C.booking_review_card("", provider, slot, row["service"], C.cost_text(row.get("in_network")), bool(row.get("referral_required")))
        action = await call(deps.broker.create_action, session_ref, "appointment.request", params, {"facts": card["facts"]})
        card["actionId"] = action["action_id"]
        return {"action_id": action["action_id"], "status": "awaiting_user_confirmation",
                "card_ref": deps.cards.put(session_ref, "booking-review@1", card)}

    @server.tool(annotations=WRITE, structured_output=True)
    async def submit_appointment_request(session_ref: SessionRef, action_id: ActionRef) -> dict[str, Any]:
        """Step 2 of booking. Only call after the relay tells you the user confirmed this action_id."""
        g: Grant = await call(deps.broker.exchange, session_ref, None, action_id)
        a = g.action or {}
        p = a.get("params") or {}
        appt = await call(deps.core.post, g, "/v1/appointments/requests", {**p, "note": (a.get("extras") or {}).get("note")})
        provider = await call(deps.core.get, await grant(session_ref, "providers.read"), f"/v1/providers/{p['provider_ref']}")
        card = C.confirmation_card("Booked", "Your appointment is booked", [
            {"title": "Confirmation", "value": appt["ref"]},
            {"title": "Doctor", "value": f"{provider['name']}, {provider['practice']}"},
            {"title": "When", "value": C.slot_label(appt["start"])},
            {"title": "Where", "value": f"{appt['location']['line1']}, {appt['location']['city']}"},
        ], "You'll get a reminder the day before. Manage or cancel it from Appointments in the portal.")
        return {"appointment_ref": appt["ref"], "status": appt["status"], "start": appt["start"],
                "card_ref": deps.cards.put(session_ref, "confirmation@1", card)}

    @server.tool(annotations=PREPARE, structured_output=True)
    async def prepare_referral(
        session_ref: SessionRef,
        to_provider_ref: ProviderRef,
        service_ref: ServiceRef,
        visits: Annotated[int, Field(ge=1, le=6, description="Number of visits the referral covers")] = 1,
    ) -> dict[str, Any]:
        """Step 1 of a referral (provider portal only): drafts a referral for the patient in context and returns a
        review card. Nothing is sent until the provider submits it in the card."""
        g = await grant(session_ref, "members.read providers.read benefits.read")
        if g.claims["role"] != "provider":
            raise ToolError("role_not_allowed: Referrals are created by the member's doctor in the provider portal.")
        m = await member_context(g)
        provider = await call(deps.core.get, g, f"/v1/providers/{to_provider_ref}")
        if service_ref not in provider.get("services", []):
            raise ToolError("not_found: That doctor does not offer this service.")
        row = await benefit_row(g, service_ref)
        params = {"to_provider_ref": to_provider_ref, "service_ref": service_ref, "visits": visits}
        card = C.referral_review_card("", m["display_name"], provider, (row or {}).get("service") or {"ref": service_ref, "name": service_ref}, m["plan"]["name"], visits)
        action = await call(deps.broker.create_action, session_ref, "referral.submit", params, {"facts": card["facts"]})
        card["actionId"] = action["action_id"]
        return {"action_id": action["action_id"], "status": "awaiting_user_confirmation",
                "card_ref": deps.cards.put(session_ref, "referral-review@1", card)}

    @server.tool(annotations=WRITE, structured_output=True)
    async def submit_referral(session_ref: SessionRef, action_id: ActionRef) -> dict[str, Any]:
        """Step 2 of a referral. Only call after the relay tells you the provider submitted this action_id."""
        g: Grant = await call(deps.broker.exchange, session_ref, None, action_id)
        a = g.action or {}
        p = a.get("params") or {}
        ref = await call(deps.core.post, g, "/v1/referrals", {**p, "reason": (a.get("extras") or {}).get("reason")})
        provider = await call(deps.core.get, await grant(session_ref, "providers.read"), f"/v1/providers/{p['to_provider_ref']}")
        card = C.confirmation_card("Submitted", "Referral submitted", [
            {"title": "Referral", "value": ref["ref"]},
            {"title": "Refer to", "value": f"{provider['name']}, {provider['practice']}"},
            {"title": "Visits", "value": str(ref["visits"])},
            {"title": "Valid", "value": f"{ref['valid_from']} to {ref['valid_to']}"},
        ], "The member and the specialist's office have been notified.")
        return {"referral_ref": ref["ref"], "status": ref["status"], "card_ref": deps.cards.put(session_ref, "confirmation@1", card)}

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True), structured_output=True)
    async def request_human_handoff(
        session_ref: SessionRef,
        reason: Annotated[str, Field(description="user_request | out_of_scope | complaint | clinical | system_error")],
        topic: Annotated[str, Field(description="One short line for the care specialist, no diagnoses or member ids", max_length=200)],
    ) -> dict[str, Any]:
        """Hand the conversation to a human care specialist. Use when the user asks for a person, for complaints,
        clinical questions, or when a tool keeps failing."""
        g = await grant(session_ref, "members.read")
        res = await call(deps.handoff.send, {"session_ref": session_ref, "audience": g.claims["role"], "reason": reason, "topic": topic[:200]})
        return {"ticket_ref": res.get("ticket_ref"), "queue": res.get("queue", "care-team"), "expected_response": res.get("expected_response", "under 10 minutes during business hours")}
