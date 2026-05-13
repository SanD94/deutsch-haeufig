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

The old vocabeo.com/browse scraper has been removed. All words come from the
official DWDS Goethe-Zertifikat lists.

### B2 extension: project-defined common-word layer

DWDS/Goethe currently gives us official A1, A2, and B1 lists, but no equivalent
official B2 list. For this project, **B2 is therefore an operational level**, not
a claimed Goethe/CEFR-certified list.

The first boundary to define is the **lower bound**:

> A B2 candidate must be a common contemporary DWDS dictionary lemma that is
> **not already present in the official Goethe A1/A2/B1 seed set**.

That lower bound gives us “beyond B1” without inventing difficulty labels for
known beginner/intermediate vocabulary. The selection goal is **not** to define a
frequency range, because a range can be arbitrary and can still admit weak words.
The goal is to find the **best 1,000 common useful words after B1**.

Proposed source and scoring pipeline for the first **1,000 common B2 words**:

1. Start from DWDS dictionary headwords, preferably the downloadable DWDS
   headword JSON from `https://www.dwds.de/dwds_static/wb/dwdswb-headwords.json`
   or the DWDS Lemmadatenbank download if we need the complete frequency-class
   export.
2. Remove every `(lemma, pos)` already in Goethe A1/A2/B1.
3. Keep only entries with a DWDS dictionary URL and a useful part of speech
   (`Substantiv`, `Verb`, `Adjektiv`, `Adverb`, plus a small number of common
   connectors/particles if they survive filtering).
4. Query DWDS frequency in batches with
   `GET https://www.dwds.de/api/frequency/?q={lemma}`. The response provides
   `hits` and `frequency` on a 0–6 logarithmic scale. Use `hits` as the main
   commonness signal; use `frequency` only as a coarse sanity check, not as the
   definition of B2.
5. Exclude likely non-B2 noise before taking the top 1,000: proper names, opaque
   compounds with very narrow domains, archaic/historical-only entries,
   regional-only variants, spelling variants, affixes, multiword entries unless
   highly useful, and words whose DWDS definition page has no parseable definition.
6. Score candidates by commonness plus learner usefulness, then take the top
   accepted words inside POS buckets rather than a raw frequency range. Initial
   target mix for 1,000 words:
   - ~450 nouns
   - ~220 verbs
   - ~220 adjectives/participial adjectives
   - ~70 adverbs
   - ~40 connectors, particles, pronouns, and other high-utility function words
7. Treat the “upper bound” as the **1,000th accepted candidate** in this scored,
   audited list. If the tail is too specialist or too easy, adjust scoring and
   exclusion rules, then regenerate; do not rely on a fixed frequency interval.
8. Enrich exactly like Goethe words: DWDS HTML definitions, DWDS corpus examples,
   optional IPA, and cached raw responses.

This gives a reproducible B2 approximation: “common DWDS words above Goethe B1,”
ranked by corpus frequency and filtered for learner usefulness. It is intentionally
easy to revise: if review shows the bottom of the top-1,000 list is weak, we can
adjust POS quotas, usefulness scoring, and exclusion rules, then regenerate
`source_ref = "dwds:b2:auto:v1"`.

---

## 2. Core requirements (user-stated)

