# Fitbod exercise catalog — scraped dataset

Scraped 2026-07-02/03 for the fitness platform's workout-generation work
(the "big db with exercises" behind fitbod.me/workouts). **Not yet imported
anywhere** — incorporation into the `exercises` table is a separate, later task.

## What's here

| File | Contents |
|------|----------|
| `fitbod_exercises.json` | **1,067 exercise records** (full detail; see schema below) + `_meta` provenance |
| `fitbod_summaries.json` | 9 exercises seen only in index-page listings (no archived detail page — obscure BOSU variants) |
| `overlap_report.json` | Vocabulary + name-overlap analysis vs our seeded free-exercise-db library |
| `scrape_fitbod.py` | The acquisition tool (`fetch` / `parse` stages, resumable) |
| `analyze_overlap.py` | Regenerates `overlap_report.json` (reuses `backend/app/services/matcher.py` rules) |

Raw page cache (201 MB, re-parse source): `~/.cache/fitbod-scrape/raw/` —
kept out of the repo. `targets.json`/`slugs.txt`/logs live alongside it.

## How it was acquired (provenance)

- fitbod.me sits behind an aggressive Cloudflare bot wall (even `robots.txt`
  is challenged), so the **live site was never crawled**. All content comes
  from **Internet Archive Wayback Machine snapshots** (2025–2026 captures),
  enumerated via the CDX API (1,098 unique `/exercises/<slug>` URLs from
  2,673 archived variants) and fetched politely (keep-alive, ≤5 concurrent,
  global pacing, backoff).
- Each page is a Next.js App Router document; the full exercise entity is
  embedded as JSON in the React flight stream (`self.__next_f.push`) — the
  parser decodes that stream, so there are no HTML-heuristic fields.
- Per-record provenance: `_source_url`; fetch log has the exact snapshot
  timestamp per slug. 1,098/1,098 pages fetched, 0 parse failures.
  Of the 1,098 pages: 1,067 exercise details + 31 muscle/equipment index pages.

## Record schema (as published by Fitbod)

Key fields per record (identical to Fitbod's own app data model):

- `name`, `slug`, `id`, `externalResourceId`, `level`
  (beginner 690 / intermediate 308 / advanced 69), `isBodyweight` (542 true)
- `primaryMuscleGroups` / `secondaryMuscleGroups` — 16-label vocabulary:
  abductors, abs, adductors, **back**, biceps, calves, chest, forearms,
  glutes, hamstrings, lower-back, neck, quadriceps, shoulders, trapezius,
  triceps
- `equipment[]` — name + Fitbod equipment id + icon URL; **69 equipment
  kinds** (much richer than free-exercise-db's vocabulary)
- `instructions[]` (step-by-step prose), `description` (prose), `proTips[]`
- `imageUrl` / `videoUrl` / `videoUrlMobile` — Fitbod CDN links (not mirrored)
- `muscleGroupRanking`, `popularityRanking`, `efficacyRanking` — Fitbod's
  per-muscle effectiveness scores and app-wide popularity ranks
- `_related_exercises[]` — **substitution data**: the exercises users most
  often replace this one with, with real frequencies (`strategy:
  "most-replaced"`) — directly useful for equipment-constrained swaps in our
  generator
- `_page_title`, `_source_url`, `author` (Fitbod's credited trainer)

## Overlap vs our current library (free-exercise-db, 873 seeded)

Using the same conservative normalise+alias rules as the Fitbod-CSV import
matcher: **170 name-matched**, **897 new-to-us**, 714 library-only. The
catalogs are largely complementary; true semantic overlap is higher than 170
(naming conventions differ — e.g. machine/band/BOSU/TRX variants), so any
import should extend the alias table rather than trust exact names.

Muscle-vocabulary mapping to our `MuscleGroup` enum (17 labels) is nearly 1:1:
`abs→abdominals`, `trapezius→traps`, `lower-back→lower back`,
`quadriceps→quadriceps`; **`back` is coarser than our `lats`/`middle back`**
(needs a split rule or a default), `neck` maps directly; Fitbod has no
obliques/middle-back labels.

## Licensing / usage note (read before importing)

Exercise **facts** (names, muscle groups, equipment, level, rankings,
substitution frequencies) are non-copyrightable data and safe to use as
generator inputs. The **prose** (`description`, `instructions`), **media
URLs** (their CDN), and trainer attributions are Fitbod's copyrighted
content: keep them for private/reference use, but don't republish them
verbatim in user-facing surfaces (repo convention: "no copyrighted text" —
see `services/program_templates.py`). If we import, prefer: facts from this
dataset + instructions from free-exercise-db (public domain) or self-written.
The tooling + facts-only outputs are committed; **`fitbod_exercises.json`
itself is gitignored** (it embeds the copyrighted prose) — vendoring it into
the GitHub-mirrored repo is a licensing decision to make explicitly. It lives
on the devvm here and re-materialises from the raw cache via
`scrape_fitbod.py parse`.

## Re-running

```bash
# refresh URL inventory (CDX) -> ~/.cache/fitbod-scrape/{slugs.txt,targets.json}
# (see git history of this README / scrape_fitbod.py docstring)
python3 scrape_fitbod.py fetch   # resumable; skips cached pages
python3 scrape_fitbod.py parse   # rebuilds fitbod_exercises.json
python3 analyze_overlap.py       # rebuilds overlap_report.json
```

## Not done (later / optional)

- **DB incorporation** — the actual task this feeds ("generate workouts
  from"): mapping into `exercises`/`exercise_muscles`, dedup vs the seeded
  library, equipment-vocabulary reconciliation with Gym Profile.
- `/workouts/*` facet pages (7,364 archived) — Fitbod's *generated workout
  examples* (3 workouts per page: exercises + per-set reps). Derivative
  content; our generator derives from Principles (ADR-0004). Enumerable the
  same way if ever wanted (e.g. to benchmark our generator's output).
- The 9 summary-only BOSU variants (no archived detail pages) — could be
  fetched from the live site via `homelab browser` if ever needed.
