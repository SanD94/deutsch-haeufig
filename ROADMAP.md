# ROADMAP — *deutsch-haufig*

Incremental, demo-able milestones. Each milestone ships something usable end-to-end.

Legend: 🟢 must-have · 🟡 should-have · 🔵 nice-to-have

---

## M0 — Project skeleton - Completed

## M1 — Seed ingest from vocabeo - Removed

The original M1 scraped vocabeo.com/browse for a ~6200-word seed list. This was
replaced by M1-DWDS and has now been **fully removed** — the `vocabeo.py` module,
its test fixtures, and the `scrape`/`seed`/`all` pipeline subcommands have been
deleted. All words in the DB now come from the official DWDS Goethe-Zertifikat
lists. See M1-DWDS below.

---

## M1-DWDS — Seed ingest from DWDS Goethe-Zertifikat word lists

The authoritative word lists are published by DWDS for the Goethe-Zertifikat
levels A1, A2, B1. Source: https://www.dwds.de/d/api#wb-list-goethe

- CSV: `https://www.dwds.de/api/lemma/goethe/{A1,A2,B1}.csv`
- JSON: `https://www.dwds.de/api/lemma/goethe/{A1,A2,B1}.json`

🟢 `ingest/goethe.py` — fetch DWDS Goethe word lists (CSV):
   - Fetch all three CSV files at once via httpx.
   - Parse each row into `(lemma, url, pos, genus, article, onlypl)`.
   - CSV columns: `Lemma`, `URL`, `Wortart`, `Genus`, `Artikel`, `nur_im_Plural`.
   - Save raw CSV to `data/goethe/` cache (idempotent, re-fetch only on cache miss).
   - Normalize DWDS wordart to our `pos` mapping (e.g. `"Substantiv"` → `"noun"`).
   - For nouns, populate `article` from the `Artikel` column (e.g. `"der, das"`).
   - Tag each word with its CEFR level (`A1`, `A2`, `B1`).

🟢 `ingest/pipeline.py goethe` subcommand — upsert Goethe words into `Word` table:
   - Dedup on `(lemma, pos)` — the same word can appear across levels (e.g. `Haus` in A1 + B1);
     when that happens, keep the *lowest* level (most basic).
   - Set `source_ref = "dwds:goethe:{level}"`.
   - Print summary per level.

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

## M2 — Definitions from DWDS via HTML parsing

**Definitions are NOT available through any documented DWDS API.** The
`/api/wb/snippet` endpoint only returns metadata (lemma, wortart, url).
The `/wb/{lemma}` HTML page is the only reliable source for German-only
definitions, register/domain markers, and embedded corpus examples.

🟢 `ingest/dwds.py`:
   - Fetch `/wb/{lemma}` HTML page via httpx.
   - Parse with selectolax to extract 1..n `Sense.definition_de` from
     `div.dwdswb-lesart` / `span.dwdswb-definition` selectors.
   - Extract register (`span.dwdswb-stilebene`) and domain (`span.dwdswb-stilfaerbung`).
   - Embed corpus examples from `span.dwdswb-belegtext` as fallback.
   - Cache raw HTML to `data/dwds_cache/`.
🟢 `ingest/pipeline.py enrich` upserts senses.
🟢 Word detail page: monolingual definition, examples, attribution to dwds.
🟡 Fallback: if dwds lookup fails, mark `Sense.definition_de = NULL` and surface a "Definition fehlt" badge.
🟢 Tests: snapshot parser against 10 saved HTML fixtures (covers nouns, verbs, particles).

**Demo:** click any A1 word → German definition + corpus examples render.

---

## M2a — Corpus examples via DWDS API (replaces HTML-embedded examples)

The HTML pages embed corpus examples as `dwdswb-belegtext` spans, but these are
limited in number and quality. The DWDS korpus search API at
`https://www.dwds.de/r/?q={lemma}&view=json&format=full&limit=10` returns
richer, more diverse sentences with proper bibliographic metadata.

🟢 `ingest/dwds.py` — add `fetch_corpus_api(lemma, limit=10)`:
   - Call `https://www.dwds.de/r/?q={lemma}&format=full&view=json&limit=10&corpus=kern`
     using the `kern` corpus (higher quality, literary sources).
   - Parse the JSON response; extract sentence text from `ctx_` arrays
     by concatenating all `w` tokens with `ws=1` (non-space-separated tokens get `ws=0`).
   - Cache responses in `data/dwds_cache/corpus/{lemma}.json`.
   - If kernel corpus returns less than N results, supplement with `corpus=dwdsxl`.
   - On pipeline enrich: prefer API examples; fall back to HTML-embedded `belegtext`.

🟢 Pipeline option: `uv run ingest enrich --corpus-api` enables API-based
   example fetching specifically (vs HTML scraping).

🟡 Graceful degradation: if the korpus API returns 0 results (rare words),
   fall back to examples extracted from HTML.

🟢 Tests: fixture JSON responses from korpus API; parser reconstructs
   sentences correctly from structured KWIC data.

---

## M2b — IPA pronunciation via API

The `/api/ipa/?q={lemma}` endpoint returns IPA notation — no HTML scraping needed.

🟡 `ingest/dwds.py` — add `fetch_ipa(lemma)`:
   - Call `https://www.dwds.de/api/ipa/?q={lemma}`.
   - Parse JSON response; populate `Word.ipa` with the first result.
   - Cache to `data/dwds_cache/ipa/{lemma}.json`.

