# `search/ingest.py`

Source: [`search/ingest.py`](../../../../search/ingest.py)

> **Summary:** Creates or updates the Azure AI Search index for plan documents and uploads the documents, one chunk per `#` section.

## Usage

```bash
SEARCH_SERVICE_NAME=srch-healthgen python search/ingest.py   # Entra token via az, or SEARCH_ADMIN_KEY
python search/ingest.py --dry-run                            # print the 22 chunks
```

## What it does

- **`chunks(path)`:** parses the YAML front matter (`title`, `plan`, `plan_ref`, `doc_type`), removes HTML comments, and splits on `# ` headings. Each chunk gets:
  - an `id` (`{file}-{nn}`), `section`, and the content on one line;
  - the plan fields;
  - a portal `url` with an anchor, based on `PLAN_DOCS_BASE_URL`.
- **`main()`:** `PUT /indexes/{name}` with `index.json` (api-version `2024-07-01`; the name can be overridden with `SEARCH_INDEX_NAME`), then `POST /docs/index` with `mergeOrUpload`. It fails if any document fails.
- **`headers()`:** uses `SEARCH_ADMIN_KEY`, or `az account get-access-token --resource https://search.azure.com`.

## How it's used in the real system

Point it at your real SBC and EOC documents (Markdown with the same front matter), or replace it with an indexer over Blob Storage when the documents are PDFs. Keep the field names: the agents' search tool returns `title`, `section`, `content` and `url`. `foundry-local` also imports `chunks()` for its keyword search.
