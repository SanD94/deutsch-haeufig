"""Dialogue/paragraph generation provider interface.

M4: ``DialogueProvider`` protocol that any LLM backend implements.
"""

from __future__ import annotations

from typing import Protocol


class DialogueProvider(Protocol):
    """Generates short German dialogues for a given sense."""

    async def generate(self, lemma: str, definition_de: str) -> str:
        """Return a 6-line German dialogue featuring *lemma* naturally.

        Raises ``DialogueGenerationError`` on failure.
        """


class DialogueGenerationError(RuntimeError):
    """Provider could not generate a dialogue."""


class NoOpProvider:
    """Fallback when no real provider is configured — always raises."""

    async def generate(self, lemma: str, definition_de: str) -> str:
        msg = "No dialogue provider configured (check opencode.json)"
        raise DialogueGenerationError(msg)


def provider_from_config() -> DialogueProvider:
    """Build a provider from ``opencode.json``.

    Returns ``NoOpProvider`` if no valid provider config is found.
    """
    from deutsch_haufig.config import get_dialogue_provider_config  # noqa: PLC0415

    provider_cfg = get_dialogue_provider_config()
    if provider_cfg is None:
        return NoOpProvider()

    from deutsch_haufig.dialogue.openai_provider import (  # noqa: PLC0415
        OpenAIProvider,
    )

    return OpenAIProvider(
        api_key=provider_cfg["api_key"],
        model=provider_cfg["model"],
        base_url=provider_cfg["base_url"],
    )
