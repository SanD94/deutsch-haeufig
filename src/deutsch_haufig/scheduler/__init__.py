"""Spaced-repetition scheduler interface. Implementations land in M3."""

from __future__ import annotations

from typing import Protocol


class Scheduler(Protocol):
    """Minimal interface every scheduler must implement."""

    ...
