# `search/documents/harbor-ppo-2026-sbc.md`

Source: [`search/documents/harbor-ppo-2026-sbc.md`](../../../../../search/documents/harbor-ppo-2026-sbc.md)

> **Summary:** A synthetic plan document, "Harbor PPO 2026 Summary of Benefits and Coverage", indexed for the plan FAQ and benefit check agents. It is not a real plan.

**Sections:** Overview (no PCP or referrals needed), deductibles ($1,000 in-network / $2,000 out-of-network), office visits ($25 / $60, 40% out-of-network), dermatology, emergency and urgent care.

**Format:** YAML front matter (`title`, `plan`, `plan_ref`, `doc_type`), then one `#` heading per section. [`search/ingest.py`](../ingest.py.md) turns each section into one search chunk. The figures match the core mock's data ([`app/data.py`](../../../files/services/healthgen-core-mock/app/data.py.md)), so the FAQ and the member-specific answers agree.

**In the real system:** replace it with the real document, converted to Markdown with the same front matter, or index the PDFs directly. Have plan documents reviewed by compliance; the agents quote them.
