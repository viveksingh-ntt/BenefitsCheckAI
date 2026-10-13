# `agents/plan-faq.yaml`

Source: [`agents/plan-faq.yaml`](../../../../agents/plan-faq.yaml)

> **Summary:** A declarative definition of `healthgen-plan-faq`. It answers general plan questions only from the plan documents in Azure AI Search, with no member data or PHI.

| | |
| --- | --- |
| Layer | Foundry agents |
| Local run | Not used (`foundry-local` does a keyword search over the same documents) |
| Azure | **Real** prompt agent with incoming A2A |
| Tools | `azure_ai_search` only (semantic, top 5) |
| Data classification | Public |

## What the instructions say

- Always search first, and answer only from what is found.
- Name the document and section ("Harbor HMO 2026 Evidence of Coverage, Referrals").
- Questions like "what will I pay" get the plan rule plus a *Check my benefits* suggestion.
- Ignore any `session_ref`, and never return a `card_ref`.

## How it's used in the real system

Keeping PHI tools out of this agent means general questions never touch member data. To grow it, replace the synthetic documents with your real SBC and EOC documents ([`search/ingest.py`](../../files/search/ingest.py.md)) and add more skills to its agent card.
