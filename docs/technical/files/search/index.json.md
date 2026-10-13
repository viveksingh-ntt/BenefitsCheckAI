# `search/index.json`

Source: [`search/index.json`](../../../../search/index.json)

> **Summary:** The Azure AI Search index schema `healthgen-plan-docs`: the fields, and the semantic configuration that the agents' `query_type: semantic` relies on.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | key | `{file}-{nn}` |
| `title` | searchable | Document title |
| `section` | searchable | The semantic *title* field |
| `content` | searchable, `en.microsoft` analyzer | The semantic *content* field |
| `plan`, `plan_ref`, `doc_type` | filterable (`plan` and `doc_type` facetable) | Use these for filters such as `plan_ref eq 'pln_harbor_hmo_2026'` |
| `url` | retrievable | Citation link |

The semantic configuration `default` uses section as the title, content as the content, and plan and title as keywords. It has no vector fields. To add hybrid search, add an embedding field and a vectorizer, and change `query_type` in the agent YAML to `vector_semantic_hybrid`.
