"""HealthGen core mock: the system-of-record APIs the MCP data spoke calls.

Run:  uvicorn app.main:app --port 8101
Every route except /healthz needs a downstream token from the identity broker (see auth.py).
"""

from __future__ import annotations

import datetime as dt
import itertools
import logging
import os
import threading
from typing import Any, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import data
from .auth import AuthError, Principal, TokenValidator

log = logging.getLogger("healthgen.core")


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def money(v: float | None) -> float | None:
    return None if v is None else round(float(v), 2)


class Store:
    """In-memory writes. The real core persists these; the mock forgets them on restart."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.appointments: dict[str, dict[str, Any]] = {}
        self.referrals: dict[str, dict[str, Any]] = {}
        self.booked_slots: set[str] = set()
        self._seq = itertools.count(2741)

    def next_ref(self, prefix: str) -> str:
        return f"{prefix}-{next(self._seq)}"


def create_app(validator: TokenValidator | None = None, today: Callable[[], dt.date] | None = None) -> Starlette:
    validator = validator or TokenValidator.from_env()
    store = Store()
    fixed_today = os.getenv("CORE_TODAY")
    today = today or (lambda: dt.date.fromisoformat(fixed_today) if fixed_today else dt.date.today())

    def authed(scope: str) -> Callable:
        def wrap(fn: Callable) -> Callable:
            async def handler(request: Request) -> JSONResponse:
                try:
                    principal = validator.validate(request.headers.get("authorization"))
                    principal.require_scope(scope)
                    return await fn(request, principal)
                except AuthError as exc:
                    log.info("denied %s %s: %s", request.method, request.url.path, exc.code)
                    return error(exc.status, exc.code, str(exc))
                except LookupError as exc:
                    return error(404, "not_found", str(exc))
                except ValueError as exc:
                    return error(400, "bad_request", str(exc))
            return handler
        return wrap

    def member_for(principal: Principal, member_ref: str) -> dict[str, Any]:
        principal.require_member(member_ref)
        member = data.MEMBERS.get(member_ref)
        if not member:
            raise LookupError("Member not found")
        if principal.role == "provider" and member_ref not in data.PROVIDER_PANELS.get(principal.sub, []):
            raise AuthError(403, "not_on_panel", "Member is not attributed to this provider")
        return member

    def provider_view(p: dict[str, Any], origin: tuple[float, float] | None, plan: dict[str, Any] | None) -> dict[str, Any]:
        out = {k: v for k, v in p.items() if k not in ("location", "networks")}
        if origin:
            out["distance_miles"] = round(data.miles_between(origin, p["location"]), 1)
        if plan:
            out["in_network"] = plan["network_ref"] in p["networks"]
        return out

    # ------------------------------------------------------------------ members

    @authed("members.read")
    async def get_member(request: Request, principal: Principal) -> JSONResponse:
        m = member_for(principal, request.path_params["member_ref"])
        plan = data.PLANS[m["plan_ref"]]
        pcp = data.PROVIDERS.get(m["pcp_ref"])
        return JSONResponse({
            "ref": m["ref"],
            "first_name": m["first_name"],
            "display_name": f'{m["first_name"]} {m["last_name"]}',
            "member_id_last4": m["member_id_last4"],
            "plan": {"ref": plan["ref"], "name": plan["name"], "type": plan["type"], "year": plan["year"]},
            "home_zip": m["home_zip"],
            "pcp": {"ref": pcp["ref"], "name": pcp["name"], "practice": pcp["practice"]} if pcp else None,
        })

    @authed("eligibility.read")
    async def get_eligibility(request: Request, principal: Principal) -> JSONResponse:
        m = member_for(principal, request.path_params["member_ref"])
        e = data.ELIGIBILITY[m["ref"]]
        on = today().isoformat()
        active = e["status"] == "active" and e["effective_date"] <= on <= e["termination_date"]
        return JSONResponse({**e, "member_ref": m["ref"], "plan_ref": m["plan_ref"], "as_of": on, "active_on_date": active})

    @authed("accumulators.read")
    async def get_accumulators(request: Request, principal: Principal) -> JSONResponse:
        m = member_for(principal, request.path_params["member_ref"])
        a = data.ACCUMULATORS[m["ref"]]
        ded, oop = a["deductible"], a["out_of_pocket"]
        return JSONResponse({
            "member_ref": m["ref"],
            "plan_ref": m["plan_ref"],
            "as_of": a["as_of"],
            "deductible": {**ded, "individual_remaining": money(ded["individual_limit"] - ded["individual_met"])},
            "out_of_pocket": {**oop, "individual_remaining": money(oop["individual_limit"] - oop["individual_met"])},
        })

    @authed("benefits.read")
    async def get_benefits(request: Request, principal: Principal) -> JSONResponse:
        m = member_for(principal, request.path_params["member_ref"])
        plan = data.PLANS[m["plan_ref"]]
        service_ref = request.query_params.get("service_ref")
        category = request.query_params.get("category")
        rows = []
        for ref, b in data.BENEFITS[plan["ref"]].items():
            svc = data.SERVICES[ref]
            if service_ref and ref != service_ref:
                continue
            if category and svc["category"] != category:
                continue
            rows.append({"service": {k: svc[k] for k in ("ref", "name", "category", "procedure_code")}, **b})
        if service_ref and not rows:
            raise LookupError("Service not found for this plan")
        return JSONResponse({"member_ref": m["ref"], "plan": {"ref": plan["ref"], "name": plan["name"], "type": plan["type"]}, "benefits": rows})

    @authed("priorauth.read")
    async def get_prior_auth(request: Request, principal: Principal) -> JSONResponse:
        m = member_for(principal, request.path_params["member_ref"])
        service_ref = request.query_params.get("service_ref") or ""
        b = data.BENEFITS[m["plan_ref"]].get(service_ref)
        if not b:
            raise LookupError("Service not found for this plan")
        return JSONResponse({
            "member_ref": m["ref"],
            "service_ref": service_ref,
            "procedure_code": data.SERVICES[service_ref]["procedure_code"],
            "prior_auth_required": bool(b.get("prior_auth_required")),
            "referral_required": bool(b.get("referral_required")),
            "notes": "Prior authorization is requested by the treating provider." if b.get("prior_auth_required") else None,
        })

    # ----------------------------------------------------------------- catalog

    @authed("services.read")
    async def search_services(request: Request, principal: Principal) -> JSONResponse:
        q = (request.query_params.get("q") or "").lower().strip()
        category = request.query_params.get("category")
        out = []
        for svc in data.SERVICES.values():
            if category and svc["category"] != category:
                continue
            hay = " ".join([svc["name"], svc["description"], *svc["keywords"]]).lower()
            if q and not any(word in hay for word in q.split()):
                continue
            out.append({k: svc[k] for k in ("ref", "name", "category", "procedure_code", "description")})
        return JSONResponse({"services": out})

    @authed("providers.read")
    async def search_providers(request: Request, principal: Principal) -> JSONResponse:
        qp = request.query_params
        specialty = (qp.get("specialty") or "").lower()
        service_ref = qp.get("service_ref")
        plan = data.PLANS.get(qp.get("plan_ref") or "")
        zip_code = qp.get("zip")
        radius = float(qp.get("radius_miles") or 10)
        if zip_code and zip_code not in data.ZIP_CENTROIDS:
            raise ValueError("Unknown ZIP code for this pilot area")
        origin = data.ZIP_CENTROIDS.get(zip_code) if zip_code else None
        results = []
        for p in data.PROVIDERS.values():
            if specialty and p["specialty"].lower() != specialty:
                continue
            if service_ref and service_ref not in p["services"]:
                continue
            if qp.get("in_network_only", "true") == "true" and plan and plan["network_ref"] not in p["networks"]:
                continue
            if qp.get("accepting_only") == "true" and not p["accepting_new_patients"]:
                continue
            view = provider_view(p, origin, plan)
            if origin and view["distance_miles"] > radius:
                continue
            results.append(view)
        results.sort(key=lambda r: r.get("distance_miles", 0))
        return JSONResponse({"providers": results, "radius_miles": radius, "zip": zip_code})

    @authed("providers.read")
    async def get_provider(request: Request, principal: Principal) -> JSONResponse:
        p = data.PROVIDERS.get(request.path_params["provider_ref"])
        if not p:
            raise LookupError("Provider not found")
        return JSONResponse(provider_view(p, None, data.PLANS.get(request.query_params.get("plan_ref") or "")))

    @authed("providers.read")
    async def get_availability(request: Request, principal: Principal) -> JSONResponse:
        ref = request.path_params["provider_ref"]
        p = data.PROVIDERS.get(ref)
        if not p:
            raise LookupError("Provider not found")
        service_ref = request.query_params.get("service_ref")
        if service_ref and service_ref not in p["services"]:
            raise ValueError("Provider does not offer this service")
        slots = [s for s in data.availability(ref, today()) if s["ref"] not in store.booked_slots]
        return JSONResponse({"provider_ref": ref, "accepting_new_patients": p["accepting_new_patients"], "slots": slots})

    # ------------------------------------------------------------------ writes

    @authed("appointment.request")
    async def create_appointment(request: Request, principal: Principal) -> JSONResponse:
        body = await request.json()
        params = {k: body.get(k) for k in ("member_ref", "provider_ref", "slot_ref", "service_ref")}
        if not all(params.values()):
            raise ValueError("member_ref, provider_ref, slot_ref and service_ref are required")
        member_for(principal, params["member_ref"])
        confirmation_id = validator.consume_confirmation(principal, "appointment.request", params)
        provider = data.PROVIDERS.get(params["provider_ref"])
        if not provider or params["service_ref"] not in provider["services"]:
            raise LookupError("Provider or service not found")
        slot = next((s for s in data.availability(provider["ref"], today()) if s["ref"] == params["slot_ref"]), None)
        if not slot:
            raise LookupError("Slot not found")
        with store.lock:
            if slot["ref"] in store.booked_slots:
                return error(409, "slot_taken", "That time was just taken")
            store.booked_slots.add(slot["ref"])
            ref = store.next_ref("APT")
            appt = {
                "ref": ref,
                "status": "booked",
                **params,
                "start": slot["start"],
                "duration_minutes": slot["duration_minutes"],
                "location": provider["address"],
                "practice": provider["practice"],
                "note": (body.get("note") or "")[:300] or None,
                "confirmation_id": confirmation_id,
                "requested_by": {"role": principal.role, "ref": principal.sub},
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            store.appointments[ref] = appt
        log.info("appointment %s booked (confirmation %s, session %s)", ref, confirmation_id, principal.session_ref)
        return JSONResponse(appt, status_code=201)

    @authed("referral.submit")
    async def create_referral(request: Request, principal: Principal) -> JSONResponse:
        if principal.role != "provider":
            raise AuthError(403, "provider_only", "Only a provider can submit a referral")
        body = await request.json()
        params = {k: body.get(k) for k in ("member_ref", "to_provider_ref", "service_ref")}
        params["visits"] = int(body.get("visits") or 1)
        if not all(params.values()):
            raise ValueError("member_ref, to_provider_ref and service_ref are required")
        member = member_for(principal, params["member_ref"])
        confirmation_id = validator.consume_confirmation(principal, "referral.submit", params)
        to = data.PROVIDERS.get(params["to_provider_ref"])
        if not to or params["service_ref"] not in to["services"]:
            raise LookupError("Provider or service not found")
        start = today()
        with store.lock:
            ref = store.next_ref("REF")
            referral = {
                "ref": ref,
                "status": "submitted",
                **params,
                "referring_provider_ref": principal.sub,
                "plan_ref": member["plan_ref"],
                "valid_from": start.isoformat(),
                "valid_to": (start + dt.timedelta(days=90)).isoformat(),
                "reason": (body.get("reason") or "")[:300] or None,
                "confirmation_id": confirmation_id,
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            store.referrals[ref] = referral
        log.info("referral %s submitted (confirmation %s, session %s)", ref, confirmation_id, principal.session_ref)
        return JSONResponse(referral, status_code=201)

    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "healthgen-core-mock"})

    app = Starlette(routes=[
        Route("/healthz", healthz),
        Route("/v1/members/{member_ref}", get_member),
        Route("/v1/members/{member_ref}/eligibility", get_eligibility),
        Route("/v1/members/{member_ref}/accumulators", get_accumulators),
        Route("/v1/members/{member_ref}/benefits", get_benefits),
        Route("/v1/members/{member_ref}/prior-auth", get_prior_auth),
        Route("/v1/services", search_services),
        Route("/v1/providers", search_providers),
        Route("/v1/providers/{provider_ref}", get_provider),
        Route("/v1/providers/{provider_ref}/availability", get_availability),
        Route("/v1/appointments/requests", create_appointment, methods=["POST"]),
        Route("/v1/referrals", create_referral, methods=["POST"]),
    ])
    app.state.store = store
    return app


def _lazy_app() -> Starlette:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    return create_app()


class _Lazy:
    """Build the ASGI app on first request so importing this module never needs env vars (tests)."""

    def __init__(self) -> None:
        self._app: Starlette | None = None

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if self._app is None:
            self._app = _lazy_app()
        await self._app(scope, receive, send)


app = _Lazy()
