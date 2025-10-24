from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv
from requests import HTTPError

from confluence_converter.api import ConfluenceClient, ConfluenceConfig
from confluence_converter.conversion import convert_page
from confluence_converter.utils import copy_env_example, load_json, write_json, write_jsonl

LOG = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent
OUT_ROOT = Path("out")
DOCS_DIR = OUT_ROOT / "docs"
CHUNKS_FILE = OUT_ROOT / "chunks" / "chunks.jsonl"
STATE_FILE = OUT_ROOT / "state" / "emb_index.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Confluence pages to JSON for LLM ingestion.")
    parser.add_argument("--base-url", dest="base_url")
    parser.add_argument("--email")
    parser.add_argument("--api-token", dest="api_token")
    parser.add_argument("--space")
    parser.add_argument("--root-page-id", dest="root_page_id")
    parser.add_argument(
        "--include-children",
        dest="include_children",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Include child pages (default: true). Use --no-include-children to disable.",
    )
    return parser.parse_args()


def env_or_default(args: argparse.Namespace) -> dict:
    from distutils.util import strtobool

    include_children_env = os.getenv("INCLUDE_CHILDREN", "true")
    include_children = (
        args.include_children
        if args.include_children is not None
        else bool(strtobool(include_children_env))
    )

    config = {
        "base_url": args.base_url or os.getenv("CONF_BASE_URL"),
        "email": args.email or os.getenv("CONF_EMAIL"),
        "api_token": args.api_token or os.getenv("CONF_API_TOKEN"),
        "space": args.space or os.getenv("CONF_SPACE"),
        "root_page_id": args.root_page_id or os.getenv("CONF_ROOT_PAGE_ID"),
        "include_children": include_children,
    }
    missing = [key for key, value in config.items() if value in (None, "")]
    if missing:
        raise ValueError(f"Missing required configuration keys: {', '.join(missing)}")
    return config


def ensure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def main() -> int:
    ensure_logging()
    copy_env_example(PROJECT_ROOT / ".env.example", PROJECT_ROOT / ".env")
    load_dotenv(PROJECT_ROOT / ".env")

    try:
        args = parse_args()
        settings = env_or_default(args)
    except ValueError as exc:
        LOG.error(str(exc))
        return 1

    client = ConfluenceClient(
        ConfluenceConfig(
            base_url=settings["base_url"],
            email=settings["email"],
            api_token=settings["api_token"],
        )
    )

    page_ids = list(client.traverse_descendants(settings["root_page_id"], settings["include_children"]))
    LOG.info("Processing %s page(s) from space %s", len(page_ids), settings["space"])

    all_chunks: List[dict] = []
    chunk_index: Dict[str, str] = {}
    processed_docs = 0

    for page_id in page_ids:
        try:
            page = client.fetch_page(page_id)
        except HTTPError as exc:
            LOG.error("Failed to fetch page %s: %s", page_id, exc)
            continue

        doc, chunks, chunk_map = convert_page(
            page,
            space=settings["space"],
            base_url=settings["base_url"],
        )

        doc_path = DOCS_DIR / (doc["slug"] + ".json")
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        with open(doc_path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)

        all_chunks.extend(chunks)
        chunk_index.update(chunk_map)
        processed_docs += 1
        LOG.info(
            "Exported %s (sections=%s, chunks=%s)",
            doc["title"],
            len(doc["sections"]),
            len(chunks),
        )

    if not processed_docs:
        LOG.warning("No documents exported.")
        return 0

    write_jsonl(CHUNKS_FILE, all_chunks)

    previous_index = load_json(STATE_FILE)
    write_json(STATE_FILE, chunk_index)

    changed_chunks = sum(1 for cid, thash in chunk_index.items() if previous_index.get(cid) != thash)
    removed_chunks = len(set(previous_index.keys()) - set(chunk_index.keys()))

    LOG.info(
        "Chunk export complete: %s chunks total, %s changed/new, %s removed.",
        len(all_chunks),
        changed_chunks,
        removed_chunks,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
