# `search/documents/harbor-hmo-2026-eoc-referrals.md`

Source: [`search/documents/harbor-hmo-2026-eoc-referrals.md`](../../../../../search/documents/harbor-hmo-2026-eoc-referrals.md)

> **Summary:** A synthetic plan document, "Harbor HMO 2026 Evidence of Coverage: referrals and prior authorization", indexed for the plan FAQ and benefit check agents. It is not a real plan.

**Sections:** Referrals (valid 90 days, list visits, exceptions), seeing a specialist without a referral, prior authorization (examples, 15-day or 72-hour decisions), the definition of medically necessary, appeals (180 days to appeal).

**Format:** YAML front matter (`title`, `plan`, `plan_ref`, `doc_type`), then one `#` heading per section. [`search/ingest.py`](../ingest.py.md) turns each section into one search chunk. The figures match the core mock's data ([`app/data.py`](../../../files/services/healthgen-core-mock/app/data.py.md)), so the FAQ and the member-specific answers agree.

**In the real system:** replace it with the real document, converted to Markdown with the same front matter, or index the PDFs directly. Have plan documents reviewed by compliance; the agents quote them.
