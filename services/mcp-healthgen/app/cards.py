"""Card data built from system-of-record responses.

Tools return a short ``card_ref`` to the model instead of card JSON. The agent puts the ref in its reply
envelope; the relay fetches the card here (``GET /internal/cards/{ref}``) and binds the template. So what a
member sees in a card always comes from HealthGen core, never from text the model generated.
"""

from __future__ import annotations

import datetime as dt
import secrets
import threading
import time
from typing import Any

DISTANCE_OPTIONS = [{"title": f"Within {m} mile{'s' if m > 1 else ''}", "value": str(m)} for m in (1, 5, 10, 25)]


class CardStore:
    """In-memory, per-session, 30-minute TTL. Single replica for the pilot (see docs/operations.md)."""

    def __init__(self, ttl: int = 1800, max_cards: int = 50_000):
        self.ttl = ttl
        self.max_cards = max_cards
        self._cards: dict[str, tuple[str, float, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def put(self, session_ref: str, template_id: str, data: dict[str, Any]) -> str:
        ref = f"crd_{secrets.token_hex(8)}"
        now = time.time()
        with self._lock:
            if len(self._cards) >= self.max_cards:
                for k in [k for k, v in self._cards.items() if v[1] < now] or list(self._cards)[: self.max_cards // 10]:
                    self._cards.pop(k, None)
            self._cards[ref] = (session_ref, now + self.ttl, {"template_id": template_id, "data": data})
        return ref

    def get(self, card_ref: str, session_ref: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._cards.get(card_ref)
        if not entry or entry[0] != session_ref or entry[1] < time.time():
            return None
        return entry[2]


def money(v: float | None) -> str:
    if v is None:
        return "—"
    return f"${v:,.0f}" if float(v).is_integer() else f"${v:,.2f}"


def cost_text(tier: dict[str, Any] | None) -> str:
    if not tier:
        return "Not covered"
    parts = []
    if tier.get("copay"):
        parts.append(f"{money(tier['copay'])} specialist copay per visit")
    if tier.get("coinsurance_pct"):
        parts.append(f"{tier['coinsurance_pct']}% coinsurance")
    if not parts:
        parts.append("No cost share")
    return " + ".join(parts)


def slot_label(start_iso: str) -> str:
    d = dt.datetime.fromisoformat(start_iso)
    hour = d.strftime("%I").lstrip("0")
    return f"{d:%a}, {d:%b} {d.day} · {hour}:{d:%M} {d:%p}"


def initials(name: str) -> str:
    words = [w for w in name.replace("Dr.", "").split() if w]
    return "".join(w[0] for w in words[:2]).upper()


def benefit_card(row: dict[str, Any], plan: dict[str, Any], plan_year: int) -> dict[str, Any]:
    svc = row["service"]
    facts: list[dict[str, str]] = []
    if row.get("covered"):
        inn = row.get("in_network") or {}
        oon = row.get("out_of_network")
        facts.append({"title": "Network", "value": "In-network only" if not oon else "In- and out-of-network"})
        facts.append({"title": "Visit cost", "value": cost_text(inn)})
        if oon:
            facts.append({"title": "Out of network", "value": cost_text(oon) + (" after deductible" if oon.get("deductible_applies") else "")})
        facts.append({"title": "Deductible", "value": "Applies" if inn.get("deductible_applies") else "Does not apply to this service"})
        facts.append({"title": "Referral", "value": "PCP referral required before visit" if row.get("referral_required") else "Not required"})
        facts.append({"title": "Prior auth", "value": "Required" if row.get("prior_auth_required") else "Not required"})
        if row.get("limits"):
            facts.append({"title": "Limits", "value": row["limits"]})
        label = "Covered when medically necessary"
    else:
        facts.append({"title": "Coverage", "value": row.get("exclusion") or "Not covered"})
        label = "Not covered"
    return {
        "service": {"name": svc["name"], "category": svc["category"].title(), "ref": svc["ref"]},
        "plan": {"name": plan["name"], "year": str(plan_year), "ref": plan["ref"]},
        "coverage": {"label": label},
        "facts": facts,
        "notice": "Estimate, not a payment guarantee. Biopsy, lab work and treatment may cost extra. "
                  "Final coverage depends on eligibility and how the claim is coded.",
    }


def service_card(services: list[dict[str, Any]], zip_code: str, distance: int, selected: str | None, copay_hint: str | None) -> dict[str, Any]:
    return {
        "title": f"{services[0]['category'].title()} service options" if services else "Service options",
        "subtitle": f"In person · Near {zip_code}",
        "zip": zip_code,
        "distance": str(distance),
        "distanceOptions": DISTANCE_OPTIONS,
        "services": [{"ref": s["ref"], "name": s["name"], "description": s["description"]} for s in services],
        "selected": selected or (services[0]["ref"] if services else None),
        "notice": copay_hint or "Choose a service to see in-network doctors. Nothing is booked.",
    }


def providers_card(providers: list[dict[str, Any]], plan_name: str, radius: float, zip_code: str, service: dict[str, Any], audience: str, referral_required: bool) -> dict[str, Any]:
    doctors = []
    for p in providers:
        doctors.append({
            "ref": p["ref"],
            "initials": initials(p["name"]),
            "name": p["name"],
            "specialty": "Dermatologist" if p["specialty"] == "Dermatology" else p["specialty"],
            "practice": p["practice"],
            "services": " · ".join(p.get("highlights") or []),
            "network": ("In-network" if p.get("in_network", True) else "Out-of-network") + (" · Accepting new patients" if p.get("accepting_new_patients") else " · Not accepting new patients"),
            "address": p["address"]["line1"],
            "distanceText": f"{p.get('distance_miles', 0)} miles away",
        })
    notice = ("PCP referral required. " if referral_required else "") + "Verify details with the office. No appointment or referral has been created."
    return {
        "title": f"Doctors for a {service['name'].lower()}",
        "doctors": doctors,
        "plan": plan_name,
        "radius": int(radius) if float(radius).is_integer() else radius,
        "zip": zip_code,
        "selected": doctors[0]["ref"] if doctors else None,
        "audience": audience,
        "serviceRef": service["ref"],
        "notice": notice,
    }


def availability_card(provider: dict[str, Any], service: dict[str, Any], slots: list[dict[str, Any]]) -> dict[str, Any]:
    items = [{"ref": s["ref"], "label": slot_label(s["start"]),
              "detail": f"In person · {s['duration_minutes']} min · {provider['address']['line1']}"} for s in slots]
    return {
        "doctor": {"name": provider["name"], "practice": provider["practice"], "ref": provider["ref"]},
        "service": service["name"],
        "slots": items,
        "selected": items[0]["ref"] if items else None,
        "serviceRef": service["ref"],
        "notice": "Times can change until booked. Choosing a time does not book it.",
    }


def booking_review_card(action_id: str, provider: dict[str, Any], slot: dict[str, Any], service: dict[str, Any], cost: str, referral_required: bool) -> dict[str, Any]:
    facts = [
        {"title": "Doctor", "value": f"{provider['name']}, {provider['practice']}"},
        {"title": "When", "value": slot_label(slot["start"])},
        {"title": "Where", "value": f"{provider['address']['line1']}, {provider['address']['city']}"},
        {"title": "Service", "value": service["name"]},
        {"title": "Estimated cost", "value": cost},
    ]
    if referral_required:
        facts.append({"title": "Before you go", "value": "Ask your PCP for a dermatology referral"})
    return {
        "actionId": action_id,
        "providerRef": provider["ref"],
        "slotRef": slot["ref"],
        "facts": facts,
        "notice": "Nothing is booked until you confirm. You can cancel from Appointments in the portal.",
    }


def referral_review_card(action_id: str, member_name: str, provider: dict[str, Any], service: dict[str, Any], plan_name: str, visits: int) -> dict[str, Any]:
    return {
        "actionId": action_id,
        "memberName": member_name,
        "providerRef": provider["ref"],
        "serviceRef": service["ref"],
        "facts": [
            {"title": "Patient", "value": member_name},
            {"title": "Refer to", "value": f"{provider['name']}, {provider['practice']}"},
            {"title": "Service", "value": service["name"]},
            {"title": "Plan", "value": plan_name},
            {"title": "Visits", "value": str(visits)},
            {"title": "Valid for", "value": "90 days from submission"},
        ],
        "notice": "Nothing is sent until you submit. The member and the specialist's office are notified after submission.",
    }


def confirmation_card(status: str, title: str, facts: list[dict[str, str]], notice: str) -> dict[str, Any]:
    return {"status": status, "title": title, "facts": facts, "notice": notice}
