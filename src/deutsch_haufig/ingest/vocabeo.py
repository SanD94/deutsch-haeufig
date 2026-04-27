"""Scrape vocabeo.com/browse for the M1 frequency-ranked seed corpus.

The browse page is a SvelteKit SPA with a virtual list — only the rows
near the viewport exist in the DOM at any time, and rows are absolutely
positioned via ``style.top``. To get every row we apply each option of
the page's *Part of Speech* filter in turn (so every harvested row is
already tagged with its POS) and scroll the virtualised list to render
each chunk, deduplicating by ``top`` offset.

Each row's outer HTML is captured and handed to :func:`parse_row_html`
— a pure, fixture-testable function that returns a :class:`VocabeoEntry`
matching the M1 JSONL schema:

    {lemma, article, pos, level, frequency, en_gloss, source_ref}

``article`` (e.g. ``"die"``) is split off the lemma cell for nouns,
which vocabeo renders as ``"<Lemma>, <article>"``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from selectolax.parser import HTMLParser

if TYPE_CHECKING:  # pragma: no cover - type-only import
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

URL = "https://vocabeo.com/browse"
ROW_HEIGHT = 30.4  # px, fixed by the Svelte virtual list
VIEWPORT = {"width": 1280, "height": 900}
SCROLL_STEP = 600
SETTLE_SECONDS = 0.10
MAX_NO_GROWTH_ROUNDS = 30

# (filter label as shown on vocabeo, canonical short tag stored in JSONL)
POS_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Adjective", "adj"),
    ("Adverb", "adv"),
    ("Conjunction", "conj"),
    ("Interjection", "interj"),
    ("Noun", "noun"),
    ("Number", "num"),
    ("Preposition", "prep"),
    ("Pronoun", "pron"),
    ("Verb", "verb"),
)

KNOWN_POS_TAGS: tuple[str, ...] = tuple(tag for _, tag in POS_OPTIONS)


# --- entry shape ----------------------------------------------------------


@dataclass(frozen=True)
class VocabeoEntry:
    """One row of the M1 seed JSONL."""

    lemma: str
    article: str | None
    pos: str
    level: str | None
    frequency: int | None
    en_gloss: str
    source_ref: str


# --- pure parser ----------------------------------------------------------


# Vocabeo renders nouns as "<Lemma>, <article>" — e.g. "Uhr, die".
# A few entries carry multiple articles (e.g. "Erbe, der/die"); we accept
# any combination of der/die/das separated by commas or slashes.
ARTICLE_SUFFIX_RE = re.compile(
    r"^(?P<lemma>.+?),\s*"
    r"(?P<article>(?:der|die|das)(?:\s*[,/]\s*(?:der|die|das))*)$"
)


def split_article(raw: str) -> tuple[str | None, str]:
    """Return ``(article, bare_lemma)`` for a noun cell like ``"Uhr, die"``.

    Non-noun cells (or nouns without a trailing article) return
    ``(None, raw)`` unchanged.
    """
    m = ARTICLE_SUFFIX_RE.match(raw)
    if not m:
        return None, raw
    return m.group("article").strip(), m.group("lemma").strip()


def _cell_text(tree: HTMLParser, css_class: str) -> str:
    node = tree.css_first(f".cell.{css_class}")
    if node is None:
        return ""
    return " ".join(node.text(separator=" ").split()).strip()


def parse_row_html(
    html: str,
    *,
    pos: str,
    source_slug: str = "vocabeo:browse",
) -> VocabeoEntry:
    """Parse one virtual-list row's outer HTML into a :class:`VocabeoEntry`.

    Pure function — no I/O, no playwright; safe to drive from tests.
    Raises :class:`ValueError` if the row carries no lemma cell.
    """
    tree = HTMLParser(html)
    lemma_raw = _cell_text(tree, "word")
    if not lemma_raw:
        raise ValueError("row has no .cell.word text")
    en_gloss = _cell_text(tree, "translation")
    level = _cell_text(tree, "level") or None
    freq_str = _cell_text(tree, "frequency")
    frequency: int | None = int(freq_str) if freq_str.isdigit() else None

    if pos == "noun":
        article, lemma = split_article(lemma_raw)
    else:
        article, lemma = None, lemma_raw

    return VocabeoEntry(
        lemma=lemma,
        article=article,
        pos=pos,
        level=level,
        frequency=frequency,
        en_gloss=en_gloss,
        source_ref=source_slug,
    )


# --- jsonl I/O ------------------------------------------------------------


def write_jsonl(entries: Iterable[VocabeoEntry], path: Path) -> int:
    """Write entries one-per-line as JSON. Returns the number of records."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as fh:
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


