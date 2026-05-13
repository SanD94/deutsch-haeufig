# ROADMAP — *deutsch-haufig*

Incremental, demo-able milestones. Each milestone ships something usable end-to-end.

Legend: 🟢 must-have · 🟡 should-have · 🔵 nice-to-have

---

## M0 — Project skeleton - Completed

## M1 — Seed ingest from vocabeo - Completed (deprecated)

The original M1 scraped vocabeo.com/browse for a ~6200-word seed list. This worked
but the vocabeo list is noisy — many entries are not high-quality, definitions
were in English, and CEFR levels were only present for a subset.

**Replaced by M1-DWDS below.** The `vocabeo.py` scraper and `data/vocabeo_seed.jsonl`
remain in the repo for reference but are no longer the primary seed source.
Existing vocabeo-derived words in the DB should be migrated or left in place
(they will have `source_ref LIKE 'vocabeo:%'` and can co-exist).

---

## M1-DWDS — Seed ingest from DWDS Goethe-Zertifikat word lists

The authoritative word lists are published by DWDS for the Goethe-Zertifikat
levels A1, A2, B1. Source: https://www.dwds.de/d/api#wb-list-goethe

- CSV: `https://www.dwds.de/api/lemma/goethe/{A1,A2,B1}.csv`
- JSON: `https://www.dwds.de/api/lemma/goethe/{A1,A2,B1}.json`

🟢 `ingest/goethe.py` — fetch DWDS Goethe word lists (CSV or JSON):
   - Fetch all three CSV files at once via httpx.
   - Parse each row into `(lemma, url, pos, genus, article, onlypl)`.
   - CSV columns: `Lemma`, `URL`, `Wortart`, `Genus`, `Artikel`, `nur_im_Plural`.
   - Save raw CSV to `data/goethe/` cache (idempotent, re-fetch only on cache miss).
   - Normalize DWDS wordart to our `pos` mapping (e.g. `"Substantiv"` → `"noun"`).
   - For nouns, populate `article` from the `Artikel` column (e.g. `"der, das"`).
   - Tag each word with its CEFR level (`A1`, `A2`, `B1`).

🟢 `ingest/pipeline.py seed-goethe` — upsert Goethe words into `Word` table:
   - Dedup on `(lemma, pos)` — the same word can appear across levels (e.g. `Haus` in A1 + B1);
     when that happens, keep the *lowest* level (most basic).
   - Set `source_ref = "dwds:goethe:{level}"`.
   - Print summary: *"X inserted, Y skipped (duplicates), Z already exist"*.

🟢 `uv run ingest goethe` (one command to fetch + seed all three levels).

🟢 Tests: fixture CSV snippets for each level; parser handles `nur_im_Plural`-only
   entries, multi-article nouns (`"der, das"`), and missing optional fields.

**Numbers:** ~800 A1, ~1200 A2, ~1600 B1 ≈ **3600 words total** — all officially
curated by Goethe-Institut, all with guaranteed DWDS dictionary coverage.

**Demo:**
```
uv run ingest goethe
→ A1: 813 inserted, 0 skipped
→ A2: 1187 inserted, 42 skipped (duplicates across levels)
→ B1: 1561 inserted, 136 skipped
→ Total: 3561 words in DB
```

---

## M2 — German definitions & examples from dwds — Completed

🟢 `ingest/dwds.py`:
   - Fetch Wörterbuch entry per lemma+pos.
   - Extract 1..n `Sense.definition_de`.
   - Fetch ≥3 corpus examples per sense (`Example.text_de`, `source="dwds-korpus"`).
🟢 `ingest/pipeline.py enrich --limit N` upserts senses + examples; idempotent.
🟢 Word detail page: monolingual definition, examples, attribution to dwds.
🟡 Fallback: if dwds lookup fails, mark `Sense.definition_de = NULL` and surface a "Definition fehlt" badge.
🟢 Tests: snapshot parser against 10 saved HTML fixtures (covers nouns, verbs, particles).

**Demo:** click any A1 word → German definition + 3 real corpus examples render.

---

## M2a — DWDS corpus examples via API

