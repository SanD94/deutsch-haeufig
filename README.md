# deutsch‑häufig

Web app to learn the most frequent German words with **monolingual** definitions
(from [dwds.de](https://www.dwds.de)), rich contextual examples, and an
[FSRS](https://github.com/open-spaced-repetition/py-fsrs) spaced-repetition
review loop.

## Quickstart

```bash
uv sync
uv run web        # → http://localhost:8000
```

Then browse words, learn with spaced repetition, and click the speaker icon
for pronunciation (browser TTS, offline-friendly).

```bash
uv run pytest     # 110+ tests
uv run ruff check .
```

## Usage

| Route | What |
|---|---|
| `/` | Landing page |
| `/browse` | Filterable word list (level, POS, frequency, search) |
| `/word/{id}` | Monolingual definition, examples, on-demand LLM dialogue |
| `/learn` | FSRS review session with 4-button rating + keyboard shortcuts |

### Keyboard shortcuts (Learn)

- `Space` — reveal answer
- `1`–`4` — rate card (Again, Hard, Good, Easy)

### Dialogue generation

Set `WANDB_API_KEY` (or your OpenAI-compatible provider) in the environment,
and `opencode.json` at the project root will be read automatically for the
API endpoint, key, and model. An LLM-generated "Mini-Dialog" button appears
on each word sense.

## Architecture

```
Python 3.13 · FastAPI · SQLAlchemy 2.x + SQLite · Pydantic
Jinja2 + HTMX + Alpine.js + Tailwind · httpx + selectolax (scraping)
FSRS scheduler · pytest
```

See [PLAN.md](./PLAN.md) and [ROADMAP.md](./ROADMAP.md) for the full design.

## Data sources

- **Word list**: [vocabeo.com](https://vocabeo.com/browse) — frequency-ranked German vocabulary (~6,260 words with metadata)
- **Definitions & examples**: [DWDS](https://www.dwds.de) — Digitales Wörterbuch der deutschen Sprache

## License

MIT
