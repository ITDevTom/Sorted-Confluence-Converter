# Confluence Converter

Export Confluence Cloud pages into structured JSON suitable for LLM ingestion. The converter:

- pulls page content (and optional descendants) via the Confluence Cloud REST API,
- normalises HTML into Markdown sections (lifting tables into JSON),
- emits document JSON, chunk JSONL, and an embedding state index for delta detection.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configure Environment

Update `.env` (auto-created from `.env.example` if missing) with your Confluence credentials:

```dotenv
CONF_BASE_URL=https://company.atlassian.net/wiki
CONF_EMAIL=me@company.com
CONF_API_TOKEN=***
CONF_SPACE=CSP
CONF_ROOT_PAGE_ID=1234567890
INCLUDE_CHILDREN=true
```

- `CONF_ROOT_PAGE_ID` is the numeric ID of the page to export.
- Set `INCLUDE_CHILDREN=false` to export only the root page.

### Run the Converter

```bash
python converter.py --space CSP --root-page-id 1234567890
```

Any CLI flag overrides the matching `.env` entry. Use `--no-include-children` to skip descendants.

## Outputs

- `out/docs/<slug>.json` — full document (metadata, sections, chunks).
- `out/chunks/chunks.jsonl` — one JSON object per chunk (ready for embeddings).
- `out/state/emb_index.json` — `chunk_id -> text_hash` map for delta detection.

Each run overwrites the outputs to maintain deterministic state.

## Table JSON

Tables are preserved in two forms:

1. Markdown within the section body (`body_md`) for human readable output.
2. Structured `table_json` payload:

```json
{
  "columns": ["carrier", "required"],
  "display_columns": ["Carrier", "Required"],
  "rows": [
    {"carrier": "DHL Paket", "required": "EKP Number"}
  ]
}
```

Consumers can render tabular UI directly from `table_json` while still indexing the surrounding text in embeddings.

## Logging & Deltas

- Logs report page, section, and chunk counts during export.
- `emb_index.json` tracks chunk content hashes so you can re-embed only changed chunks after each run.
- Removed chunks appear in the log summary to highlight embedding deletions to handle.

