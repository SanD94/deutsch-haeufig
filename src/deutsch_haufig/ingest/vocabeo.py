"""Scrape vocabeo.com for a frequency-ranked German seed corpus.

vocabeo.com/browse is rendered by a SvelteKit SPA, so the underlying word
list is not in the static HTML.  The site, however, exposes server-rendered
*"100 most common …"* pages under /german-vocabulary/, plus a couple of
themed pages (colors, numbers).  Together those cover the top several
hundred most-frequent A1 words — exactly the slice the PoC needs (PLAN §7
asks for ~200 A1 words).

Each row on those pages looks like::

    <div class="row svelte-p4dir4">
      <div>
        <span class="german-verb …">LEMMA</span> -
        <span class="english-verb …">EN_GLOSS</span>
      </div>
      <div>German example sentence …</div>
      <div class="english-sentence …">English translation …</div>
      <button class="dictionary-link …">…</button>
    </div>

For nouns the lemma carries the article suffix ("Uhr, die"); we strip it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx
from selectolax.parser import HTMLParser, Node

logger = logging.getLogger(__name__)


# --- source pages ----------------------------------------------------------


@dataclass(frozen=True)
class SourcePage:
    """One scrape target on vocabeo.com."""

    url: str
    pos: str
    category: str
    level: str | None = "A1"


SOURCE_PAGES: tuple[SourcePage, ...] = (
    SourcePage(
        "https://vocabeo.com/german-vocabulary/100-most-common-german-verbs",
        pos="verb",
        category="Common verbs",
    ),
    SourcePage(
        "https://vocabeo.com/german-vocabulary/100-most-common-german-nouns",
        pos="noun",
        category="Common nouns",
    ),
    SourcePage(
        "https://vocabeo.com/german-vocabulary/100-most-common-german-adjectives",
        pos="adj",
        category="Common adjectives",
    ),
    SourcePage(
        "https://vocabeo.com/german-vocabulary/colors-in-german",
        pos="adj",
        category="Colors",
    ),
    SourcePage(
        "https://vocabeo.com/german-vocabulary/numbers-in-german",
        pos="num",
        category="Numbers",
    ),
)


# --- entry shape -----------------------------------------------------------


@dataclass(frozen=True)
class VocabeoEntry:
    """Raw seed entry; mirrors the JSONL written to disk."""

    lemma: str
    article: str | None
    pos: str
    level: str | None
    frequency: int
    category: str
    en_gloss: str
    example_de: str | None
    example_en: str | None
    source_ref: str  # e.g. "vocabeo:100-most-common-german-verbs#7"


# --- parser ----------------------------------------------------------------


_ARTICLES = {"der", "die", "das"}


def _strip_decorations(text: str) -> str:
    """Remove trailing emoji / symbol decorations (e.g. ``"rot 🔴"`` → ``"rot"``)."""
    text = " ".join(text.split()).strip()
    # Drop trailing non-letter tokens.  We keep tokens that contain at least
    # one alphabetic character (covers German ä/ö/ü/ß and digits-with-text).
    parts = text.split()
    while parts and not any(ch.isalpha() for ch in parts[-1]):
        parts.pop()
    return " ".join(parts)


def _split_lemma(raw: str, pos: str) -> tuple[str, str | None]:
    """Split a vocabeo lemma cell into (lemma, article).

    Conventions across vocabeo's SSR pages:

    - Nouns: ``"Uhr, die"`` / ``"Computer, der"``  → strip the article.
    - Numbers: ``"0 - null"`` / ``"21 - einundzwanzig"`` → keep the word.
    - Colors: ``"rot 🔴"``                        → strip the emoji tail.
    """
    text = _strip_decorations(raw)
    if pos == "num" and " - " in text:
        # "0 - null" → "null"
        _digits, _, word = text.partition(" - ")
        text = _strip_decorations(word) or text
        return text, None
    if pos == "noun" and "," in text:
        head, _, tail = text.rpartition(",")
        tail = tail.strip()
        head = head.strip()
        if tail in _ARTICLES and head:
            return head, tail
    return text, None


def _bucket_frequency(rank: int, total: int) -> int:
    """Map a 1-based rank within a page to a 1..5 frequency bucket.

    Higher == more frequent.  Top fifth of the page → 5, bottom fifth → 1.
    Matches vocabeo's own 5-level UI bucket.
    """
    if total <= 0 or rank < 1:
        return 1
    # Map ranks evenly into 5 buckets, with rank 1 → bucket 5.
    fifth = max(1, (total + 4) // 5)
    bucket = 5 - min(4, (rank - 1) // fifth)
    return max(1, min(5, bucket))


def _row_text(div: Node) -> str:
    return " ".join(div.text(separator=" ").split()).strip()


def parse_browse_page(
    html: str,
    *,
    pos: str,
    category: str,
    level: str | None = "A1",
    source_slug: str = "vocabeo",
) -> list[VocabeoEntry]:
    """Parse one server-rendered vocabeo vocabulary page into entries.

    Pure function over a HTML string so it can be exercised by fixtures.
    Skips CTA / divider rows that re-use the same outer ``row`` markup.
    """
    tree = HTMLParser(html)
    entries: list[VocabeoEntry] = []
    rows = tree.css("div.row")
    # First pass: keep only word rows (one with a german-* span).
    word_rows: list[Node] = []
    for row in rows:
        gerry = row.css_first("span[class^='german-']") or row.css_first("span[class*=' german-']")
        if gerry is None:
            continue
        word_rows.append(row)

    total = len(word_rows)
    for rank, row in enumerate(word_rows, start=1):
        gerry = row.css_first("span[class^='german-']") or row.css_first("span[class*=' german-']")
        engy = row.css_first("span[class^='english-']") or row.css_first("span[class*=' english-']")
        if gerry is None or engy is None:
            continue
        raw_lemma = gerry.text(strip=True)
        en_gloss = " ".join(engy.text(separator=" ").split()).strip()
        lemma, article = _split_lemma(raw_lemma, pos)
        if not lemma:
            continue

        # Example sentence + translation are sibling <div>s of the lemma row.
        # The translation div has class="english-sentence …".
        example_de: str | None = None
        example_en: str | None = None
        for child in row.css("div"):
            classes = (child.attributes.get("class") or "").split()
            if "english-sentence" in classes:
                example_en = _row_text(child) or None
                continue
            # Skip the lemma+gloss container (it holds the german-* span).
            if child.css_first("span[class^='german-']") is not None:
                continue
            if example_de is None:
                txt = _row_text(child)
                if txt:
                    example_de = txt

        entries.append(
            VocabeoEntry(
                lemma=lemma,
                article=article,
                pos=pos,
                level=level,
                frequency=_bucket_frequency(rank, total),
                category=category,
                en_gloss=en_gloss,
                example_de=example_de,
                example_en=example_en,
                source_ref=f"{source_slug}#{rank}",
            )
        )
    return entries


# --- fetcher + cache -------------------------------------------------------


def _cache_path(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    safe = url.rsplit("/", 1)[-1] or "index"
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in safe)
    return cache_dir / f"{safe}-{digest}.html"


async def fetch_html(
    client: httpx.AsyncClient,
    url: str,
    cache_dir: Path,
    *,
    force: bool = False,
) -> str:
    """GET ``url`` with on-disk HTML cache.  Returns the response body."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, url)
    if path.exists() and not force:
        logger.debug("cache hit: %s", path.name)
        return path.read_text(encoding="utf-8")
    logger.info("fetching %s", url)
    resp = await client.get(url, headers={"User-Agent": "deutsch-haufig/0.1 (+seed)"})
    resp.raise_for_status()
    body = resp.text
    path.write_text(body, encoding="utf-8")
    return body


