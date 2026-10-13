"""Synthetic HealthGen core data.

Everything here is invented for the pilot and the demos. It matches the Care assistant prototype
(Alex Morgan on Harbor HMO, Dr. Nina Patel at SoHo Skin, ...). No real members, providers or plans.
Replace this service with the real HealthGen core APIs; the MCP server only depends on the HTTP contract
listed in this service's README.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

PLAN_YEAR = 2026

PLANS: dict[str, dict[str, Any]] = {
    "pln_harbor_hmo_2026": {
        "ref": "pln_harbor_hmo_2026",
        "name": "Harbor HMO",
        "type": "HMO",
        "year": PLAN_YEAR,
        "network_ref": "net_harbor_hmo",
        "referral_required_for_specialist": True,
        "out_of_network_covered": False,
    },
    "pln_harbor_ppo_2026": {
        "ref": "pln_harbor_ppo_2026",
        "name": "Harbor PPO",
        "type": "PPO",
        "year": PLAN_YEAR,
        "network_ref": "net_harbor_ppo",
        "referral_required_for_specialist": False,
        "out_of_network_covered": True,
    },
}

MEMBERS: dict[str, dict[str, Any]] = {
    "mbr_7f3a": {
        "ref": "mbr_7f3a",
        "first_name": "Alex",
        "last_name": "Morgan",
        "date_of_birth": "1988-04-12",
        "member_id_last4": "4821",
        "plan_ref": "pln_harbor_hmo_2026",
        "home_zip": "10013",
        "pcp_ref": "prv_pcp_01",
        "relationship": "subscriber",
    },
    "mbr_2c91": {
        "ref": "mbr_2c91",
        "first_name": "Jordan",
        "last_name": "Lee",
        "date_of_birth": "1993-09-30",
        "member_id_last4": "1307",
        "plan_ref": "pln_harbor_ppo_2026",
        "home_zip": "10003",
        "pcp_ref": "prv_pcp_02",
        "relationship": "subscriber",
    },
}

ELIGIBILITY: dict[str, dict[str, Any]] = {
    "mbr_7f3a": {"status": "active", "effective_date": "2026-01-01", "termination_date": "2026-12-31", "coverage": ["medical", "pharmacy"]},
    "mbr_2c91": {"status": "active", "effective_date": "2026-03-01", "termination_date": "2026-12-31", "coverage": ["medical"]},
}

ACCUMULATORS: dict[str, dict[str, Any]] = {
    "mbr_7f3a": {
        "as_of": "2026-10-01",
        "deductible": {"individual_limit": 1500.0, "individual_met": 450.0},
        "out_of_pocket": {"individual_limit": 6000.0, "individual_met": 980.0},
    },
    "mbr_2c91": {
        "as_of": "2026-10-01",
        "deductible": {"individual_limit": 1000.0, "individual_met": 1000.0},
        "out_of_pocket": {"individual_limit": 5000.0, "individual_met": 1320.0},
    },
}

SERVICES: dict[str, dict[str, Any]] = {
    "svc_focused_skin_exam": {
        "ref": "svc_focused_skin_exam",
        "name": "Focused skin exam",
        "category": "dermatology",
        "procedure_code": "99203",
        "description": "One changing mole or specific skin concern.",
        "keywords": ["mole", "skin", "spot", "rash", "dermatology", "dermatologist", "skin check", "skin exam"],
    },
    "svc_comprehensive_skin_exam": {
        "ref": "svc_comprehensive_skin_exam",
        "name": "Comprehensive skin exam",
        "category": "dermatology",
        "procedure_code": "99204",
        "description": "Multiple concerns or a broader exam when clinically indicated.",
        "keywords": ["full body", "skin", "skin check", "dermatology", "dermatologist", "skin exam", "screening"],
    },
    "svc_skin_biopsy": {
        "ref": "svc_skin_biopsy",
        "name": "Skin biopsy",
        "category": "dermatology",
        "procedure_code": "11102",
        "description": "Removal of a small skin sample for lab testing, when the dermatologist recommends it.",
        "keywords": ["biopsy", "mole removal", "skin"],
    },
    "svc_mohs_surgery": {
        "ref": "svc_mohs_surgery",
        "name": "Mohs surgery",
        "category": "dermatology",
        "procedure_code": "17311",
        "description": "Specialised skin cancer surgery.",
        "keywords": ["mohs", "skin cancer", "surgery"],
    },
    "svc_cosmetic_skin_screening": {
        "ref": "svc_cosmetic_skin_screening",
        "name": "Cosmetic skin consultation",
        "category": "dermatology",
        "procedure_code": "S0000",
        "description": "Cosmetic evaluation with no medical concern.",
        "keywords": ["cosmetic", "wrinkle", "aesthetic"],
    },
}

# Benefit rows by plan and service. Money values are USD.
BENEFITS: dict[str, dict[str, dict[str, Any]]] = {
    "pln_harbor_hmo_2026": {
        "svc_focused_skin_exam": {"covered": True, "in_network": {"copay": 40.0, "coinsurance_pct": 0, "deductible_applies": False}, "out_of_network": None, "referral_required": True, "prior_auth_required": False, "limits": None},
        "svc_comprehensive_skin_exam": {"covered": True, "in_network": {"copay": 40.0, "coinsurance_pct": 0, "deductible_applies": False}, "out_of_network": None, "referral_required": True, "prior_auth_required": False, "limits": "One per year unless medically necessary"},
        "svc_skin_biopsy": {"covered": True, "in_network": {"copay": 0.0, "coinsurance_pct": 20, "deductible_applies": True}, "out_of_network": None, "referral_required": True, "prior_auth_required": False, "limits": None},
        "svc_mohs_surgery": {"covered": True, "in_network": {"copay": 0.0, "coinsurance_pct": 20, "deductible_applies": True}, "out_of_network": None, "referral_required": True, "prior_auth_required": True, "limits": None},
        "svc_cosmetic_skin_screening": {"covered": False, "exclusion": "Cosmetic services are excluded.", "referral_required": False, "prior_auth_required": False},
    },
    "pln_harbor_ppo_2026": {
        "svc_focused_skin_exam": {"covered": True, "in_network": {"copay": 60.0, "coinsurance_pct": 0, "deductible_applies": False}, "out_of_network": {"copay": 0.0, "coinsurance_pct": 40, "deductible_applies": True}, "referral_required": False, "prior_auth_required": False, "limits": None},
        "svc_comprehensive_skin_exam": {"covered": True, "in_network": {"copay": 60.0, "coinsurance_pct": 0, "deductible_applies": False}, "out_of_network": {"copay": 0.0, "coinsurance_pct": 40, "deductible_applies": True}, "referral_required": False, "prior_auth_required": False, "limits": "One per year unless medically necessary"},
        "svc_skin_biopsy": {"covered": True, "in_network": {"copay": 0.0, "coinsurance_pct": 15, "deductible_applies": True}, "out_of_network": {"copay": 0.0, "coinsurance_pct": 40, "deductible_applies": True}, "referral_required": False, "prior_auth_required": False, "limits": None},
        "svc_mohs_surgery": {"covered": True, "in_network": {"copay": 0.0, "coinsurance_pct": 15, "deductible_applies": True}, "out_of_network": {"copay": 0.0, "coinsurance_pct": 40, "deductible_applies": True}, "referral_required": False, "prior_auth_required": True, "limits": None},
        "svc_cosmetic_skin_screening": {"covered": False, "exclusion": "Cosmetic services are excluded.", "referral_required": False, "prior_auth_required": False},
    },
}

PROVIDERS: dict[str, dict[str, Any]] = {
    "prv_19": {
        "ref": "prv_19",
        "name": "Dr. Nina Patel",
        "first_name": "Nina",
        "last_name": "Patel",
        "specialty": "Dermatology",
        "practice": "SoHo Skin",
        "address": {"line1": "210 Spring St", "city": "New York", "state": "NY", "zip": "10012"},
        "location": (40.7265, -73.9975),
        "networks": ["net_harbor_hmo", "net_harbor_ppo"],
        "accepting_new_patients": True,
        "services": ["svc_focused_skin_exam", "svc_comprehensive_skin_exam", "svc_skin_biopsy"],
        "highlights": ["Medical skin exams", "Changing mole evaluation"],
        "languages": ["English", "Hindi"],
    },
    "prv_42": {
        "ref": "prv_42",
        "name": "Dr. Daniel Chen",
        "first_name": "Daniel",
        "last_name": "Chen",
        "specialty": "Dermatology",
        "practice": "Union Dermatology",
        "address": {"line1": "30 E 14th St", "city": "New York", "state": "NY", "zip": "10003"},
        "location": (40.7356, -73.9925),
        "networks": ["net_harbor_hmo", "net_harbor_ppo"],
        "accepting_new_patients": True,
        "services": ["svc_focused_skin_exam", "svc_skin_biopsy", "svc_mohs_surgery"],
        "highlights": ["Medical skin exams", "Changing mole evaluation"],
        "languages": ["English", "Mandarin"],
    },
    "prv_57": {
        "ref": "prv_57",
        "name": "Dr. Maya Brooks",
        "first_name": "Maya",
        "last_name": "Brooks",
        "specialty": "Dermatology",
        "practice": "Hudson Dermatology",
        "address": {"line1": "455 Hudson St", "city": "New York", "state": "NY", "zip": "10014"},
        "location": (40.7310, -74.0065),
        "networks": ["net_harbor_ppo"],
        "accepting_new_patients": False,
        "services": ["svc_focused_skin_exam", "svc_comprehensive_skin_exam"],
        "highlights": ["Medical skin exams"],
        "languages": ["English", "Spanish"],
    },
    "prv_pcp_01": {
        "ref": "prv_pcp_01",
        "name": "Dr. Priya Raman",
        "first_name": "Priya",
        "last_name": "Raman",
        "specialty": "Family Medicine",
        "practice": "Harbor Primary Care",
        "address": {"line1": "88 Hudson St", "city": "New York", "state": "NY", "zip": "10013"},
        "location": (40.7186, -74.0089),
        "networks": ["net_harbor_hmo", "net_harbor_ppo"],
        "accepting_new_patients": True,
        "services": [],
        "highlights": ["Primary care"],
        "languages": ["English", "Tamil"],
    },
    "prv_pcp_02": {
        "ref": "prv_pcp_02",
        "name": "Dr. Sam Ortiz",
        "first_name": "Sam",
        "last_name": "Ortiz",
        "specialty": "Family Medicine",
        "practice": "Midtown Family Medicine",
        "address": {"line1": "120 E 23rd St", "city": "New York", "state": "NY", "zip": "10010"},
        "location": (40.7397, -73.9851),
        "networks": ["net_harbor_hmo", "net_harbor_ppo"],
        "accepting_new_patients": True,
        "services": [],
        "highlights": ["Primary care"],
        "languages": ["English", "Spanish"],
    },
}

# Provider-portal users and the patients they may act for (attribution/panel).
PROVIDER_PANELS: dict[str, list[str]] = {
    "prv_pcp_01": ["mbr_7f3a"],
    "prv_pcp_02": ["mbr_2c91"],
}

ZIP_CENTROIDS: dict[str, tuple[float, float]] = {
    "10003": (40.7317, -73.9892),
    "10010": (40.7390, -73.9826),
    "10012": (40.7258, -73.9981),
    "10013": (40.7208, -74.0040),
    "10014": (40.7340, -74.0054),
    "10001": (40.7506, -73.9972),
}

SLOT_TIMES: dict[str, list[tuple[int, int]]] = {
    "prv_19": [(10, 30), (14, 15)],
    "prv_42": [(9, 0), (11, 45), (16, 0)],
    "prv_57": [(13, 0)],
}

DISTANCE_OPTIONS = [1, 5, 10, 25]


def miles_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def next_business_days(start: dt.date, count: int) -> list[dt.date]:
    days: list[dt.date] = []
    d = start
    while len(days) < count:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            days.append(d)
    return days


def availability(provider_ref: str, today: dt.date, days: int = 3) -> list[dict[str, Any]]:
    """Deterministic open slots for the next ``days`` business days."""
    slots: list[dict[str, Any]] = []
    for i, day in enumerate(next_business_days(today, days)):
        for j, (hh, mm) in enumerate(SLOT_TIMES.get(provider_ref, [])):
            # Leave a predictable gap so not every day looks identical.
            if (i + j) % 3 == 2:
                continue
            start = dt.datetime(day.year, day.month, day.day, hh, mm)
            slots.append({
                "ref": f"slt_{provider_ref}_{start:%Y%m%d%H%M}",
                "provider_ref": provider_ref,
                "start": start.isoformat(),
                "duration_minutes": 30,
                "mode": "in_person",
            })
    return slots
