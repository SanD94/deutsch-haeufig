"""Parser fixtures for M1 — vocabeo seed scraper.

Five hand-picked fixtures cover the structural variants we found on
vocabeo.com/german-vocabulary/* in April 2026:

  - verbs.html       reflexive forms, ``(sich) X`` form, mixed in CTA dividers
  - nouns.html       ``"Lemma, der/die/das"`` article suffix
  - adjectives.html  bare adjective lemmas
  - colors.html      lemmas decorated with trailing emoji
  - numbers.html     ``"<digit> - <word>"`` format
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deutsch_haufig.ingest.vocabeo import (
    VocabeoEntry,
    parse_browse_page,
    read_jsonl,
    write_jsonl,
)

FIXTURES = Path(__file__).parent / "fixtures" / "vocabeo"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- per-fixture parser tests ---------------------------------------------


def test_parse_verbs_extracts_lemmas_and_examples() -> None:
    entries = parse_browse_page(_read("verbs.html"), pos="verb", category="Common verbs")
    lemmas = [e.lemma for e in entries]
    assert lemmas == ["stellen", "nehmen", "sich erinnern", "(sich) vorstellen"]
    assert all(e.pos == "verb" for e in entries)
    assert all(e.article is None for e in entries)
    # First entry carries gloss + example pair.
    first = entries[0]
    assert "to put" in first.en_gloss
    assert first.example_de == "Ich stelle die Bücher ins Regal."
    assert first.example_en == "I put the books on the shelf."
    assert first.source_ref.endswith("#1")


def test_parse_verbs_skips_cta_divider() -> None:
    entries = parse_browse_page(_read("verbs.html"), pos="verb", category="Common verbs")
    # 4 word rows in the fixture; 1 CTA divider must be ignored.
    assert len(entries) == 4
    for e in entries:
        assert "Struggling" not in e.en_gloss
        assert "Struggling" not in (e.example_de or "")


def test_parse_nouns_strips_article_suffix() -> None:
    entries = parse_browse_page(_read("nouns.html"), pos="noun", category="Common nouns")
    by_lemma = {e.lemma: e for e in entries}
    assert by_lemma["Uhr"].article == "die"
    assert by_lemma["Jahr"].article == "das"
    assert by_lemma["Mensch"].article == "der"
    assert all(e.pos == "noun" for e in entries)


def test_parse_adjectives_keeps_bare_lemma() -> None:
    entries = parse_browse_page(_read("adjectives.html"), pos="adj", category="Common adjectives")
    assert [e.lemma for e in entries] == ["groß", "klein"]
    assert all(e.article is None for e in entries)
    assert all(e.pos == "adj" for e in entries)


def test_parse_colors_strips_trailing_emoji() -> None:
    entries = parse_browse_page(_read("colors.html"), pos="adj", category="Colors")
    assert [e.lemma for e in entries] == ["rot", "blau", "grün"]
    assert all("🔴" not in e.lemma for e in entries)


def test_parse_numbers_drops_digit_prefix() -> None:
    entries = parse_browse_page(_read("numbers.html"), pos="num", category="Numbers")
    assert [e.lemma for e in entries] == ["null", "eins", "einundzwanzig"]
    assert all(e.pos == "num" for e in entries)


# --- frequency bucketing --------------------------------------------------


def test_frequency_buckets_decrease_with_rank() -> None:
    """Top entries get higher buckets than lower entries on the same page."""
    entries = parse_browse_page(_read("verbs.html"), pos="verb", category="Common verbs")
    # 4 word entries → buckets are non-increasing as rank grows.
    freqs = [e.frequency for e in entries]
    assert freqs == sorted(freqs, reverse=True)
    assert freqs[0] == 5
    assert all(1 <= f <= 5 for f in freqs)


# --- jsonl round-trip -----------------------------------------------------


def test_write_and_read_jsonl_round_trip(tmp_path: Path) -> None:
    entries = parse_browse_page(_read("nouns.html"), pos="noun", category="Common nouns")
    out = tmp_path / "seed.jsonl"
    n = write_jsonl(entries, out)
    assert n == len(entries)
    # File is valid JSONL (one JSON object per line).
    for line in out.read_text(encoding="utf-8").splitlines():
        json.loads(line)
    # And can be re-hydrated identically.
    rehydrated = read_jsonl(out)
    assert rehydrated == entries


# --- fixture coverage sanity check ----------------------------------------


@pytest.mark.parametrize(
    "name,pos,category",
    [
        ("verbs.html", "verb", "Common verbs"),
        ("nouns.html", "noun", "Common nouns"),
        ("adjectives.html", "adj", "Common adjectives"),
        ("colors.html", "adj", "Colors"),
        ("numbers.html", "num", "Numbers"),
    ],
)
def test_every_fixture_yields_at_least_one_entry(name: str, pos: str, category: str) -> None:
    entries = parse_browse_page(_read(name), pos=pos, category=category)
    assert entries, f"{name} should parse at least one entry"
    for e in entries:
        assert isinstance(e, VocabeoEntry)
        assert e.lemma
        assert e.pos == pos
        assert e.category == category
        assert 1 <= e.frequency <= 5
