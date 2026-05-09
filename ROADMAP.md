# ROADMAP — *deutsch-haufig*

Incremental, demo-able milestones. Each milestone ships something usable end-to-end.

Legend: 🟢 must-have · 🟡 should-have · 🔵 nice-to-have

---

## M0 — Project skeleton - Completed

## M1 — Seed ingest from vocabeo - Completed

## M2 — German definitions & examples from dwds — Completed

## M3 — Spaced repetition core - Completed

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
