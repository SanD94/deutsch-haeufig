"""Collocation extraction from DWDS "Typische Verbindungen" section.

DWDS pages include a "Typische Verbindungen" section that lists common
word combinations (collocations) with frequency data. This module
extracts them from already-cached DWDS HTML.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from selectolax.parser import HTMLParser

from deutsch_haufig.ingest.dwds import _cache_path


@dataclass(frozen=True)
class CollocationEntry:
    """A single collocation extracted from DWDS."""

    collocate: str
    category: str
    frequency: int


def parse_collocations(html: str) -> list[CollocationEntry]:
    tree = HTMLParser(html)
    container = tree.css_first("div.wp-article-cloud div.htmltagcloud")
    if container is None:
        return []

    results: list[CollocationEntry] = []
    for item in container.css("span[class^='wp-t']"):
        collocate_el = item.css_first("a")
        if collocate_el is None:
            continue
        collocate = collocate_el.text(strip=True)
        if not collocate or len(collocate) < 2:
            continue

        # Extract frequency from wp-tN class
        freq = 0
        for cls in item.attributes.get("class", "").split():
            if cls.startswith("wp-t"):
                try:
                    freq = int(cls[4:])
                except (ValueError, TypeError):
                    pass
                break

        # Determine POS category from wp-pos-N class
        category = "other"
        for cls in item.attributes.get("class", "").split():
            if cls.startswith("wp-pos-"):
                category = cls[7:]
                break

        results.append(CollocationEntry(
            collocate=collocate,
            category=category,
            frequency=freq,
        ))

    return results


def _normalize_category(raw: str) -> str:
    raw = raw.strip().lower()
    mapping = {
        "subjekt": "subject",
        "objekt": "object",
        "attribut": "attribute",
        "adjektivattribut": "attribute",
        "genitivattribut": "attribute",
        "präpositionalgruppe": "prepositional",
        "adverbial": "adverbial",
        "verbal": "verbal",
    }
    return mapping.get(raw, "other")


def extract_for_lemma(lemma: str, pos: str) -> list[CollocationEntry]:
    cache_path = _cache_path(lemma, pos)
    if not cache_path.exists():
        return []
    html = cache_path.read_text(encoding="utf-8")
    return parse_collocations(html)


def batch_extract(
    words: list[tuple[int, str, str]],
) -> Iterator[tuple[int, list[CollocationEntry]]]:
    for word_id, lemma, pos in words:
        entries = extract_for_lemma(lemma, pos)
        if entries:
            yield word_id, entries
