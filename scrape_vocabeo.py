"""Scrape all words from https://vocabeo.com/browse.

The browse page uses a Svelte virtual list where rows are absolutely
positioned inside ``#virtual-list-wrapper`` and only those near the
viewport are rendered. We scroll the wrapper top-to-bottom and read
each rendered row, deduplicating by its ``top`` offset (which maps
1-to-1 to the word's index in the full list).
"""

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

URL = "https://vocabeo.com/browse"
OUT_PATH = Path("data/vocabeo_words.json")
ROW_HEIGHT = 30.4  # px, fixed by the Svelte virtual list
EXPECTED_TOTAL = 6260
VIEWPORT = {"width": 1280, "height": 900}
SCROLL_STEP = 600  # ~20 rows; overlaps with prior viewport
SETTLE_SECONDS = 0.10
MAX_NO_GROWTH_ROUNDS = 30


async def collect_visible(page) -> list[dict]:
    """Return the rendered rows as ``[{idx, top, word, translation, level, frequency}]``."""
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
                const word = row.querySelector('.cell.word')?.innerText.trim() || '';
                const tr = row.querySelector('.cell.translation')?.innerText.trim() || '';
                const lvl = row.querySelector('.cell.level')?.innerText.trim() || '';
                const freq = row.querySelector('.cell.frequency')?.innerText.trim() || '';
                if (!word) continue;
                out.push({ top, word, translation: tr, level: lvl, frequency: freq });
            }
            return out;
        }"""
    )


async def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    results: dict[int, dict] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport=VIEWPORT)
        await page.goto(URL, timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_selector("#virtual-list-wrapper", timeout=30000)
        await asyncio.sleep(2.0)

        scroll_height = await page.evaluate(
            "document.querySelector('#virtual-list-wrapper').scrollHeight"
        )
        print(f"scrollHeight={scroll_height}px (~{int(scroll_height / ROW_HEIGHT)} rows)")

        no_growth = 0
        scroll_top = 0
        last_size = 0

        while True:
            await page.evaluate(
                f"document.querySelector('#virtual-list-wrapper').scrollTop = {scroll_top}"
            )
            await asyncio.sleep(SETTLE_SECONDS)

            for row in await collect_visible(page):
                top_px = float(row["top"].rstrip("px") or 0)
                idx = round(top_px / ROW_HEIGHT)
                if idx not in results:
                    results[idx] = {
                        "index": idx,
                        "top": row["top"],
                        "word": row["word"],
                        "translation": row["translation"],
                        "level": row["level"],
                        "frequency": row["frequency"],
                    }

            if len(results) == last_size:
                no_growth += 1
            else:
                no_growth = 0
            last_size = len(results)

            if scroll_top % (SCROLL_STEP * 20) == 0:
                print(f"  scrollTop={scroll_top:>7d} collected={len(results)}")

            if scroll_top >= scroll_height and no_growth >= MAX_NO_GROWTH_ROUNDS:
                break
            if len(results) >= EXPECTED_TOTAL and no_growth >= 5:
                break

            scroll_top += SCROLL_STEP
            if scroll_top > scroll_height + SCROLL_STEP * 5:
                # Wrap around once to pick up any tail rows we glossed over.
                scroll_top = 0

        await browser.close()

    ordered = [results[i] for i in sorted(results)]
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(ordered, f, ensure_ascii=False, indent=2)

    print(f"Total collected: {len(ordered)} (expected {EXPECTED_TOTAL})")
    print(f"Saved to {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
