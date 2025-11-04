from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional

import requests
from requests.auth import HTTPBasicAuth
from requests.session import Session

LOG = logging.getLogger(__name__)


@dataclass
class ConfluenceConfig:
    base_url: str
    email: str
    api_token: str


class ConfluenceClient:
    """Wrapper around the Confluence Cloud REST API."""

    def __init__(self, config: ConfluenceConfig) -> None:
        self._config = config
        self._session: Session = requests.Session()
        self._session.auth = HTTPBasicAuth(config.email, config.api_token)
        self._session.headers.update({"Accept": "application/json"})

    def fetch_page(self, page_id: str) -> Dict:
        url = f"{self._config.base_url}/rest/api/content/{page_id}"
        params = {"expand": "body.storage,version,ancestors"}
        LOG.debug("Fetching page %s", page_id)
        response = self._session.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def fetch_children_ids(self, page_id: str) -> List[str]:
        url = f"{self._config.base_url}/rest/api/content/{page_id}/child/page"
        children: List[str] = []
        start = 0
        limit = 50

        while True:
            params = {"start": start, "limit": limit}
            LOG.debug("Fetching children of %s (start=%s)", page_id, start)
            response = self._session.get(url, params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()
            results = payload.get("results", [])
            children.extend([str(result["id"]) for result in results if "id" in result])
            if payload.get("_links", {}).get("next") is None:
                break
            start += limit

        return children

    def traverse_descendants(self, root_id: str, include_children: bool) -> Iterator[str]:
        """Yield page IDs to process, starting with the root and optionally all descendants."""
        yield root_id
        if not include_children:
            return

        queue: List[str] = [root_id]
        seen = {root_id}
        while queue:
            current = queue.pop(0)
            for child_id in self.fetch_children_ids(current):
                if child_id in seen:
                    continue
                seen.add(child_id)
                queue.append(child_id)
                yield child_id