| # | Requirement | Source of truth |
|---|---|---|
| 1 | Word meaning shown **in German** | [dwds.de](https://www.dwds.de) — HTML scrape of `/wb/{lemma}` (no API for definitions) |
| 2 | **Several** example sentences in context | DWDS korpus API `GET /r?q={lemma}&view=json` |
| 3 | On-demand paragraph / mini-dialogue | LLM-generated, cached in `Dialogue` table |
| 4 | **Spaced Repetition** algorithm | FSRS via `fsrs` Python package |
| 5 | **Web application** | Python (FastAPI) + SQLite + HTMX/Alpine front-end |

---

## 3. Data model

```
Word
  id              INTEGER PK
  lemma           TEXT          -- e.g. "geben"
  article         TEXT NULL     -- "der" / "die" / "das" for nouns
  pos             TEXT          -- noun | verb | adj | adv | prep | conj | pron | interj | num
  level           TEXT NULL     -- A1 | A2 | B1 | B2 | null; B2 is project-defined
  frequency       INTEGER       -- DWDS frequency bucket 0..6 when available
  frequency_hits  INTEGER NULL  -- DWDS corpus hits for ranking B2 candidates
  ipa             TEXT NULL     -- from /api/ipa/
  plural          TEXT NULL     -- nouns only
  source_ref      TEXT          -- e.g. "dwds:goethe:A1" or "dwds:b2:auto:v1"

Sense                            -- one Word can have multiple senses
  id              INTEGER PK
  word_id         FK -> Word
  order           INTEGER       -- sense ordering from DWDS
  definition_de   TEXT          -- German monolingual definition (from HTML scrape of /wb/{lemma})
  register        TEXT NULL     -- ugs., geh., fachspr., …
  domain          TEXT NULL     -- e.g. "Medizin"

Example
  id              INTEGER PK
  sense_id        FK -> Sense
  text_de         TEXT
  source          TEXT          -- "dwds-korpus" | "generated"
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
[DWDS APIs]                        [DWDS HTML scrape]
     |                                     |
     v                                     v
  Goethe CSV                      /wb/{lemma} page
  /api/lemma/goethe/{level}.csv   (definitions only)
     |                                     |
     v                                     v
  parse rows -> Word              parse lesarten -> Sense
     |                                     |
     +--------+----------------------------+
              |
              v
  [DWDS korpus API]
  /r?q={lemma}&view=json&limit=10
              |
              v
  parse ctx_ arrays -> Example
              |
              v
         SQLite (Word, Sense, Example)
              |
              v
  optional: LLM generates dialogue (cached)
```

Steps:

1. **Fetch DWDS Goethe CSVs** for A1, A2, B1 → `data/goethe/goethe_{level}.csv`. (API call)
2. **Parse CSV rows** → upsert into `Word` table deduped on `(lemma, pos)`; keep lowest CEFR level.
3. **Fetch definitions** from `/wb/{lemma}` HTML. **Note: there is no DWDS API for definitions** — the `/api/wb/snippet` endpoint only returns lemma + wortart metadata, not definition text. HTML scraping is the only option. Cache raw HTML to `data/dwds_cache/`.
4. **Fetch examples** from korpus API `GET /r?q={lemma}&format=full&view=json&limit=10&corpus=kern`. Reconstruct sentences from the `ctx_` token arrays. Cache JSON to `data/dwds_cache/corpus/`.
5. **Optional: fetch IPA** from `GET /api/ipa/?q={lemma}`. Cache to `data/dwds_cache/ipa/`.
6. Persist everything to **SQLite**. Re-runnable; idempotent on `(lemma, pos)`.

### B2 candidate ingestion

```
[DWDS headwords / Lemmadatenbank]
              |
              v
  remove Goethe A1/A2/B1 lemmas
              |
              v
  [DWDS frequency API]
  /api/frequency/?q={lemma}
              |
              v
  score + filter + stratify by POS
              |
              v
  top 1,000 project-defined B2 lemmas
              |
              v
  same enrichment as Goethe words
```

B2 ingestion rules:

1. Treat A1/A2/B1 as the hard lower-bound exclusion set.
2. Use DWDS frequency `hits` as the main commonness signal. Keep `frequency` as
   an audit/sanity field, but do not define B2 by a frequency range.
3. Prefer learner-useful single-token lemmas with parseable DWDS definitions and
   corpus examples.
4. Use POS quotas so the final 1,000 words are broad rather than just noun-heavy.
5. Mark rows as `level = "B2"` and `source_ref = "dwds:b2:auto:v1"` so this
   generated layer remains distinguishable from official Goethe data.

The practical upper bound is the 1,000th accepted word after scoring and review.
After the first candidate pass, inspect the lowest-ranked included words and the
highest-ranked excluded words; if the tail is poor, revise the scoring/exclusion
rules and regenerate the same 1,000-word target.

### CLI

```
uv run ingest goethe            # fetch + seed all three Goethe levels
uv run ingest b2-candidates     # generate project-defined top 1,000 B2 words
uv run ingest enrich            # fetch defs (HTML) + examples (API) + IPA (API)
uv run ingest enrich --corpus-api  # fetch examples via API only
uv run ingest enrich --with-ipa    # also fetch IPA
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
| HTTP | **httpx** | Async, connection-pooled, used for all API calls + HTML fetches. |
| HTML parsing | **selectolax** | Minimal dependency for the one remaining HTML scrape (definitions). |
| SRS | **`fsrs`** PyPI package | Well-maintained reference implementation. |
| LLM (optional) | OpenAI-compatible API behind a `DialogueProvider` interface | Easy to mock/disable. |
| Testing | **pytest** + **httpx.AsyncClient** | Standard. |
| Packaging | **uv** + `pyproject.toml` | Fast, reproducible. |

---

## 7. PoC scope (v0.1)

The PoC must demonstrate the full loop end-to-end on the **~3600 Goethe words**:

- [x] `uv run ingest goethe` fetches and seeds A1 + A2 + B1 words from DWDS CSV API.
- [x] `uv run ingest enrich` pulls definitions (via HTML), examples (via korpus API), and IPA (via API).
- [x] Browse page: filter by level / pos.
- [x] Word detail page: German definition, examples, IPA, "Show conversation" button (LLM, cached).
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
│   ├── goethe/                  # cached Goethe CSV files (API)
│   ├── dwds_cache/
│   │   ├── *.html               # cached /wb/{lemma} pages (HTML scrape for definitions)
│   │   ├── corpus/*.json        # cached korpus API responses (JSON)
│   │   └── ipa/*.json           # cached IPA API responses (JSON)
│   └── vocabeo_seed.jsonl       # (deprecated, may be present from old runs)
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
│   │   ├── goethe.py            # DWDS Goethe CSV fetcher + parser (API)
│   │   ├── dwds.py              # definition HTML parser + API fetchers
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
    ├── test_ingest_goethe.py    # Goethe CSV parser tests
    ├── test_ingest_dwds.py      # DWDS HTML parser tests
    ├── test_ingest_dwds_corpus.py # DWDS korpus API + IPA tests
    ├── test_ingest_pipeline.py  # pipeline CLI tests
    ├── test_ingest_pipeline.py  # pipeline CLI tests
    ├── test_scheduler.py
    └── test_*.py
```

---

## 9. Source methods: API vs HTML scraping

| Data | Source | Method | Notes |
|---|---|---|---|
| Word lists (A1/A2/B1) | `GET /api/lemma/goethe/{level}.csv` | CSV API | ✅ Fast, stable |
| Definitions | `GET /wb/{lemma}` | HTML scrape | ✅ Only option — no API for definition text |
| Corpus examples | `GET /r?q={lemma}&view=json` | JSON API | ✅ Richer than HTML-embedded snippets |
| IPA | `GET /api/ipa/?q={lemma}` | JSON API | ✅ Clean JSON |
| Collocations | `GET /wb/{lemma}` | HTML scrape | ⏳ Future — extracted from HTML |
| Conjugations | Verbformen (external) | HTML scrape | ⏳ Future |

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| DWDS Goethe CSV format changes | Isolate parser in `ingest/goethe.py`, snapshot CSV fixtures for tests. |
| DWDS HTML changes (definitions) | Isolate parser in `ingest/dwds.py`, snapshot fixture per word for tests. |
| DWDS korpus API format changes | Isolate JSON parser, snapshot fixture response for tests. |
| LLM cost / hallucination for dialogues | Generate **on demand only**, cache in DB, allow regeneration. |
| FSRS misuse | Use the reference lib; don't reinvent; cover with tests. |
| Scope creep | Hard cut at v0.1; everything else in ROADMAP.md. |

---

## 11. Definition of done for the PoC

1. `uv run ingest goethe` populates `app.db` with ~3600 Goethe words across A1-A2-B1.
2. `uv run ingest enrich` fetches definitions (HTML) + examples (API) + IPA (API) for all of them.
3. `uv run web` starts the app at `http://localhost:8000`.
4. From the browse page I can pick a word, read its **German** definition + ≥3 corpus examples + IPA.
5. From `/learn` I can review cards by level; ratings persist; due dates change in line with FSRS.
6. `pytest` is green; basic CI on push.
