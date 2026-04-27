"""M1 — vocabeo seed scraper parser tests.

Five fixture rows cover the structural variants we found on
vocabeo.com/browse in April 2026:

  - adj_a1.html         bare adjective lemma
  - noun_der.html       ``"<Lemma>, der"`` article suffix
  - noun_die.html       ``"<Lemma>, die"`` article suffix
  - verb_sein.html      ``sein`` (verb) — homograph
  - pron_no_level.html  ``sein`` (pronoun) — homograph + missing CEFR level

The parser is exercised through :func:`parse_row_html`, the same pure
function the live Playwright scraper drives over each captured row.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from deutsch_haufig.ingest.vocabeo import (
    VocabeoEntry,
    parse_row_html,
    read_jsonl,
    split_article,
    write_jsonl,
)

FIXTURES = Path(__file__).parent / "fixtures" / "vocabeo"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- per-fixture parser tests ---------------------------------------------


def test_parse_adjective_keeps_bare_lemma() -> None:
    e = parse_row_html(_read("adj_a1.html"), pos="adj")
    assert e.lemma == "gut"
    assert e.article is None
    assert e.pos == "adj"
    assert e.level == "A1"
    assert e.frequency == 5
    assert e.en_gloss == "good, fine"


def test_parse_noun_der_strips_article_suffix() -> None:
    e = parse_row_html(_read("noun_der.html"), pos="noun")
    assert e.lemma == "Mensch"
    assert e.article == "der"
    assert e.pos == "noun"
    assert "human" in e.en_gloss


def test_parse_noun_die_strips_article_suffix() -> None:
    e = parse_row_html(_read("noun_die.html"), pos="noun")
    assert e.lemma == "Uhr"
    assert e.article == "die"
    assert e.pos == "noun"


def test_parse_verb_homograph_keeps_lemma() -> None:
    e = parse_row_html(_read("verb_sein.html"), pos="verb")
    assert e.lemma == "sein"
    assert e.article is None  # articles are noun-only
    assert e.pos == "verb"
    assert e.en_gloss == "to be"


def test_parse_pronoun_handles_missing_level() -> None:
    e = parse_row_html(_read("pron_no_level.html"), pos="pron")
    assert e.lemma == "sein"
    assert e.pos == "pron"
    assert e.level is None  # empty level cell → None
    assert e.frequency == 3
    assert e.article is None


# --- helper unit tests ----------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected_article,expected_lemma",
    [
        ("Uhr, die", "die", "Uhr"),
        ("Mensch, der", "der", "Mensch"),
        ("Jahr, das", "das", "Jahr"),
        ("Erbe, der/die", "der/die", "Erbe"),  # multi-article variant
        ("Buch , das", "das", "Buch"),  # tolerates extra whitespace
        ("gut", None, "gut"),  # no article suffix
        ("sein", None, "sein"),  # homograph: no comma
    ],
)
def test_split_article(raw: str, expected_article: str | None, expected_lemma: str) -> None:
    article, lemma = split_article(raw)
    assert article == expected_article
    assert lemma == expected_lemma


# --- jsonl round-trip -----------------------------------------------------


def test_write_and_read_jsonl_round_trip(tmp_path: Path) -> None:
    entries = [
        parse_row_html(_read("adj_a1.html"), pos="adj"),
        parse_row_html(_read("noun_die.html"), pos="noun"),
        parse_row_html(_read("verb_sein.html"), pos="verb"),
    ]
    out = tmp_path / "seed.jsonl"
    n = write_jsonl(entries, out)
    assert n == len(entries)
    # File is valid JSONL (one JSON object per line) with the M1 schema.
    expected_keys = {"lemma", "article", "pos", "level", "frequency", "en_gloss", "source_ref"}
    for line in out.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        assert set(record) == expected_keys
    rehydrated = read_jsonl(out)
    assert rehydrated == entries


# --- fixture coverage sanity check ----------------------------------------


@pytest.mark.parametrize(
    "name,pos",
    [
        ("adj_a1.html", "adj"),
        ("noun_der.html", "noun"),
        ("noun_die.html", "noun"),
        ("verb_sein.html", "verb"),
        ("pron_no_level.html", "pron"),
    ],
)
def test_every_fixture_yields_a_valid_entry(name: str, pos: str) -> None:
    e = parse_row_html(_read(name), pos=pos)
    assert isinstance(e, VocabeoEntry)
    assert e.lemma
    assert e.pos == pos
    if e.frequency is not None:
        assert 1 <= e.frequency <= 5
    # Round-trip through JSON to ensure the dataclass is JSON-serialisable.
    json.dumps(asdict(e), ensure_ascii=False)


def test_parse_row_without_word_cell_raises() -> None:
    with pytest.raises(ValueError):
        parse_row_html(
            '<div data-testid="virtual-list-row"></div>',
            pos="adj",
        )
