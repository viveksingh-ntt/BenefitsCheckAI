# `search/documents/healthgen-member-faq.md`

Source: [`search/documents/healthgen-member-faq.md`](../../../../../search/documents/healthgen-member-faq.md)

> **Summary:** A synthetic plan document, "HealthGen member FAQ", indexed for the plan FAQ and benefit check agents. It is not a real plan.

**Sections:** Copay, deductible, coinsurance, finding an in-network doctor, cancelling an appointment, talking to a person.

**Format:** YAML front matter (`title`, `plan`, `plan_ref`, `doc_type`), then one `#` heading per section. [`search/ingest.py`](../ingest.py.md) turns each section into one search chunk. The figures match the core mock's data ([`app/data.py`](../../../files/services/healthgen-core-mock/app/data.py.md)), so the FAQ and the member-specific answers agree.

**In the real system:** replace it with the real document, converted to Markdown with the same front matter, or index the PDFs directly. Have plan documents reviewed by compliance; the agents quote them.
