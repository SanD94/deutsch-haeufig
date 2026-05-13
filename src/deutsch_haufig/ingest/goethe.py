"""Fetch and parse DWDS Goethe-Zertifikat word lists.

M1-DWDS seed source. Uses the official DWDS API endpoints:

  https://www.dwds.de/api/lemma/goethe/{A1,A2,B1}.csv

Each CSV row contains: Lemma, URL, Wortart, Genus, Artikel, nur_im_Plural.

Usage::

    from deutsch_haufig.ingest.goethe import fetch_goethe_list, parse_goethe_csv

    csv_text = fetch_goethe_list("A1")
    entries = parse_goethe_csv(csv_text, level="A1")
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from deutsch_haufig.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://www.dwds.de/api/lemma/goethe"
CACHE_DIR = settings.data_dir / "goethe"

# Mapping from DWDS Wortart to our canonical POS tags
POS_MAP: dict[str, str] = {
    "Adjektiv": "adj",
    "Adverb": "adv",
    "Affix": "affix",
    "bestimmter Artikel": "article",
    "Bruchzahlwort": "num",
    "Demonstrativpronomen": "pron",
    "Eigenname": "noun",
    "Indefinitpronomen": "pron",
    "Interjektion": "interj",
    "Interrogativpronomen": "pron",
    "Kardinalzahlwort": "num",
    "Konjunktion": "conj",
    "Mehrwortausdruck": "phrase",
    "Ordinalzahlwort": "num",
    "Partikel": "particle",
    "Personalpronomen": "pron",
    "Possessivpronomen": "pron",
    "Präposition": "prep",
    "Pronomen": "pron",
    "Pronominaladverb": "adv",
    "Reflexivpronomen": "pron",
    "Relativpronomen": "pron",
    "Reziprokes Pronomen": "pron",
    "Substantiv": "noun",
    "Verb": "verb",
}


@dataclass(frozen=True)
class GoetheEntry:
    """One word from a DWDS Goethe-Zertifikat CSV list."""

    lemma: str
    url: str
    pos: str
    level: str
    article: str | None = None
    genus: str | None = None
    only_plural: bool = False

    @property
    def source_ref(self) -> str:
        return f"dwds:goethe:{self.level}"


def _normalize_pos(dwds_pos: str) -> str:
    """Map a DWDS Wortart string to our canonical POS tag."""
    return POS_MAP.get(dwds_pos.strip(), dwds_pos.strip().lower())


def parse_goethe_csv(text: str, *, level: str) -> list[GoetheEntry]:
    """Parse a raw DWDS Goethe CSV string into a list of ``GoetheEntry``.

    Pure function — no I/O.

    CSV columns: Lemma, URL, Wortart, Genus, Artikel, nur_im_Plural
    """
    entries: list[GoetheEntry] = []
    reader = csv.DictReader(io.StringIO(text))

    for row in reader:
        lemma = row.get("Lemma", "").strip()
        url = row.get("URL", "").strip()
        wortart = row.get("Wortart", "").strip()
        genus = row.get("Genus", "").strip() or None
        artikel = row.get("Artikel", "").strip() or None
        nur_plural = row.get("nur_im_Plural", "0").strip() == "1"

        if not lemma or not wortart:
            continue

        pos = _normalize_pos(wortart)

        entries.append(
            GoetheEntry(
                lemma=lemma,
                url=url,
                pos=pos,
                level=level,
                article=artikel,
                genus=genus,
                only_plural=nur_plural,
            )
        )

    return entries


# --- HTTP fetching -----------------------------------------------------------


def _cache_path(level: str) -> Path:
    """Path for caching a raw Goethe CSV for a given level."""
    return CACHE_DIR / f"goethe_{level}.csv"


async def fetch_goethe_list(
    level: str,
    *,
    use_cache: bool = True,
    force_fetch: bool = False,
) -> str:
    """Fetch a DWDS Goethe-Zertifikat CSV for the given level (A1, A2, B1).

    Returns raw CSV text. Caches to ``data/goethe/`` on first fetch.
    """
    level = level.upper()
    if level not in ("A1", "A2", "B1"):
        msg = f"invalid level: {level!r} (expected A1, A2, or B1)"
        raise ValueError(msg)

    cache_path = _cache_path(level)

    if use_cache and not force_fetch and cache_path.exists():
        logger.debug("[goethe:%s] loading from cache", level)
        return cache_path.read_text(encoding="utf-8")

    url = f"{BASE_URL}/{level}.csv"
    logger.info("[goethe:%s] fetching %s", level, url)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        text = response.text

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")

    return text


async def fetch_all_goethe_lists(
    *,
    use_cache: bool = True,
    force_fetch: bool = False,
) -> dict[str, list[GoetheEntry]]:
    """Fetch and parse all three Goethe levels.

    Returns ``{"A1": [...], "A2": [...], "B1": [...]}``.
    """
    result: dict[str, list[GoetheEntry]] = {}
    for level in ("A1", "A2", "B1"):
        csv_text = await fetch_goethe_list(level, use_cache=use_cache, force_fetch=force_fetch)
        entries = parse_goethe_csv(csv_text, level=level)
        result[level] = entries
        logger.info("[goethe:%s] parsed %d entries", level, len(entries))
    return result
