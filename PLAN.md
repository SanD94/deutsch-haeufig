# PLAN — *deutsch-haufig*

A web app to learn the most frequent German words for daily talk, with **German-only definitions** (from dwds.de), **rich contextual examples**, and a **spaced repetition** review loop.

---

## 1. Why vocabeo.com/browse is relevant

[vocabeo.com/browse](https://vocabeo.com/browse) exposes a curated, frequency-ranked German vocabulary list that is an excellent **seed corpus** for this project:

- **~6,260 words** ordered by **frequency** (1–5 buckets) — perfect for "most-used in daily talk".
- Each entry already carries the metadata we need to bootstrap a learner DB:
  - **Lemma** (with article for nouns, e.g. *der/die/das*).
  - **Part of speech** (noun, verb, adj., adv., prep., conj., pron., interj., num.).
  - **CEFR level** (A1 / A2 / B1 / none).
  - **Frequency rank** (1–5).
  - **Topical category** (Clothes & Fashion, Food & Drink, House & Home, Body Parts, Doctor & Medicine, Animals, Weather & Seasons, …).
  - **Sample sentences** (German + English gloss).
- It also exposes a built-in spaced-repetition / "Learn" view, which validates the UX we want to build.

What it is **missing** for our goals:

1. Definitions are in **English**, not German. We want **monolingual** explanations (better for B1+ acquisition and to break the "translation reflex").
2. Sentence examples are short, isolated and not always thematically grouped — we want **multiple examples per sense** and, on demand, a **short dialogue/paragraph** that situates the word.
3. The SRS is closed-source — we want a transparent, configurable algorithm (FSRS / SM-2).
4. No local-first ownership of the data and progress.

So vocabeo is an excellent **inspiration + seed source** (the wordlist itself, plus its metadata schema), and dwds.de is the right **authoritative German source** for monolingual definitions and corpus examples.

---

## 2. Core requirements (user-stated)

| # | Requirement | Source of truth |
|---|---|---|
| 1 | Word meaning shown **in German** | [dwds.de](https://www.dwds.de) (Wörterbuch + DWDS-Korpus) |
| 2 | **Several** example sentences in context; on demand a **paragraph / mini-dialogue** | dwds.de corpus + LLM-generated dialogue, cached |
| 3 | **Spaced Repetition** algorithm to schedule reviews | FSRS (preferred) / SM-2 fallback |
| 4 | **Web application** with a clean PoC | Python (FastAPI) + SQLite + HTMX/Alpine front-end |

---

## 3. Data model

```
Word
  id              INTEGER PK
  lemma           TEXT          -- e.g. "geben"
  article         TEXT NULL     -- "der" / "die" / "das" for nouns
  pos             TEXT          -- noun | verb | adj | adv | prep | conj | pron | interj | num
  level           TEXT NULL     -- A1 | A2 | B1 | null
  frequency       INTEGER       -- 1..5 (5 = most frequent)
  ipa             TEXT NULL
  plural          TEXT NULL     -- nouns only
  source_ref      TEXT          -- e.g. "vocabeo:der" / "dwds:geben"

Sense                            -- one Word can have multiple senses
  id              INTEGER PK
  word_id         FK -> Word
  definition_de   TEXT          -- German monolingual definition (from dwds)
  register        TEXT NULL     -- ugs., geh., fachspr., …
  domain          TEXT NULL     -- e.g. "Medizin"

Example
  id              INTEGER PK
  sense_id        FK -> Sense
  text_de         TEXT
  source          TEXT          -- "dwds-korpus" | "vocabeo" | "generated"
  translation_en  TEXT NULL     -- optional fallback only

Dialogue                         -- on-demand paragraph/conversation
  id              INTEGER PK
  sense_id        FK -> Sense
  text_de         TEXT
  generated_by    TEXT          -- "llm:gpt-..." | "hand"
  created_at      TIMESTAMP

User
  id, email, created_at, settings_json

ReviewCard                       -- one card per (user, sense)
  id              PK
  user_id         FK
  sense_id        FK
  -- FSRS state:
  stability       REAL
  difficulty      REAL
  due             TIMESTAMP
  last_review     TIMESTAMP NULL
  reps            INTEGER
  lapses          INTEGER
  state           TEXT           -- new | learning | review | relearning

ReviewLog
  id, card_id, ts, rating (1=Again,2=Hard,3=Good,4=Easy), elapsed_days, scheduled_days
```

---

## 4. Word ingestion pipeline

```
[vocabeo.com/browse]                 [dwds.de]
        |                                 |
        v                                 v
  scrape lemma+meta            fetch definition(s) + corpus examples
        \                               /
         \                             /
          v                           v
                seed_words.jsonl  ── normalize ──▶ SQLite (Word, Sense, Example)
                                                 |
                                                 v
                                  optional: LLM generates dialogue (cached)
```

Steps:

1. **Scrape vocabeo** (one-time) → `data/vocabeo_seed.jsonl` with `{lemma, article, pos, level, frequency, category}`. Respect robots/ToS — single low-rate run, cache on disk.
2. **Enrich via dwds.de** for each lemma:
   - Wörterbuch entry → 1..n `Sense` rows with `definition_de` (monolingual).
   - DWDS-Korpus → up to N=5 short authentic example sentences per sense.
3. **Normalize** part-of-speech, gender, plurals.
4. **Optional LLM step** (only when the user clicks *"Show me a conversation"*): generate a 4–8-line dialogue using the word in the chosen sense, cache it in `Dialogue`.
5. Persist everything to **SQLite**. Re-runnable; idempotent on `(lemma, pos)`.

---

## 5. Spaced repetition

- Algorithm: **FSRS v4** (open, modern, better retention than SM-2). Use the `fsrs` Python package.
- Each `Sense` becomes a card. Ratings: *Again / Hard / Good / Easy* (1–4).
- Daily new-card limit + max-review limit (configurable in user settings).
- On submit: compute next `stability`, `difficulty`, `due`; append `ReviewLog`.
- Provide a `/learn` queue: *due cards first, then up to N new cards by frequency desc.*

Why FSRS over SM-2: better data-driven scheduling, proven open-source implementations in Python and JS, and trivially swappable behind a `Scheduler` interface — so we can A/B vs SM-2 later.

---

## 6. Tech stack (PoC)

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.13** | Fast iteration; good scraping + ML libs; FSRS lib exists. |
| Web framework | **FastAPI** | Async, typed, tiny boilerplate; auto OpenAPI for later. |
| DB | **SQLite** (via SQLAlchemy 2.x) | Zero-setup; perfect for PoC; one-file backup. |
| Front-end | **Jinja2 + HTMX + Alpine.js + Tailwind** | No SPA build step; full keyboard UX; trivially deployable. |
| Scraping | **httpx + selectolax** | Fast, async-friendly. |
| SRS | **`fsrs`** PyPI package | Well-maintained reference implementation. |
| LLM (optional) | OpenAI-compatible API behind a `DialogueProvider` interface | Easy to mock/disable. |
| Testing | **pytest** + **httpx.AsyncClient** | Standard. |
| Packaging | **uv** + `pyproject.toml` | Fast, reproducible. |

---

## 7. PoC scope (v0.1)

The PoC must demonstrate the full loop end-to-end on a **small slice (~200 A1 words)**:

- [ ] Ingest 200 most frequent A1 words from vocabeo seed.
- [ ] For each: pull German definition + ≥3 corpus examples from dwds.
- [ ] Browse page: filter by level / category / pos / frequency.
- [ ] Word detail page: German definition, examples, "Show conversation" button (LLM, cached).
- [ ] Learn page: FSRS-driven review queue with 4-button rating, keyboard shortcuts (1/2/3/4).
- [ ] Single local user (no auth) — settings in a JSON blob.
- [ ] All data in `app.db` (SQLite), seed script reproducible.

---

## 8. Project layout

```
deutsch-haufig/
├── PLAN.md
├── ROADMAP.md
├── pyproject.toml
├── app.db                       # gitignored
├── data/
│   ├── vocabeo_seed.jsonl
│   └── dwds_cache/
├── src/deutsch_haufig/
│   ├── __init__.py
│   ├── main.py                  # FastAPI entrypoint
│   ├── config.py
│   ├── db.py                    # SQLAlchemy session / engine
│   ├── models.py                # ORM models from §3
│   ├── schemas.py               # Pydantic
│   ├── scheduler/
│   │   ├── __init__.py          # Scheduler interface
│   │   ├── fsrs_scheduler.py
│   │   └── sm2_scheduler.py
│   ├── ingest/
│   │   ├── vocabeo.py           # scraper
│   │   ├── dwds.py              # definition + examples fetcher
│   │   └── pipeline.py          # CLI: `python -m deutsch_haufig.ingest`
│   ├── dialogue/
│   │   ├── provider.py          # interface
│   │   └── openai_provider.py
│   ├── routes/
│   │   ├── browse.py
│   │   ├── word.py
│   │   ├── learn.py
│   │   └── api.py
│   └── templates/               # Jinja2 + HTMX partials
└── tests/
    ├── test_scheduler.py
    ├── test_ingest_dwds.py
    └── test_routes.py
```

---

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| vocabeo / dwds ToS or rate limits | Single low-rate ingest, cache on disk, document attribution, keep raw seed file out of redistribution. |
| dwds HTML changes | Isolate parser in `ingest/dwds.py`, snapshot a fixture per word for tests. |
| LLM cost / hallucination for dialogues | Generate **on demand only**, cache in DB, mark `generated_by`, allow user to regenerate or report. |
| FSRS misuse | Use the reference lib; don't reinvent; cover with tests for: new card → learning → review transitions. |
| Scope creep | Hard cut at v0.1 (see §7); everything else lives in ROADMAP.md. |

---

## 10. Definition of done for the PoC

1. `uv run ingest` populates `app.db` with ≥200 enriched A1 words.
2. `uv run web` starts the app at `http://localhost:8000`.
3. From the browse page I can pick a word, read its **German** definition + ≥3 examples, and request a **dialogue**.
4. From `/learn` I can review at least 20 cards in a row; ratings persist; due dates change in line with FSRS.
5. `pytest` is green; basic CI on push.
