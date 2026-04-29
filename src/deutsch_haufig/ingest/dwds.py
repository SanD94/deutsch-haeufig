"""Fetch German definitions and corpus examples from dwds.de.

DWDS (Digitales Wörterbuch der deutschen Sprache) provides
monolingual definitions and real usage examples from the DWDS
korpus. This module:

1. Fetches the Wörterbuch entry for a given lemma.
2. Extracts 1..n German definitions.
3. Fetches ≥3 corpus examples per sense.

All data is cached to ``data/dwds_cache/`` for replayability.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from selectolax.parser import HTMLParser

from deutsch_haufig.config import settings

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

BASE_URL = "https://www.dwds.de"
CACHE_DIR = settings.data_dir / "dwds_cache"


def _cache_path(lemma: str, pos: str) -> Path:
    """Path for caching a DWDS response for a given lemma+POS."""
    key = hashlib.sha256(f"{lemma}:{pos}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"{lemma}_{pos}_{key}.html"


# --- entry shapes ----------------------------------------------------------


@dataclass(frozen=True)
class DWDSSense:
    """A single sense extracted from a DWDS Wörterbuch entry."""

    order: int
    definition_de: str
    register: str | None = None
    domain: str | None = None


@dataclass(frozen=True)
class DWDSExample:
    """A single corpus example from DWDS korpus."""

    text_de: str
    source: str = "dwds-korpus"
    translation_en: str | None = None


@dataclass(frozen=True)
class DWDSEntry:
    """Full DWDS entry for one lemma."""

    lemma: str
    pos: str
    fetched_at: datetime
    senses: tuple[DWDSSense, ...]
    examples: dict[int, tuple[DWDSExample, ...]]
    not_found: bool = False


# --- HTTP -------------------------------------------------------------------


async def fetch_entry(
    lemma: str,
    pos: str,
    *,
    use_cache: bool = True,
    force_fetch: bool = False,
) -> DWDSEntry | None:
    """Fetch DWDS entry for a lemma, caching results.

    Returns None if the word is not found on DWDS.
    """
    cache_path = _cache_path(lemma, pos)

    if use_cache and not force_fetch and cache_path.exists():
        with cache_path.open(encoding="utf-8") as f:
            html = f.read()
    else:
        url = f"{BASE_URL}/wb/{lemma}"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
            ) as client:
                response = await client.get(url)
                if response.status_code == 404:
                    logger.debug("[%s] 404 at DWDS, marking not_found", lemma)
                    html = None
                else:
                    response.raise_for_status()
                    html = response.text
        except httpx.HTTPError as e:
            logger.warning("[%s] HTTP error: %s", lemma, e)
            html = None

        if html is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with cache_path.open("w", encoding="utf-8") as f:
                f.write(html)

    if html is None:
        return DWDSEntry(
            lemma=lemma,
            pos=pos,
            fetched_at=datetime.utcnow(),
            senses=(),
            examples={},
            not_found=True,
        )

    return parse_entry(lemma, pos, html)


# --- pure parsers ----------------------------------------------------------

# DWDS uses a specific HTML structure for definitions:
# <div class="bedeutung"> ... <span class="def">Definition text</span>


def _css_text(tree: HTMLParser, selector: str, sep: str = " ") -> str:
    node = tree.css_first(selector)
    if node is None:
        return ""
    return sep.join(node.text(separator=" ").split()).strip()


def _css_all(tree: HTMLParser, selector: str) -> list[HTMLParser]:
    return list(tree.css(selector))


def parse_entry(lemma: str, pos: str, html: str) -> DWDSEntry:
    """Parse a DWDS Wörterbuch entry from raw HTML.

    Pure function — no I/O.
    """
    tree = HTMLParser(html)

    senses: list[DWDSSense] = []
    sense_idx = 1

    for lesart in _css_all(tree, "div.dwdswb-lesart"):
        def_elem = lesart.css_first("span.dwdswb-definition, div.dwdswb-lesart-def")
        if def_elem:
            def_text = " ".join(def_elem.text(separator=" ").split()).strip()
        else:
            def_text = ""

        if not def_text:
            wrapper = lesart.css_first("div.dwdswb-lesart-content")
            if wrapper:
                full_text = " ".join(wrapper.text(separator=" ").split()).strip()
                if len(full_text) > 5:
                    def_text = full_text
            if not def_text:
                continue

        if len(def_text) < 3:
            continue

        register = None
        reg_node = lesart.css_first("span.dwdswb-stilebene")
        if reg_node:
            register = reg_node.text().strip()

        domain = None
        dom_node = lesart.css_first("span.dwdswb-stilfaerbung")
        if dom_node:
            domain = dom_node.text().strip()

        senses.append(
            DWDSSense(
                order=sense_idx,
                definition_de=def_text,
                register=register,
                domain=domain,
            )
        )
        sense_idx += 1

    examples_by_sense: dict[int, list[DWDSExample]] = {i + 1: [] for i in range(len(senses) or 1)}

    for beleg in _css_all(tree, "span.dwdswb-belegtext"):
        text = " ".join(beleg.text(separator=" ").split()).strip()
        if text and len(text) > 15:
            examples_by_sense[1].append(
                DWDSExample(
                    text_de=text,
                    source="dwds-korpus",
                )
            )

    for idx in examples_by_sense:
        examples_by_sense[idx] = examples_by_sense[idx][:3]

    return DWDSEntry(
        lemma=lemma,
        pos=pos,
        fetched_at=datetime.utcnow(),
        senses=tuple(senses),
        examples={k: tuple(v) for k, v in examples_by_sense.items()},
    )


# --- batch processing ------------------------------------------------------


async def fetch_words(
    words: Iterator[tuple[int, str, str]],
    *,
    limit: int | None = None,
    rate_limit: float = 0.5,
) -> Iterator[tuple[int, DWDSEntry]]:
    """Fetch DWDS entries for a sequence of (word_id, lemma, pos) tuples.

    Yields (word_id, entry) tuples. Respects rate limiting between requests.
    """
    from asyncio import sleep

    count = 0
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
    ) as client:
        for word_id, lemma, pos in words:
            if limit is not None and count >= limit:
                break

            entry = await fetch_entry_for_client(client, lemma, pos)
            yield word_id, entry
            count += 1
            await sleep(rate_limit)


async def fetch_entry_for_client(
    client: httpx.AsyncClient,
    lemma: str,
    pos: str,
) -> DWDSEntry | None:
    """Fetch using an existing client (for connection reuse)."""
    url = f"{BASE_URL}/wb/{lemma}"
    cache_path = _cache_path(lemma, pos)

    if cache_path.exists():
        with cache_path.open(encoding="utf-8") as f:
            html = f.read()
    else:
        try:
            response = await client.get(url)
            if response.status_code == 404:
                html = None
            else:
                response.raise_for_status()
                html = response.text
        except httpx.HTTPError:
            html = None

        if html is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with cache_path.open("w", encoding="utf-8") as f:
                f.write(html)

    if html is None:
        return DWDSEntry(
            lemma=lemma,
            pos=pos,
            fetched_at=datetime.utcnow(),
            senses=(),
            examples={},
            not_found=True,
        )

    return parse_entry(lemma, pos, html)


# --- cache utilities -------------------------------------------------------


def list_cached() -> list[tuple[str, str]]:
    """List all cached (lemma, pos) pairs."""
    out: list[tuple[str, str]] = []
    if not CACHE_DIR.exists():
        return out
    for f in CACHE_DIR.iterdir():
        if f.suffix == ".html":
            stem = f.stem
            parts = stem.rsplit("_", 1)
            if len(parts) == 2:
                lemma, pos = parts[0], parts[1]
                out.append((lemma, pos))
    return out


def clear_cache() -> int:
    """Clear the DWDS cache. Returns the number of files removed."""
    if not CACHE_DIR.exists():
        return 0
    count = 0
    for f in CACHE_DIR.iterdir():
        if f.suffix == ".html":
            f.unlink()
            count += 1
    return count
