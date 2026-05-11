"""Verb conjugation table from Verbformen (www.verbformen.de).

Fetches and parses the conjugation table for a German verb, storing
results in the ``Conjugation`` model.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
from selectolax.parser import HTMLParser

from deutsch_haufig.config import settings

logger = logging.getLogger(__name__)

CACHE_DIR = settings.data_dir / "dwds_cache"
VERBFORMEN_URL = "https://www.verbformen.de/konjugation"


TENSES = (
    ("Präsens", ("ich", "du", "er/sie/es", "wir", "ihr", "sie")),
    ("Präteritum", ("ich", "du", "er/sie/es", "wir", "ihr", "sie")),
    ("Perfekt", ("ich", "du", "er/sie/es", "wir", "ihr", "sie")),
    ("Plusquamperfekt", ("ich", "du", "er/sie/es", "wir", "ihr", "sie")),
    ("Futur I", ("ich", "du", "er/sie/es", "wir", "ihr", "sie")),
    ("Futur II", ("ich", "du", "er/sie/es", "wir", "ihr", "sie")),
)


@dataclass(frozen=True)
class ConjugationEntry:
    """A single conjugated form."""

    tense: str
    pronoun: str
    form: str


def _cache_path(lemma: str) -> Path:
    key = hashlib.sha256(lemma.encode()).hexdigest()[:16]
    return CACHE_DIR / f"verbformen_{lemma}_{key}.html"


async def fetch_conjugations(
    lemma: str, *, use_cache: bool = True
) -> list[ConjugationEntry] | None:
    """Fetch conjugation table for *lemma* from verbformen.de."""
    cache_path = _cache_path(lemma)

    if use_cache and cache_path.exists():
        html = cache_path.read_text(encoding="utf-8")
    else:
        url = f"{VERBFORMEN_URL}/{lemma}.htm"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(15.0), follow_redirects=True
            ) as client:
                resp = await client.get(url)
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                html = resp.text
        except httpx.HTTPError as e:
            logger.warning("[verbformen] %s: %s", lemma, e)
            return None

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(html, encoding="utf-8")

    return parse_conjugations(html)


def parse_conjugations(html: str) -> list[ConjugationEntry]:
    """Parse Verbformen HTML into conjugation entries.

    Verbformen uses a table with id ``#konjugation`` containing rows
    with class ``.row1`` / ``.row2`` and cells for each pronoun.
    """
    tree = HTMLParser(html)
    results: list[ConjugationEntry] = []

    # Try to find the main conjugation table
    table = tree.css_first("table#konjugation, div.konjugation table")
    if table is None:
        return results

    tense_names = list(dict.fromkeys(t[0] for t in TENSES))  # unique, ordered
    tense_idx = 0
    for row in table.css("tr"):
        cells = row.css("td")
        if len(cells) < 7:
            continue

        # First cell is the tense/subject label
        first = cells[0].text(strip=True)
        # Map to pronoun
        pronouns = ("ich", "du", "er/sie/es", "wir", "ihr", "sie")

        # Check if this is a tense header row
        header = row.css_first("th")
        if header:
            header_text = header.text(strip=True).lower()
            for i, tn in enumerate(tense_names):
                if tn.lower() in header_text:
                    tense_idx = i
                    break
            continue

        # Find which pronoun this row corresponds to
        if first in pronouns:
            pronoun = first
            for _i, cell in enumerate(cells[1:7], 1):
                form = cell.text(strip=True)
                if form and form != "—" and form != "–":
                    tense_name = tense_names[tense_idx] if tense_idx < len(tense_names) else ""
                    if tense_name:
                        results.append(
                            ConjugationEntry(
                                tense=tense_name,
                                pronoun=pronoun,
                                form=form,
                            )
                        )
            tense_idx = min(tense_idx + 1, len(tense_names) - 1)

    return results


def batch_fetch(
    lemmas: list[str],
    *,
    rate_limit: float = 0.3,
) -> Iterator[tuple[str, list[ConjugationEntry] | None]]:
    """Fetch conjugations for multiple lemmas."""
    import asyncio

    async def _run():
        for lemma in lemmas:
            result = await fetch_conjugations(lemma)
            yield lemma, result
            await asyncio.sleep(rate_limit)

    async for item in _run():  # noqa: UP028
        yield item
