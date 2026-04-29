"""Pydantic v2 I/O schemas."""

from __future__ import annotations

from pydantic import BaseModel


class ExampleOut(BaseModel):
    text_de: str
    source: str


class SenseOut(BaseModel):
    id: int
    order: int
    definition_de: str
    register_label: str | None = None
    domain: str | None = None
    examples: list[ExampleOut] = []


class WordDetail(BaseModel):
    id: int
    lemma: str
    article: str | None = None
    pos: str
    level: str | None = None
    frequency: int | None = None
    senses: list[SenseOut] = []
