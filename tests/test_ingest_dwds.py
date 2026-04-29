"""M2 — DWDS definition parser tests.

Fixtures cover nouns, verbs, and particles from dwds.de:

  fixtures/dwds/noun_haus.html    basic noun entry "Haus"
  fixtures/dwds/verb_geben.html   verb "geben"
  fixtures/dwds/verb_sein.html    verb "sein"
  fixtures/dwds/verb_haben.html   verb "haben"
  fixtures/dwds/verb_werden.html  verb "werden"
  fixtures/dwds/noun_auto.html    noun "Auto"
  fixtures/dwds/noun_buch.html    noun "Buch"
  fixtures/dwds/noun_stadt.html   noun "Stadt"
  fixtures/dwds/particle_ab.html  particle "ab"
  fixtures/dwds/particle_doch.html particle "doch"

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


# Noun tests

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


def test_parse_noun_auto() -> None:
    e = parse_entry("Auto", "noun", _read("noun_auto.html"))
    assert e.lemma == "Auto"
    assert len(e.senses) >= 1
    assert e.senses[0].definition_de
    assert "Kraftfahrzeug" in e.senses[0].definition_de or "Personenkraftwagen" in e.senses[0].definition_de


def test_parse_noun_auto_examples() -> None:
    e = parse_entry("Auto", "noun", _read("noun_auto.html"))
    examples = e.examples.get(1, ())
    assert len(examples) >= 1


def test_parse_noun_buch() -> None:
    e = parse_entry("Buch", "noun", _read("noun_buch.html"))
    assert e.lemma == "Buch"
    assert len(e.senses) >= 1
    assert e.senses[0].definition_de
    assert "Blättern" in e.senses[0].definition_de or "Werk" in e.senses[0].definition_de


def test_parse_noun_buch_examples() -> None:
    e = parse_entry("Buch", "noun", _read("noun_buch.html"))
    examples = e.examples.get(1, ())
    assert len(examples) >= 1


def test_parse_noun_stadt() -> None:
    e = parse_entry("Stadt", "noun", _read("noun_stadt.html"))
    assert e.lemma == "Stadt"
    assert len(e.senses) >= 1
    assert e.senses[0].definition_de
    assert "Ortschaft" in e.senses[0].definition_de or "besiedelt" in e.senses[0].definition_de


def test_parse_noun_stadt_examples() -> None:
    e = parse_entry("Stadt", "noun", _read("noun_stadt.html"))
    examples = e.examples.get(1, ())
    assert len(examples) >= 1


# Verb tests

def test_parse_verb_geben() -> None:
    e = parse_entry("geben", "verb", _read("verb_geben.html"))
    assert e.lemma == "geben"
    assert len(e.senses) >= 1
    assert e.senses[0].definition_de
    assert "reichen" in e.senses[0].definition_de or "überlassen" in e.senses[0].definition_de


def test_parse_verb_geben_examples() -> None:
    e = parse_entry("geben", "verb", _read("verb_geben.html"))
    examples = e.examples.get(1, ())
    assert len(examples) >= 1


def test_parse_verb_sein() -> None:
    e = parse_entry("sein", "verb", _read("verb_sein.html"))
    assert e.lemma == "sein"
    assert len(e.senses) >= 1
    assert e.senses[0].definition_de
    assert "befinden" in e.senses[0].definition_de or "existieren" in e.senses[0].definition_de


def test_parse_verb_sein_examples() -> None:
    e = parse_entry("sein", "verb", _read("verb_sein.html"))
    examples = e.examples.get(1, ())
    assert len(examples) >= 1


def test_parse_verb_haben() -> None:
    e = parse_entry("haben", "verb", _read("verb_haben.html"))
    assert e.lemma == "haben"
    assert len(e.senses) >= 1
    assert e.senses[0].definition_de
    assert "besitzen" in e.senses[0].definition_de or "Eigentum" in e.senses[0].definition_de


def test_parse_verb_haben_examples() -> None:
    e = parse_entry("haben", "verb", _read("verb_haben.html"))
    examples = e.examples.get(1, ())
    assert len(examples) >= 1


def test_parse_verb_werden() -> None:
    e = parse_entry("werden", "verb", _read("verb_werden.html"))
    assert e.lemma == "werden"
    assert len(e.senses) >= 1
    assert e.senses[0].definition_de
    assert "wandeln" in e.senses[0].definition_de or "Zustand" in e.senses[0].definition_de


def test_parse_verb_werden_examples() -> None:
    e = parse_entry("werden", "verb", _read("verb_werden.html"))
    examples = e.examples.get(1, ())
    assert len(examples) >= 1


# Particle tests

def test_parse_particle_ab() -> None:
    e = parse_entry("ab", "particle", _read("particle_ab.html"))
    assert e.lemma == "ab"
    assert len(e.senses) >= 1
    assert e.senses[0].definition_de
    assert "weg" in e.senses[0].definition_de or "Ort" in e.senses[0].definition_de


def test_parse_particle_ab_examples() -> None:
    e = parse_entry("ab", "particle", _read("particle_ab.html"))
    examples = e.examples.get(1, ())
    assert len(examples) >= 1


def test_parse_particle_doch() -> None:
    e = parse_entry("doch", "particle", _read("particle_doch.html"))
    assert e.lemma == "doch"
    assert len(e.senses) >= 1
    assert e.senses[0].definition_de
    assert "Bekräftigung" in e.senses[0].definition_de or "Aussage" in e.senses[0].definition_de


def test_parse_particle_doch_examples() -> None:
    e = parse_entry("doch", "particle", _read("particle_doch.html"))
    examples = e.examples.get(1, ())
    assert len(examples) >= 1


# Edge cases

def test_parse_empty_html_returns_empty() -> None:
    e = parse_entry("Test", "noun", "<html><body></body></html>")
    assert e.lemma == "Test"
    assert len(e.senses) == 0
