# PLAN — *deutsch-haufig*

A web app to learn the most frequent German words for daily talk, with **German-only definitions** (from dwds.de), **rich contextual examples**, and a **spaced repetition** review loop.

---

## 1. Seed corpus: DWDS Goethe-Zertifikat word lists

The authoritative seed source is the official Goethe-Zertifikat word lists
published by DWDS at: https://www.dwds.de/d/api#wb-list-goethe

- A1: ~800 words
- A2: ~1200 words
- B1: ~1600 words
- **Total: ~3600 words** — all officially curated by Goethe-Institut, all guaranteed to have DWDS dictionary entries.

Each word arrives with:
- **Lemma**, **POS** (Wortart), **Genus**, **Article** (for nouns)
- **URL** to its DWDS dictionary page
- **`nur_im_Plural`** marker for plural-only nouns

The CSV is fetched from `https://www.dwds.de/api/lemma/goethe/{A1,A2,B1}.csv`.

**vocabeo.com/browse** was used in early M1 prototyping (~6200 words) but was replaced because:
1. Many entries are noisy/low-quality.
2. CEFR levels were missing for most words.
3. Definitions were in **English**, not German.
4. DWDS has no `vocabeo` entries in its dictionary, so enrichment had gaps.

The old vocabeo scraper (`ingest/vocabeo.py`) is kept for reference but deprecated.

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
  frequency       INTEGER       -- 0 (Goethe words don't carry frequency; reserved for future)
  ipa             TEXT NULL
  plural          TEXT NULL     -- nouns only
  source_ref      TEXT          -- e.g. "dwds:goethe:A1" / "dwds:goethe:A2"

Sense                            -- one Word can have multiple senses
  id              INTEGER PK
  word_id         FK -> Word
  order           INTEGER       -- sense ordering from DWDS
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
[DWDS Goethe CSV API]              [dwds.de]
        |                               |
        v                                v
  fetch A1/A2/B1 CSV           fetch Wörterbuch HTML
        |                          + korpus API (JSON)
        v                                |
  parse rows                      extract senses + examples
        \                               /
         \                             /
          v                           v
                goethe_words  ── upsert ──▶ SQLite (Word, Sense, Example)
                                                  |
                                                  v
                                   optional: LLM generates dialogue (cached)
```

Steps:

1. **Fetch DWDS Goethe CSVs** for A1, A2, B1 → `data/goethe/goethe_{level}.csv`.
2. **Parse CSV rows** into `GoetheEntry(lemma, url, pos, level, article, genus, only_plural)`.
3. **Upsert into `Word` table** deduped on `(lemma, pos)` — if the same word appears in multiple levels, keep the lowest (most basic) level.
4. **Enrich via dwds.de** for each word:
   - Fetch Wörterbuch page → 1..n `Sense` rows with `definition_de` (monolingual).
   - Fetch DWDS-Korpus API → up to N=5 authentic example sentences per sense.
5. Persist everything to **SQLite**. Re-runnable; idempotent on `(lemma, pos)`.

### CLI

```
uv run ingest goethe        # fetch + seed all three Goethe levels
uv run ingest enrich        # fetch DWDS defs + examples for words that lack them
uv run ingest cached-enrich # same, from local cache only (no HTTP)
```

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

The PoC must demonstrate the full loop end-to-end on the **~3600 Goethe words**:

- [x] `uv run ingest goethe` fetches and seeds A1 + A2 + B1 words from DWDS.
- [x] For each: pull German definition + ≥3 corpus examples from dwds.
- [x] Browse page: filter by level / pos.
- [x] Word detail page: German definition, examples, "Show conversation" button (LLM, cached).
- [x] Learn page: FSRS-driven review queue with 4-button rating, keyboard shortcuts (1/2/3/4).
- [x] All data in `app.db` (SQLite), seed script reproducible.

---

## 8. Project layout

```
deutsch-haufig/
├── PLAN.md
├── ROADMAP.md
├── pyproject.toml
├── app.db                       # gitignored
├── data/
│   ├── vocabeo_seed.jsonl       # deprecated, kept for reference
│   ├── goethe/                  # cached Goethe CSV files
│   └── dwds_cache/              # cached Wörterbuch HTML + korpus JSON
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
│   │   ├── goethe.py            # DWDS Goethe CSV fetcher + parser
│   │   ├── vocabeo.py           # deprecated vocabeo scraper
│   │   ├── dwds.py              # definition + examples fetcher
│   │   └── pipeline.py          # CLI: `uv run ingest`
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
    ├── test_ingest_goethe.py    # M1-DWDS: Goethe CSV parser
    ├── test_ingest_vocabeo.py   # deprecated vocabeo parser tests
    ├── test_ingest_dwds.py      # M2: DWDS HTML parser
    ├── test_scheduler.py
    └── test_*.py
```

---

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| DWDS Goethe CSV format changes | Isolate parser in `ingest/goethe.py`, snapshot CSV fixtures for tests. |
| DWDS HTML changes | Isolate parser in `ingest/dwds.py`, snapshot a fixture per word for tests. |
| LLM cost / hallucination for dialogues | Generate **on demand only**, cache in DB, mark `generated_by`, allow user to regenerate or report. |
| FSRS misuse | Use the reference lib; don't reinvent; cover with tests for: new card → learning → review transitions. |
| Scope creep | Hard cut at v0.1 (see §7); everything else lives in ROADMAP.md. |

---

## 10. Definition of done for the PoC

1. `uv run ingest goethe` populates `app.db` with ~3600 Goethe words across A1-A2-B1.
2. `uv run ingest enrich` fetches definitions + examples for all of them.
3. `uv run web` starts the app at `http://localhost:8000`.
4. From the browse page I can pick a word, read its **German** definition + ≥3 examples, and request a **dialogue**.
5. From `/learn` I can review cards by level; ratings persist; due dates change in line with FSRS.
6. `pytest` is green; basic CI on push.
