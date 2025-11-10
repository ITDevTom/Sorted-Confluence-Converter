from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify as md

from .utils import chunk_sentences, sha256_text, slugify_path, slugify_text, split_into_sentences

LOG = logging.getLogger(__name__)

HEADING_TAGS = {"h1", "h2", "h3"}


@dataclass
class Section:
    id: str
    title: str
    body_md: str
    anchors: List[str]
    table_json: Optional[List[dict]] = None


def _clean_html(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html or "", "html.parser")

    for tag in soup(["script", "style"]):
        tag.decompose()

    for tag in soup.find_all(lambda t: isinstance(t, Tag) and ":" in t.name):
        # Replace Confluence macro nodes with their visible text.
        text = tag.get_text(" ", strip=True)
        if text:
            tag.replace_with(text)
        else:
            tag.decompose()

    for tag in soup.find_all(["span", "div"]):
        tag.unwrap()

    return soup


def _html_to_markdown(soup: BeautifulSoup) -> str:
    # markdownify expects a string input.
    markdown = md(
        str(soup),
        heading_style="ATX",
        convert=["table", "ol", "ul"],
    )
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    return markdown


def _split_sections(markdown: str) -> List[Section]:
    if not markdown.strip():
        return [
            Section(
                id="overview",
                title="Overview",
                body_md="",
                anchors=["overview"],
            )
        ]

    sections: List[Section] = []
    current_title = "Overview"
    current_lines: List[str] = []

    def flush_section(title: str, lines: List[str]) -> None:
        body = "\n".join(lines).strip()
        slug = slugify_text(title)
        sections.append(
            Section(
                id=slug,
                title=title.strip() or "Untitled Section",
                body_md=body,
                anchors=[slug],
            )
        )

    heading_pattern = re.compile(r"^(#{1,3})\s+(.*)")
    for line in markdown.splitlines():
        match = heading_pattern.match(line)
        if match:
            if current_lines:
                flush_section(current_title, current_lines)
            heading = match.group(2).strip()
            current_title = heading or "Untitled Section"
            current_lines = []
            continue
        current_lines.append(line)

    flush_section(current_title, current_lines)
    return sections


def _extract_table(table: Tag) -> dict:
    headers: List[str] = []
    display_headers: List[str] = []
    body_rows: List[dict] = []

    header_cells = table.find_all("th")
    if not header_cells:
        first_row = table.find("tr")
        if first_row:
            header_cells = first_row.find_all("td")
            if header_cells:
                first_row.extract()

    for cell in header_cells:
        text = cell.get_text(" ", strip=True) or f"Column {len(headers)+1}"
        display_headers.append(text)
        headers.append(slugify_text(text))

    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        row_data: dict = {}
        for idx, cell in enumerate(cells):
            while idx >= len(headers):
                fallback_name = f"Column {len(headers)+1}"
                display_headers.append(fallback_name)
                headers.append(slugify_text(fallback_name))
            key = headers[idx]
            value = cell.get_text(" ", strip=True)
            value = _maybe_split_list(value)
            row_data[key] = value
        if row_data:
            body_rows.append(row_data)

    return {
        "columns": headers,
        "display_columns": display_headers,
        "rows": body_rows,
    }


def _maybe_split_list(value: str | List[str]) -> str | List[str]:
    if not isinstance(value, str):
        return value
    if ";" in value:
        parts = [part.strip() for part in value.split(";") if part.strip()]
        if len(parts) > 1:
            return parts
    if "," in value:
        parts = [part.strip() for part in value.split(",") if part.strip()]
        if len(parts) > 1:
            return parts
    return value


def _map_tables_to_sections(soup: BeautifulSoup) -> Dict[str, List[dict]]:
    mapping: Dict[str, List[dict]] = {}
    for table in soup.find_all("table"):
        heading = table.find_previous(HEADING_TAGS)
        if heading and heading.get_text(strip=True):
            section_id = slugify_text(heading.get_text(strip=True))
        else:
            section_id = "overview"
        table_data = _extract_table(table)
        mapping.setdefault(section_id, []).append(table_data)
    return mapping


