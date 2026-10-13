# `services/healthgen-core-mock/app/data.py`

Source: [`services/healthgen-core-mock/app/data.py`](../../../../../../services/healthgen-core-mock/app/data.py)

> **Summary:** Invented data that matches the Care assistant prototype: two members, two plans, dermatology benefits, five providers, ZIP centroids and deterministic appointment slots.

## Contents

| Data | Details |
| --- | --- |
| `PLANS` | Harbor HMO 2026 (referral required, no out-of-network) and Harbor PPO 2026. |
| `MEMBERS` | `mbr_7f3a` Alex Morgan (HMO, id ending 4821, ZIP 10013, PCP Dr. Priya Raman) and `mbr_2c91` Jordan Lee (PPO, 1307, 10003, Dr. Sam Ortiz). |
| `ELIGIBILITY`, `ACCUMULATORS` | Active 2026 coverage; HMO deductible $450 of $1,500 met. |
| `SERVICES` | Focused and comprehensive skin exams, skin biopsy, Mohs surgery, cosmetic consultation (excluded). |
| `BENEFITS` | Per plan and service: HMO specialist copay $40 with referral; PPO $60 in-network or 40% out-of-network; biopsy coinsurance; Mohs needs prior auth. |
| `PROVIDERS` | Dr. Nina Patel (`prv_19`, SoHo Skin, ~0.6 mi from 10013), Dr. Daniel Chen (`prv_42`, Union Dermatology, ~1.3 mi), Dr. Maya Brooks (`prv_57`, PPO only, not accepting), and the PCPs `prv_pcp_01` and `prv_pcp_02`. |
| `PROVIDER_PANELS` | Which members each PCP may act for. |
| `ZIP_CENTROIDS`, `SLOT_TIMES` | Inputs for distance and availability. |

## Functions

- `miles_between()`: haversine distance.
- `next_business_days()`
- `availability(provider_ref, today, days=3)`: deterministic slots for the next business days, with a predictable gap pattern and refs like `slt_prv_19_202610151030`.

## How it's used in the real system

It isn't. It exists for local runs, the pilot and tests. Its values match the synthetic plan documents in [`search/documents`](../../../../files/search/documents/harbor-hmo-2026-sbc.md.md), so the FAQ and the member data agree.
