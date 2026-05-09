"""OpenAI-based dialogue provider.

Gated by ``DEUTSCH_HAUFIG_OPENAI_API_KEY`` env var. Uses a lightweight
httpx call to the OpenAI chat completions endpoint — no SDK dependency.
"""

from __future__ import annotations

import json

import httpx

from deutsch_haufig.dialogue import DialogueGenerationError

SYSTEM_PROMPT = (
    "Du bist ein Deutschlehrer (Niveau A2). "
    "Schreibe einen 6-zeiligen Alltagsdialog auf Deutsch (Niveau A2). "
    "Der Dialog muss das vorgegebene Wort natürlich enthalten. "
    "Antworte NUR mit dem Dialogtext, ohne zusätzliche Erklärungen oder Anführungszeichen."
)


class OpenAIProvider:
    """Dialogue provider backed by OpenAI-compatible chat API."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def generate(self, lemma: str, definition_de: str) -> str:
        user_prompt = (
            f"Schreibe einen 6-zeiligen Alltagsdialog auf Deutsch (Niveau A2), "
            f"in dem das Wort \"{lemma}\" (Bedeutung: {definition_de}) "
            f"natürlich vorkommt."
        )

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 512,
                },
            )

        if resp.status_code != 200:
            detail = ""
            try:
                body = resp.json()
                detail = body.get("error", {}).get("message", resp.text[:200])
            except (json.JSONDecodeError, TypeError):
                detail = resp.text[:200]
            raise DialogueGenerationError(
                f"OpenAI API error (HTTP {resp.status_code}): {detail}"
            )

        body = resp.json()
        choices = body.get("choices", [])
        if not choices:
            raise DialogueGenerationError("OpenAI returned no choices")

        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise DialogueGenerationError("OpenAI returned empty content")

        return content.strip()