def build_document(
    page: Dict,
    markdown: str,
    sections: List[Section],
    table_mapping: Dict[str, List[dict]],
    *,
    space: str,
    base_url: str,
) -> Tuple[dict, List[dict], Dict[str, str]]:
    page_id = str(page.get("id"))
    title = page.get("title", "Untitled Page")
    version_info = page.get("version", {}) or {}
    version_number = str(version_info.get("number", "1"))
    version_when = version_info.get("when")
    ancestors = page.get("ancestors", []) or []

    ancestor_titles = [ancestor.get("title", "") for ancestor in ancestors]
    slug_parts = ancestor_titles + [title]
    slug = slugify_path(slug_parts)

    last4 = page_id[-4:].rjust(4, "0")
    doc_id = f"{space}-{slug.replace('/', '-')}-{last4}"
    webui = page.get("_links", {}).get("webui") if page.get("_links") else None
    canonical_url = f"{base_url}{webui}" if webui else None
    imported_at = dt.datetime.now(dt.timezone.utc).isoformat()

    for section in sections:
        tables = table_mapping.get(section.id)
        if tables:
            section.table_json = tables

    sections_payload: List[dict] = []
    for section in sections:
        payload = {
            "id": section.id,
            "title": section.title,
            "body_md": section.body_md,
            "anchors": section.anchors,
        }
        if section.table_json:
            payload["table_json"] = section.table_json
        sections_payload.append(payload)

    doc = {
        "id": doc_id,
        "slug": slug,
        "title": title,
        "version": version_number,
        "language": "en-GB",
        "status": "published",
        "product": None,
        "audience": ["internal-support"],
        "tags": [slugify_text(title), space],
        "domain": ["sorted"],
        "summary": None,
        "source": {
            "system": "Confluence",
            "space": space,
            "page_id": page_id,
            "canonical_url": canonical_url,
            "imported_at": imported_at,
        },
        "owners": [{"name": "Support Ops"}],
        "applicability": {
            "environments": ["Sandbox", "Production"],
            "customers": ["*"],
            "carriers": ["*"],
        },
        "compliance": {"pii": False, "confidential": "internal"},
        "history": [
            {
                "version": version_number,
                "changed_at": version_when or imported_at,
                "notes": "Imported",
            }
        ],
        "sections": sections_payload,
        "chunks": [],
        "related": [],
    }

    chunks: List[dict] = []
    chunk_index: Dict[str, str] = {}
    rank = 0
    doc_keywords = {slugify_text(title), space.lower(), space}

    for section in sections:
        keywords = set(doc_keywords)
        keywords.add(slugify_text(section.title))
        keywords.update({"sandbox", "production"})

        if not section.body_md.strip():
            continue

        sentences = split_into_sentences(section.body_md)
        for idx, chunk_text in enumerate(chunk_sentences(sentences)):
            chunk_id = f"{doc_id}::{section.id}#{rank}"
            text_hash = sha256_text(chunk_text)
            chunk_payload = {
                "chunk_id": chunk_id,
                "section_id": section.id,
                "rank": rank,
                "text": chunk_text,
                "keywords": sorted(keywords),
                "anchors": section.anchors,
                "text_hash": text_hash,
            }
            chunks.append(chunk_payload)
            doc["chunks"].append(chunk_payload)
            chunk_index[chunk_id] = text_hash
            rank += 1

    return doc, chunks, chunk_index


def convert_page(
    page: Dict,
    *,
    space: str,
    base_url: str,
) -> Tuple[dict, List[dict], Dict[str, str]]:
    body = page.get("body", {}).get("storage", {}).get("value", "") or ""
    soup = _clean_html(body)
    markdown = _html_to_markdown(soup)
    sections = _split_sections(markdown)
    table_mapping = _map_tables_to_sections(soup)
    return build_document(
        page,
        markdown,
        sections,
        table_mapping,
        space=space,
        base_url=base_url,
    )