# --- pipeline glue ---------------------------------------------------------


async def scrape_pages(
    pages: Iterable[SourcePage],
    cache_dir: Path,
    *,
    rate_limit_seconds: float = 1.0,
    force: bool = False,
) -> list[VocabeoEntry]:
    """Fetch each source page (≥ ``rate_limit_seconds`` apart) and parse it."""
    out: list[VocabeoEntry] = []
    pages = list(pages)
    timeout = httpx.Timeout(20.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for i, page in enumerate(pages):
            if i > 0:
                await asyncio.sleep(rate_limit_seconds)
            html = await fetch_html(client, page.url, cache_dir, force=force)
            slug = page.url.rsplit("/", 1)[-1]
            entries = parse_browse_page(
                html,
                pos=page.pos,
                category=page.category,
                level=page.level,
                source_slug=f"vocabeo:{slug}",
            )
            logger.info("parsed %d entries from %s", len(entries), slug)
            out.extend(entries)
    return out


def write_jsonl(entries: Iterable[VocabeoEntry], out_path: Path) -> int:
    """Write entries as one JSON object per line.  Returns the count."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(asdict(entry), ensure_ascii=False))
            fh.write("\n")
            n += 1
    return n


def read_jsonl(path: Path) -> list[VocabeoEntry]:
    """Re-hydrate a previously written seed file."""
    out: list[VocabeoEntry] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            out.append(VocabeoEntry(**data))
    return out
