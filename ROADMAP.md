# ROADMAP — *deutsch-haufig*

Incremental, demo-able milestones. Each milestone ships something usable end-to-end.

Legend: 🟢 must-have · 🟡 should-have · 🔵 nice-to-have

---

## M0 — Project skeleton 

🟢 Repo bootstrap with `uv` + `pyproject.toml` (FastAPI, SQLAlchemy, Jinja2, httpx, selectolax, fsrs, pytest).
🟢 `src/deutsch_haufig/` package layout from PLAN §8.
🟢 `make dev` / `uv run web` starts an empty FastAPI app with a "Hello, Deutschland" page.
🟢 SQLite + Alembic (or `Base.metadata.create_all`) creates empty schema.
🟢 GitHub Actions: lint (ruff) + tests (pytest).

**Demo:** open `localhost:8000` → empty browse page renders.

---

## M1 — Seed ingest from vocabeo 

🟢 `ingest/vocabeo.py` scrapes the browse list into `data/vocabeo_seed.jsonl`:
   `{lemma, article, pos, level, frequency, en_gloss}`.
   - List view yields `lemma`, `article`, `level`, `frequency`, `en_gloss`.
   - `pos` is fetched per word by opening the word's detail view (click-through),
     since it isn't exposed in the list rows.
🟢 `ingest/pipeline.py seed` populates `Word` rows (no senses yet).
🟢 Browse route lists words with filters: level, pos, frequency, full-text on lemma.
🟢 Tests: parser fixtures for 5 sample pages.

**Demo:** browse 6k words with level / pos / frequency / lemma filters.

---

## M2 — German definitions & examples from dwds 

🟢 `ingest/dwds.py`:
   - Fetch Wörterbuch entry per lemma+pos.
   - Extract 1..n `Sense.definition_de`.
   - Fetch ≥3 corpus examples per sense (`Example.text_de`, `source="dwds-korpus"`).
🟢 `ingest/pipeline.py enrich --limit N` upserts senses + examples; idempotent.
🟢 Word detail page: monolingual definition, examples, attribution to dwds.
🟡 Fallback: if dwds lookup fails, mark `Sense.definition_de = NULL` and surface a "Definition fehlt" badge.
🟢 Tests: snapshot parser against 10 saved HTML fixtures (covers nouns, verbs, particles).

**Demo:** click any A1 word → German definition + 3 real corpus examples render.

### Diagnosed Issues (Todo)
- [x] Missing templates: No `templates/` directory; `word.html`, `index.html`, `browse.html` absent, causing 500 errors on all page renders.
- [ ] Broken enrich pipeline: `pipeline.py:enrich_words()` uses closed DB session in `word_iter()`, crashes on `uv run ingest enrich`.
- [ ] DWDS parser example bug: All corpus examples mapped to sense 1 only (dwds.py lines 200-208 ignore per-sense grouping).
- [ ] Missing test fixtures: 10 DWDS HTML fixtures required by ROADMAP; only 3 referenced, none exist in `tests/fixtures/dwds/`.
- [ ] Word API response bug: `word.py:word_api()` line 147 sets `order` to `s.definition_de` instead of `s.order`.
- [ ] Unimplemented fallback: "Definition fehlt" badge for failed DWDS lookups (M2 🟡 item) missing.
- [ ] Dead code: `word.py:_serialize_word()` defined but never called.
- [ ] Incomplete test coverage: Only 3 DWDS parser tests, short of 10 required by ROADMAP.

---

## M3 — Spaced repetition core 

🟢 `Scheduler` interface; `FSRSScheduler` implementation using `fsrs` lib.
🟢 `ReviewCard` auto-created on first encounter of a sense in `/learn`.
🟢 `/learn` page:
   - Front: lemma (+article for nouns) + a *gap-cloze* example (the word blanked out).
   - Reveal → German definition + full example list.
   - Buttons *Again / Hard / Good / Easy*; keyboard 1/2/3/4 + space to reveal.
🟢 Daily caps: `new_per_day=15`, `reviews_per_day=120` (user-settable).
🟢 Header counters: *Due today · New today · Retention 30d*.
🟢 Tests: scheduler transitions, queue ordering, cap enforcement.

**Demo:** review a 20-card session; quitting and reopening preserves due dates.

---

## M4 — On-demand dialogue/paragraph 

🟡 `DialogueProvider` interface + OpenAI implementation gated by env var.
🟡 Word detail page button **"Mini-Dialog zeigen"** → calls provider with prompt:
   *"Schreibe einen 6-zeiligen Alltagsdialog auf Deutsch (Niveau A2), in dem das Wort `{lemma}` (Bedeutung: `{definition_de}`) natürlich vorkommt."*
🟡 Cache result in `Dialogue` table keyed by `sense_id`; show "Neu generieren" if user wants another.
🔵 Manual "Bericht" button to flag bad output for review.
🟡 Hard fallback: if no provider configured, hide the button.

**Demo:** click *Mini-Dialog* on `geben` → 6-line German conversation rendered, persists across reloads.

---

## M5 — Polish for first real use 

🟢 Tailwind UI pass: typography for German (proper hyphenation, lang="de"), card layout, dark mode.
🟢 Browse: pagination + saved-filter URLs.
🟡 Word audio (TTS) via browser `SpeechSynthesis` API — zero-cost, optional.
🟡 Tag a card as *suspended* / *bury until tomorrow*.
🟢 README with screenshots + 1-command quickstart.

**Demo:** ship `v0.1.0` tag; usable daily by a single learner on localhost.

---

## M6 — Multi-user & deploy 

🟡 Email-magic-link auth (FastAPI + itsdangerous).
🟡 Per-user `ReviewCard` & settings; shared `Word/Sense/Example` corpus.
🟡 Postgres option behind a config flag (SQLAlchemy URL swap).
🟡 Dockerfile + `fly.io` / `render.com` deploy recipe.
🟡 Backups: nightly dump of user's data on demand (JSON export).

---

## M7 — Statistics & insights 

🔵 `/stats` page: heatmap of reviews, retention by level/category, hardest words list, forecast of upcoming load.
🔵 Per-card history view (all `ReviewLog` entries).
🔵 CSV export of progress.

---

## M8 — Content depth (ongoing)

🔵 Add B1 → B2 → C1 lemmas (DeReKo / Leipzig frequency lists as additional sources).
🔵 Collocations panel ("Typische Verbindungen") from DWDS.
🔵 Synonyms / antonyms (OpenThesaurus).
🔵 Verb conjugation table (Konjugator from canoonet / Verbformen).
🔵 Per-category curated *thematische Dialoge* (beim Arzt, im Restaurant, …).

---


## Suggested order of attack

```
M0 → M1 → M2 → M3   ← end of week 1: a working monolingual SRS for ~200 A1 words
            ↓
           M4 → M5  ← end of week 2: shippable v0.1 single-user app
                ↓
               M6 → M7 → M8
```