# --- playwright scraper ---------------------------------------------------


async def _reset_filters(page: Page) -> None:
    try:
        await page.get_by_text("Reset filters", exact=True).click(timeout=2000)
        await asyncio.sleep(0.5)
    except Exception:  # noqa: BLE001 — best-effort, the filter UI varies
        logger.debug("reset-filters click failed (continuing)")


async def _apply_pos_filter(page: Page, label: str) -> None:
    """Select ``label`` in the *Part of Speech* filter, dropdown-or-inline."""
    try:
        await page.get_by_text("Part of Speech", exact=True).click(timeout=2000)
        await asyncio.sleep(0.2)
    except Exception:  # noqa: BLE001 — already inline, no dropdown to open
        pass
    await page.get_by_text(label, exact=True).first.click(timeout=5000)
    await page.keyboard.press("Escape")
    await asyncio.sleep(0.5)


async def _collect_visible_rows(page: Page) -> list[tuple[str, str]]:
    """Return ``[(top_px, outerHTML)]`` for currently rendered virtual rows."""
    return await page.evaluate(
        """() => {
            const wrapper = document.querySelector('#virtual-list-wrapper');
            if (!wrapper) return [];
            const items = wrapper.querySelectorAll('div[slot="item"]');
            const out = [];
            for (const it of items) {
                const top = it.style.top || '';
                const row = it.querySelector('[data-testid="virtual-list-row"]');
                if (!row) continue;
                out.push([top, row.outerHTML]);
            }
            return out;
        }"""
    )


async def _scrape_one_pos(page: Page, label: str, tag: str) -> list[VocabeoEntry]:
    """Apply one POS filter and harvest every row in the resulting list."""
    await _reset_filters(page)
    await _apply_pos_filter(page, label)
    await page.wait_for_selector("#virtual-list-wrapper", timeout=30000)
    await asyncio.sleep(1.0)

    scroll_height = await page.evaluate(
        "document.querySelector('#virtual-list-wrapper').scrollHeight"
    )
    expected_rows = max(1, int(scroll_height / ROW_HEIGHT))
    logger.info("[%s] scrollHeight=%dpx (~%d rows)", tag, scroll_height, expected_rows)

    rows: dict[int, str] = {}
    no_growth = 0
    last_size = 0
    scroll_top = 0
    while True:
        await page.evaluate(
            f"document.querySelector('#virtual-list-wrapper').scrollTop = {scroll_top}"
        )
        await asyncio.sleep(SETTLE_SECONDS)
        for top_str, outer_html in await _collect_visible_rows(page):
            top_px = float((top_str or "0px").rstrip("px") or 0)
            idx = round(top_px / ROW_HEIGHT)
            rows.setdefault(idx, outer_html)
        if len(rows) == last_size:
            no_growth += 1
        else:
            no_growth = 0
        last_size = len(rows)
        if scroll_top >= scroll_height and no_growth >= MAX_NO_GROWTH_ROUNDS:
            break
        if len(rows) >= expected_rows and no_growth >= 5:
            break
        scroll_top += SCROLL_STEP
        if scroll_top > scroll_height + SCROLL_STEP * 5:
            scroll_top = 0  # wrap once to pick up tail rows
    logger.info("[%s] collected %d rows", tag, len(rows))

    entries: list[VocabeoEntry] = []
    for idx in sorted(rows):
        try:
            entries.append(
                parse_row_html(
                    rows[idx],
                    pos=tag,
                    source_slug=f"vocabeo:browse#{tag}:{idx}",
                )
            )
        except ValueError:
            continue
    return entries


async def scrape_browse_list(
    *,
    headless: bool = True,
    pos_options: tuple[tuple[str, str], ...] = POS_OPTIONS,
) -> list[VocabeoEntry]:
    """Scrape the entire vocabeo /browse list, tagged with POS via the filter UI.

    Returns a deduplicated list keyed on ``(lemma, pos, en_gloss)`` so
    homographs (e.g. ``sein/verb`` and ``sein/pron``) are both kept.
    """
    from playwright.async_api import async_playwright

    seen: set[tuple[str, str, str]] = set()
    out: list[VocabeoEntry] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page(viewport=VIEWPORT)
        await page.goto(URL, timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_selector("#virtual-list-wrapper", timeout=30000)
        await asyncio.sleep(2.0)

        for label, tag in pos_options:
            for entry in await _scrape_one_pos(page, label, tag):
                key = (entry.lemma, entry.pos, entry.en_gloss)
                if key in seen:
                    continue
                seen.add(key)
                out.append(entry)

        await browser.close()
    return out
