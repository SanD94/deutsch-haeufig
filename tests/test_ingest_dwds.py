"""M2 — DWDS definition parser tests.

Fixtures cover nouns, verbs, and particles from dwds.de:

  fixtures/dwds/noun_haus.html    basic noun entry "Haus"
  fixtures/dwds/verb_geben.html   verb "geben"
  fixtures/dwds/verb_sein.html  verb "sein"

The parser :func:`parse_entry` is exercised as a pure function.
"""

from __future__ import annotations

from pathlib import Path


from deutsch_haufig.ingest.dwds import (
    parse_entry,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dwds"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_noun_haus_basic() -> None:
    e = parse_entry("Haus", "noun", _read("noun_haus.html"))
    assert e.lemma == "Haus"
    assert len(e.senses) >= 1
    assert e.senses[0].definition_de
    assert "Gebäude" in e.senses[0].definition_de or "Wohn" in e.senses[0].definition_de


def test_parse_noun_haus_extracts_examples() -> None:
    e = parse_entry("Haus", "noun", _read("noun_haus.html"))
    examples = e.examples.get(1, ())
    assert len(examples) >= 1
    assert examples[0].text_de


def test_parse_empty_html_returns_empty() -> None:
    e = parse_entry("Test", "noun", "<html><body></body></html>")
    assert e.lemma == "Test"
    assert len(e.senses) == 0
