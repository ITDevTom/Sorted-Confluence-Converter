from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Iterable, List, Sequence

from slugify import slugify

LOG = logging.getLogger(__name__)


def slugify_text(value: str, separator: str = "-") -> str:
    """Create a deterministic slug for headings, ids, etc."""
    return slugify(value or "unnamed", separator=separator)


def slugify_path(parts: Sequence[str]) -> str:
    """Build a nested slug path from a list of path components."""
    return "/".join(slugify_text(part, separator="-") for part in parts if part)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_sentence_splitter = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def split_into_sentences(text: str) -> List[str]:
    """Split text into coarse sentences, keeping bullet/numbered lines intact."""
    if not text:
        return []
    lines: List[str] = []
    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("-", "*", "+", ">")) or re.match(r"^\d+\.", line):
            lines.append(line)
            continue
        sentences = [segment.strip() for segment in _sentence_splitter.split(line) if segment.strip()]
        if sentences:
            lines.extend(sentences)
        else:
            lines.append(line)
    return lines


def chunk_sentences(
    sentences: Sequence[str],
    target_chars: int = 2000,
    max_chars: int = 3600,
) -> List[str]:
    """Group sentences into chunks using simple character-length heuristics."""
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    for sentence in sentences:
        sentence_len = len(sentence)
        if current and (current_len + sentence_len + 1 > max_chars):
            chunks.append("\n".join(current).strip())
            current = []
            current_len = 0

        current.append(sentence)
        current_len += sentence_len + 1

        if current_len >= target_chars:
            chunks.append("\n".join(current).strip())
            current = []
            current_len = 0

    if current:
        chunks.append("\n".join(current).strip())

    return chunks


def ensure_directory(path: str | Path) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def load_json(path: str | Path) -> dict:
    if not Path(path).exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str | Path, payload: dict) -> None:
    ensure_directory(Path(path).parent)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def write_jsonl(path: str | Path, items: Iterable[dict]) -> None:
    ensure_directory(Path(path).parent)
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False))
            f.write("\n")


def copy_env_example(example_path: Path, env_path: Path) -> None:
    """Copy the .env.example file to .env when .env is missing."""
    if env_path.exists():
        return
    if not example_path.exists():
        LOG.warning("No .env.example present to copy.")
        return
    env_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
    LOG.info("Created %s from %s", env_path, example_path)