🟡 Pipeline: optionally fetch IPA during enrichment (`--with-ipa`).

---

## M3 — Spaced repetition core - Completed

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
🔵 Collocations panel ("Typische Verbindungen") from DWDS — extracted from cached HTML.
🔵 Verb conjugation table from Verbformen.
🔵 Synonyms / antonyms (OpenThesaurus) — future work (not implemented).

---

## M8a — Project-defined B2 common-word layer

There is no official DWDS/Goethe B2 word list available in the same way as the
A1/A2/B1 Goethe-Zertifikat lists. Do **not** search for or import an unofficial
B2 list. Instead, define a reproducible in-project approximation using DWDS data.

**Definition for now:** B2 means “the best 1,000 common contemporary DWDS
dictionary lemmas after removing official Goethe A1/A2/B1 words.” This is a
project label, not a claim of official CEFR certification.

### Lower bound — define first

🟢 A candidate is allowed into the B2 pool only if:
   - Its `(lemma, pos)` is not already present in Goethe A1/A2/B1.
   - It has a DWDS dictionary entry URL.
   - It has a useful learner POS (`Substantiv`, `Verb`, `Adjektiv`, `Adverb`, plus
     a small number of high-utility connectors/particles/pronouns).
   - It has usable DWDS frequency data from `GET /api/frequency/?q={lemma}`;
     rank primarily by raw `hits`, with the 0–6 `frequency` bucket kept only as
     an audit/sanity signal.

This lower bound gives “beyond B1” plus “still common enough to learn early.”

### Upper bound — make it top-N, not a frequency range

🟡 Do not define B2 with a fixed frequency interval. A range can still include
bad learner words and exclude better ones. The practical upper bound is the
**1,000th accepted candidate** after scoring, POS balancing, and review. If the
tail of the top-1,000 is too specialist, too transparent/compound-heavy, or too
easy, adjust the scoring and exclusions, then regenerate the same 1,000-word
target.

### Candidate-generation plan for 1,000 B2 words

🟡 `ingest/b2.py` or equivalent pipeline step:
   - Load DWDS headwords from `dwdswb-headwords.json` or the DWDS Lemmadatenbank
     export if we need complete frequency-class data.
   - Exclude all Goethe A1/A2/B1 `(lemma, pos)` pairs.
   - Fetch/cache DWDS frequency responses; batch with pipe-separated `q` where
     appropriate.
   - Reject likely noise: proper names, affixes, spelling variants, regional-only
     forms, historical-only terms, opaque narrow-domain compounds, multiword
     expressions unless highly useful, and entries whose `/wb/{lemma}` page yields
     no parseable definition.
   - Rank primarily by `hits`, with `frequency` as a coarse bucket/check rather
     than a level definition.
   - Score for learner usefulness before taking the top 1,000. Useful candidates
     should be common, semantically general, definable from DWDS, likely to occur
     across several contexts, and not merely an obscure compound that wins by raw
     corpus count.
   - Stratify the final 1,000 so the list is broad, not noun-only:
     - ~450 nouns
     - ~220 verbs
     - ~220 adjectives/participial adjectives
     - ~70 adverbs
     - ~40 connectors/particles/pronouns/other function words
   - Persist as `level = "B2"`, `source_ref = "dwds:b2:auto:v1"`, and store both
     DWDS `frequency` bucket and raw `hits` for later recalibration.
   - Reuse the existing enrichment path: DWDS HTML definitions, corpus API
     examples, optional IPA.

🟡 Add a review/export command:
```
uv run ingest b2-candidates --limit 1000 --review-csv data/b2_candidates.csv
```

The CSV should include lemma, POS, DWDS URL, frequency bucket, hits, score,
exclusion reason if rejected, and source_ref. This makes the generated B2 layer
auditable before it becomes part of the main learning corpus, especially the last
100 included candidates and first 100 excluded candidates.

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

## Summary: API vs HTML scraping

| Data | Source | Method | Status |
|---|---|---|---|
| Word lists (A1/A2/B1) | `GET /api/lemma/goethe/{level}.csv` | CSV API | ✅ Done (M1-DWDS) |
| Definitions | `GET /wb/{lemma}` | HTML scraping | ✅ Done (M2) — no API alternative |
| Corpus examples | `GET /r?q={lemma}&view=json` | JSON API | ✅ Done (M2a) |
| IPA | `GET /api/ipa/?q={lemma}` | JSON API | ✅ Done (M2b) |
| Frequency | `GET /api/frequency/?q={lemma}` | JSON API | 📋 Future |
| Collocations | `GET /wb/{lemma}` | HTML scraping | 📋 Future — no API |
| Conjugations | Verbformen (external) | HTML scraping | 📋 Future |

---

## Suggested implementation order for next steps

```
M1-DWDS (fetch + seed Goethe lists)               — done
    ↓
M2a    (korpus API examples instead of HTML)       — done
    ↓
M2b    (IPA via API)                                — done
    ↓
Re-enrich all Goethe words: dwds definitions (HTML) + API examples + IPA  — next
```

The existing M3/M4/M5/M6/M7/M8/M9 features are all complete and work with
whatever words are in the DB — they don't care whether words came from vocabeo
or Goethe lists.
