"""Dialogue/paragraph generation provider interface. Filled in from M4."""

from __future__ import annotations

from typing import Protocol


class DialogueProvider(Protocol):
    """Generates short German dialogues for a given sense."""

    ...