Currently examples are scraped from the Wörterbuch page HTML (embedded `dwdswb-belegtext`
spans). The number and quality vary. The DWDS korpus API at
`https://www.dwds.de/r/?q={lemma}&view=json&limit=5` returns richer, more diverse
sentences with proper attribution and date metadata.

🟡 `ingest/dwds.py` — add `fetch_corpus_examples(lemma, sense_idx, limit=5)`:
   - Call `https://www.dwds.de/r/?q={lemma}&format=full&view=json&limit=5`.
   - Parse the JSON response; extract sentence text for each hit.
   - Cache responses in `data/dwds_cache/corpus/{lemma}.json`.
   - Fall back to embedded HTML examples if the API returns nothing.

🟡 Pipeline: when enriching a word, prefer API examples (richer, more diverse).
   Only fall back to HTML-embedded `dwdswb-belegtext` snippets.

---

## M3 — Spaced repetition core — Completed

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

## M5 — Polish for first real use - Completed

🟢 Tailwind UI pass: typography for German (proper hyphenation, lang="de"), card layout, dark mode.
🟢 Browse: pagination + saved-filter URLs.
🟡 Word audio (TTS) via browser `SpeechSynthesis` API — zero-cost, optional.
🟡 Tag a card as *suspended* / *bury until tomorrow*.
🟢 README with screenshots + 1-command quickstart.

**Demo:** ship `v0.1.0` tag; usable daily by a single learner on localhost.

---

## M6 — Multi-user & deploy - Completed

🟡 Email-magic-link auth (FastAPI + itsdangerous).
🟡 Per-user `ReviewCard` & settings; shared `Word/Sense/Example` corpus.
🟡 Postgres option behind a config flag (SQLAlchemy URL swap).
🟡 Dockerfile + `fly.io` / `render.com` deploy recipe.
🟡 Backups: `uv run backup` — JSON export of all user data.

---

## M7 — Statistics & insights - Completed

🔵 `/stats` page: heatmap of reviews, retention by level/category, hardest words list, forecast of upcoming load (14 days).
🔵 Per-card history view (all `ReviewLog` entries).
🔵 CSV export of progress (`GET /stats/csv`).

---

## M8 — Content depth (ongoing) - Completed

🔵 Add B1 → B2 → C1 lemmas (enriched 1174+ words across A1-B1 from existing pipeline).
🔵 Collocations panel ("Typische Verbindungen") from DWDS — extracted from cached HTML via `uv run enrich-depth collocations`.
🔵 Verb conjugation table from Verbformen — `uv run enrich-depth conjugations --limit N`.
🔵 Synonyms / antonyms (OpenThesaurus) — future work (not implemented).

---

## M9 — UI language switching (i18n) - Completed

🟢 Three translation files: `src/deutsch_haufig/i18n/{de,en,tr}.json` covering all UI strings.
🟢 Language resolution order: query param (`?lang=tr`) → cookie (`dh_lang`) → `Accept-Language` header → default `de`.
🟢 Language switcher dropdown in the navbar (globe icon next to Login/Logout), also available in mobile nav.
🟢 `GET /lang/{code}` route sets the `dh_lang` cookie and redirects back.
🟢 `_t("key")` Jinja2 global function in all templates for translation lookups.
🟢 `_lang` context variable exposing the active language code.
🟢 All UI strings (nav, landing, browse, learn, word detail, auth pages, stats) are translatable.
🟢 German content (definitions, examples, dialogues) stays German — only the UI chrome is translated.
🔵 Per-user language preference persisted in `User.settings_json` (future enhancement).

**Demo:** click the globe icon next to Login → select Türkçe → entire UI switches to Turkish, German learning content unchanged.

---

## Suggested implementation order for next steps

```
M1-DWDS (fetch + seed Goethe lists)
    ↓
M2a    (corpus examples via API instead of HTML snippets)
    ↓
Re-enrich all Goethe words: dwds definitions + API examples
```

The existing M3/M4/M5/M6/M7/M8/M9 features are all complete and work with
whatever words are in the DB — they don't care whether words came from vocabeo
or Goethe lists.
