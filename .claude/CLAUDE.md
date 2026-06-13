# Apple Health Dashboard — Project Knowledge

> **Direction (2026-06-12):** this app is being extended into a multi-user fitness platform
> (Fitbod + MyFitnessPal replacement). Read `CONTEXT.md` (vocabulary), `docs/adr/`
> (decisions), and `docs/plans/2026-06-12-fitness-platform-roadmap.md` before working here.

## Overview

Full-stack Apple Health data dashboard: FastAPI backend, SvelteKit frontend, Postgres,
Authentik forward-auth identity (ADR-0003; in-app WebAuthn retired). Imports Apple Health
XML/ZIP exports and provides interactive visualizations.

## Architecture

```
SvelteKit (:3000) → /api/*  → Backend (FastAPI :8000, internal proxy)
                  → /*      → SvelteKit SSR
```

**Stack:** Python 3.12, FastAPI, SQLAlchemy async + asyncpg, Postgres (TimescaleDB image in
local docker-compose only — prod is plain Postgres on the shared CNPG cluster), SvelteKit, Docker Compose

## Running Locally

```bash
docker-compose up --build        # Start all services
# Frontend: http://localhost:8080
# API: http://localhost:8080/api
# Health check: curl http://localhost:8080/api/health
```

Database: `postgresql+asyncpg://health:<DB_PASSWORD>@db:5432/apple_health`

## Backend Structure

```
backend/app/
├── api/           # Route handlers
│   ├── router.py  # Aggregates all sub-routers
│   ├── auth.py    # /api/auth — /me (returns the forward-auth user)
│   ├── dashboard.py  # /api/dashboard — summary endpoint
│   ├── metrics.py    # /api/metrics — available metrics + time-series queries
│   ├── workouts.py   # /api/workouts — list/detail with route points
│   ├── activity.py   # /api/activity — activity rings
│   ├── ingestion.py  # /api/import — upload/status/cancel/delete (Apple Health XML/ZIP)
│   ├── fitbod.py     # /api/import/fitbod — preview + commit (Fitbod CSV import, #9)
│   ├── exercises.py  # /api/exercises — browse/search/detail/create-custom (Exercise library)
│   ├── export.py     # /api/export — streamed full per-user data archive (ZIP of JSON+CSV, #19)
│   ├── sessions.py   # /api/sessions — Session/Set logging CRUD + set add/edit/delete/reorder/finish
│   ├── principles.py # /api/principles — browse/scope-by-(goal,experience)/lookup-by-key (cited KB)
│   ├── recommendations.py # /api/recommendations — freestyle + today (autoregulated) + adjust preview/start
│   ├── programs.py   # /api/programs — generate (quiz/preset)/list/active/get/activate/delete (#13)
│   ├── readiness.py  # /api/readiness — daily biometric 0–100 signal (HRV/RHR/sleep vs baseline) (#14)
│   └── nutrition.py  # /api/nutrition — Food catalog + Diary CRUD + day/history (#21); barcode→OFF, custom Foods, Recipes (#22)
├── core/
│   ├── dependencies.py # get_current_user (X-authentik-email → get-or-create User)
│   └── exceptions.py
├── migrations_support/ # Logic invoked by Alembic migrations + unit-tested directly
│   └── user_reconciliation.py  # Idempotent prod-user → Authentik-email reconcile
├── models/        # SQLAlchemy ORM (see DB Models below)
├── schemas/       # Pydantic request/response models
├── services/
│   ├── xml_parser.py  # Producer-consumer XML parsing pipeline
│   ├── dedup.py       # Bulk insert with COPY + ON CONFLICT DO NOTHING
│   ├── seed_exercises.py  # Idempotent Exercise-library seed from vendored free-exercise-db
│   ├── effort.py      # Pure Effort RIR↔RPE mapping (one-tap chip ↔ stored RPE-equivalent)
│   ├── volume.py      # Pure volume helper (encodes the non-normal-set exclusion)
│   ├── e1rm.py        # Pure estimated-1RM core (1-rep-anchored Epley + optional RIR adjust)
│   ├── pr.py          # Pure PR detection (4 dimensions; normal-only; strict-improvement)
│   ├── pr_service.py  # PR persistence: prior-bests-from-history + authoritative upsert
│   ├── readiness.py   # Pure daily biometric Readiness core (HRV/RHR/sleep vs baseline) (#14)
│   ├── autoregulation.py # Pure day-adjuster: trim/keep within Principle bounds + early-deload (#14)
│   ├── adjust.py      # Conversational-adjust ABC + deterministic provider + validate/apply (#14)
│   ├── adjust_agent.py # Gated claude-agent-service adjust provider (proposes-only; falls back) (#14)
│   ├── fitbod_parser.py # Pure Fitbod-CSV parser (by column NAME; kg/lb; warmup; group→Sessions; skip cardio) (#9)
│   ├── matcher.py     # Pure exercise-name matcher (normalise + alias; unresolved→manual) (#9)
│   ├── fitbod_import.py # Fitbod import DB glue: preview + idempotent (Session-grain) commit + PRs + Source (#9)
│   ├── nutrition.py   # Pure macro-totalling core (Σ Food per-serving macros × quantity; per-meal+day; round-once) (#21)
│   └── seed_foods.py  # Idempotent generic whole-foods Food-catalog seed (in-code; upsert by slug) (#21)
├── data/          # Vendored datasets (free_exercise_db.json, pinned by .SHA)
├── config.py      # Pydantic settings from env
├── database.py    # Engine + session factory (pool_pre_ping=True)
└── main.py        # FastAPI app
```

## DB Models & Key Indexes

| Table | PK | Key Indexes |
|-------|-----|-------------|
| `health_records` | (time, user_id, metric_type) | (user_id, metric_type, time), (batch_id) |
| `category_records` | (time, user_id, category_type) | (batch_id) |
| `workouts` | id (UUID) | UNIQUE(user_id, time, activity_type), (batch_id) |
| `workout_route_points` | (time, workout_id) | (workout_id) |
| `activity_summaries` | (date, user_id) | — |
| `users` | id | UNIQUE(email) |
| `data_sources` | id | UNIQUE(name, bundle_id) |
| `import_batches` | id (UUID) | — |
| `exercises` | id (UUID) | partial-UNIQUE(slug) WHERE user_id IS NULL, partial-UNIQUE(user_id, slug) WHERE user_id IS NOT NULL, (user_id) |
| `exercise_muscles` | id | UNIQUE(exercise_id, muscle, role), (muscle) |
| `training_sessions` | id (UUID) | (user_id, started_at) |
| `training_sets` | id (UUID) | UNIQUE(session_id, order_index), (session_id, order_index), (exercise_id) |
| `personal_records` | id (UUID) | partial-UNIQUE(user_id, exercise_id, kind) WHERE weight_bucket IS NULL, partial-UNIQUE(user_id, exercise_id, kind, weight_bucket) WHERE NOT NULL, (user_id, exercise_id) |
| `principles` | id (UUID) | UNIQUE(key), (category) |
| `principle_citations` | id | UNIQUE(principle_id, title) |
| `programs` | id (UUID) | partial-UNIQUE(user_id) WHERE status='active', (user_id) |
| `program_days` | id (UUID) | UNIQUE(program_id, day_index) |
| `program_muscle_volumes` | id | UNIQUE(program_id, muscle, week) |
| `foods` | id (UUID) | partial-UNIQUE(slug) WHERE user_id IS NULL, partial-UNIQUE(user_id, slug) WHERE user_id IS NOT NULL, (user_id) |
| `diary_entries` | id (UUID) | (user_id, entry_date) |
| `recipes` | id (UUID) | UNIQUE(food_id), (user_id) |
| `recipe_ingredients` | id (UUID) | (recipe_id), (food_id) |

**Exercise library** (the shared movement catalog — CONTEXT.md "Exercise"): `exercises.user_id`
NULL = global/shared (seeded from free-exercise-db), non-NULL = that user's private custom
Exercise; browse = global ∪ own. Two partial unique indexes key the natural key `slug`
separately per namespace (NULLs compare distinct in a plain unique). Muscle mappings are
normalized in `exercise_muscles` with `muscle` a native Postgres enum (17 dataset groups) +
`role` enum (primary/secondary) — a GROUP-BY-able dimension for Recovery/volume analytics, not
free text. Demo-video link = computed YouTube "proper form" search URL (no hosted video).
Images = jsDelivr CDN URLs (no binaries vendored). API: `/api/exercises` (browse with
search/muscle/equipment filters, detail, create-custom, `/muscles` + `/equipment` options).

**Session/Set logging** (the live gym-logging core — CONTEXT.md "Session"/"Set"; **offline-first**,
ADR-0005, #6). A **Session** is what the user logs live (NOT a `Workout`, which is reserved
for imported sensor records). Tables are named `training_sessions`/`training_sets` because
`session`/`set` collide with reserved/auth identifiers; the API/URL vocabulary stays the clean
"session"/"set". A `training_set` references exactly one `exercise` (visibility-checked: global ∪
own), records `weight_kg × reps`, a native-enum `set_type` (normal/warmup/drop/failure, default
normal), and optional **Effort** stored as the RPE-equivalent in the `rpe` column. Effort travels
the API as **RIR** (one-tap chip 0–4, 4 = "4+") and is mapped to/from RPE by the pure
`services/effort.py` (`rir_to_rpe`: 0→10, 1→9, 2→8, 3→7, 4+→6). Non-normal set types are excluded
from volume/PR stats — `services/volume.py` is the single source of that rule (PR/analytics slices
inherit it). Set order is an explicit 0-based `order_index` kept gap-free server-side (append on
add, compact on delete, two-phase rewrite on reorder). All endpoints are per-user scoped via
`get_current_user`; a Set is reached only through its owning Session. API: `/api/sessions`
(start/list/get/finish/delete a Session; `/{id}/sets` add, `/{id}/sets/{set_id}` PATCH/DELETE,
`/{id}/sets/order` PUT reorder). **Client-supplied ids** (#6): `SessionCreate`/`SetCreate` accept an
optional `id` the offline client mints up front, so a queued create replays idempotently — the
server uses it when present (else generates uuid4), and `add_set` returns the existing Set on a
replayed id (no duplicate, no `(session_id, order_index)` collision) rather than re-inserting.

**Offline-first sync** (the gym-dead-zone logger — CONTEXT.md "offline"; ADR-0005; #6). The
logging surface works fully offline; writes are captured in an **IndexedDB op-queue** and synced
to `/api/sessions...` when connectivity returns (and on app reload while online). The frontend
layer is `frontend/src/lib/sync/`:
- **`queue.ts`** — the PURE, IO-free core (vitest `queue.test.ts`): a FIFO `SyncOp` log
  (startSession / addSet / patchSet / deleteSet / reorderSets / finishSession / deleteSession),
  `applyOps` to fold it onto a base snapshot into the optimistic view, `collapseQueue` to drop ops
  that cancel out (a Set created-then-deleted offline vanishes; patches fold into a still-local
  create — **replay-invariant**), and `reconcileServerSession` to re-apply still-pending ops over a
  fresh server snapshot. **Last-write-wins per record** (single-device — accounts isolated ADR-0003;
  no CRDT). **Client-minted UUIDs ⇒ the optimistic id IS the server id, no remap.**
- **`store.ts`** — IndexedDB persistence (`idb`): durable `ops` (FIFO), `snapshots` (last server
  snapshot per Session, so a reload rebuilds offline), `kv` (prefetched context). Guarded for SSR.
- **`engine.ts`** — drains the queue head-first while online (on enqueue, on the `online` event, on
  app load); preserves order (stops at the first transient failure, retries the tail); drops only a
  permanent 4xx so one poisoned op can't wedge the queue. Tested in `engine.test.ts` (mocked api).
- **`session-store.svelte.ts` / `sessions-list.svelte.ts`** — Svelte 5 runes data layer the
  `/sessions` pages bind to: optimistic snapshot + enqueue, reconcile-on-drain, start-a-Session
  offline. **`sync-state.svelte.ts`** + `components/sessions/SyncIndicator.svelte` are the trust
  signal ("Offline — N queued" / "Syncing…" / "Synced", tap-to-retry).
The **service worker stays `generateSW`** (shell-only): the queue runs IN THE PAGE, not the SW, and
`/api/*` is deliberately never cached (caching mutations would be wrong). Supersets are expressed
offline as `superset_group` patches (replayed through the normal Set-patch endpoint), so the
client no longer needs the `/supersets` endpoints (kept server-side for compatibility). Client-side
PR detection (`lib/pr.ts`) fires offline; the server reconciles authoritative PRs on sync.

**PR detection + e1RM** (the strength-signal engine core — CONTEXT.md "PR"). Two **pure** modules
are the canonical definitions reused by analytics (#10) and progression (#11): `services/e1rm.py`
(estimated 1RM = **1-rep-anchored Epley** `w·(1 + (reps-1)/30)` so reps=1 → exactly the weight;
optional Effort adjustment folds RIR in as `effective_reps = reps + rir` — a set with reserve is
heavier, so the estimate rises and never falls) and `services/pr.py` (`detect_prs` over four
dimensions — best **weight**, best **e1rm**, best **reps_at_weight** keyed per load, best single-set
**volume**; only `normal` sets via `volume.counts_for_volume`; strict improvement so ties aren't PRs;
first-ever set PRs on every dimension). The algorithm is **mirrored in TypeScript**
(`frontend/src/lib/pr.ts`, with `pr.test.ts` mirroring the backend cases) so PR detection fires
**instantly client-side while offline** (ADR-0005) with no round-trip. The backend is the
record-of-truth: `services/pr_service.py` recomputes prior-bests-from-history (excluding the
candidate set) on every add/edit and upserts authoritative `personal_records`, so deletes/edits/
offline races never leave a false or duplicate PR. `POST /{id}/sets` and `PATCH /{id}/sets/{set_id}`
return any PRs in a `prs` field (→ the live `PRCelebration` banner); `GET /api/sessions/prs?exercise_id=`
lists the persisted records. `personal_records` is one row per (user, exercise, kind, weight_bucket)
— `weight_bucket` NULL for the three weight-independent kinds, the load for `reps_at_weight` — keyed
by two partial unique indexes (NULLs compare distinct in a plain unique) so it never double-counts.

**Principles KB** (the cited exercise-science rules — CONTEXT.md "Principle"; ADR-0004; #12). The
versioned knowledge base the Program generator (#13) composes from and the receipts UI (#14) taps,
so every prescribed training parameter traces to peer-reviewed evidence. `principles` is one row per
rule keyed on a stable `key` slug (e.g. `volume-dose-response`): a `statement`, a native-enum
`category` (volume/frequency/intensity/progression/periodization/deload/rest/nutrition), a **JSONB
`params`** dict of typed ranges the generator reads (`{name: {min?, max?, value?, unit?}}`, e.g.
`{"sets_per_muscle_per_week": {"min":10,"max":20,"unit":"sets"}}`), applicability as two JSONB arrays
(`goals` over the `training_goal` enum bulk/cut/maintain/strength, `experience_levels` over
`experience_level` beginner/intermediate/advanced — **empty array ⇒ applies to all**), a native-enum
`evidence_grade` (A/B/C = strong/moderate/limited), and a `version` + `updated_at` (the seed bumps
`version` only when a rule's substance changes). `TrainingGoal`/`ExperienceLevel` live in
`models/principle.py` — the canonical home for the CONTEXT.md Goal vocabulary #13/#15 consume.
Citations are normalized one-to-many in `principle_citations` (authors/year/title/journal + DOI/PMID/URL;
`resolved_url` prefers explicit URL → doi.org → PubMed). The query interface is
`services/principles_query.py`: `applicable_principles(goal, experience, category)` (the SQL
applicability filter — empty list OR JSONB-contains — mirrored by `Principle.applies_to`),
`principle_by_key`, and `list_principles`. API `/api/principles` (browse, or scope by
`?goal=&experience=`; `/categories`; `/{key}`) is auth-gated and read-only — content is seed-managed.
The KB is **in-code** (`services/seed_principles.py`'s `PRINCIPLES`, idempotent upsert by `key` + citation
reconciliation), not a vendored dataset, because it is small and hand-authored; **every citation was
verified against PubMed/DOI at authoring time** (verification log in the seed module docstring) — never
fabricate or paraphrase an unverified source. Task #13 added one rule, `rep-scheme` (`intensity`;
goal-specific rep ranges, cited Schoenfeld 2017 loading meta-analysis + Schoenfeld 2021 rep continuum),
so the Program generator derives rep ranges from the KB too rather than hardcoding them.

**Goal-driven Programs** (the generated multi-week schedule — CONTEXT.md "Program"; ADR-0004; #13). A
**Program** is generated **only from the Principles KB** by a deterministic, pure core
(`services/program_generation.py` — no DB, no clock, no LLM; #14 is the LLM layer): a `QuizInput` (goal,
experience, days/week, session length) + the Principles applicable to `(goal, experience)` →
`GeneratedProgram`. **Every numeric parameter is derived from a Principle's `params` range** (pick rule:
midpoint-rounded-clamped for a `{min,max}`, direct read for a `{value}`; effort = top of the RIR range)
and recorded in a **`provenance`** receipt `{param: {principle_key, value, unit, min?, max?}}` so #14 can
show "why this number"; a missing required Principle **raises** rather than inventing a number. Two
honesty rules learned from a review: (1) the **deload** volume cut reads the deload rule's *volume* param
(`deload_volume_reduction_percent`, a real cited param) — NOT its load param — and is anchored off the
ramp's **week-1 floor** (`round(floor·(1−pct/100))`, clamped strictly below the floor) so the deload is
clearly fewer sets than EVERY accumulation week (anchoring off the *top* made it land on the floor → an
invisible deload); (2) `progressive-overload.load_increase_percent` is a percent the per-set engine
(kg-based double-progression) doesn't apply, so it is **not** faked into the receipt. The mesocycle source
(`periodization` vs the universal `deload` cadence) is decided by **whether `periodization` is in the
injected applicable set** (the query layer's filter is the single source of its applicability — the
generator never re-encodes it). The split shape comes from `services/program_templates.py` (full-body /
upper-lower / PPL keyed by days/week — generic structures, no copyrighted text). Only **2×-compliant**
splits are offered per day count (PPL needs ≥6 days; at 3 days only full-body — a PPL@3 would be 1×/week),
and `generate_program` **asserts** the `training-frequency` floor on the BUILT split at runtime
(`FrequencyFloorError`); the floor is enforced for `MAJOR_MUSCLES` (compound primary movers), and the
session-length slot cap trims **accessories first** so a major muscle is never dropped below the floor. The
**preset catalog** (`services/program_presets.py`: GZCLP, Upper/Lower, PPL, 5/3/1-style) is just **pinned
`QuizInput`s fed through the same generator** — numbers still from Principles. Persistence
(`services/program_query.py`) is three tables (`programs` header + `provenance` JSONB; `program_days` split
slots; `program_muscle_volumes` the **ramping** weekly per-muscle target that drops on the scheduled
**deload** week) with **one active Program per user** (partial unique index `WHERE status='active'`;
generating archives the prior, kept not deleted). The daily Recommendation path (#11) is extended:
`recommendation_query.recommend_today` → `services/program_recommendation.py` when a Program is active
(today = the Program's next due day — `(#Sessions since created) mod days/week` — its slots filled via the
existing **Progression** core, constrained by the Gym Profile; deload week reduces sets), else the freestyle
generator. Starting it reuses
#11's `instantiate_session` (a `Recommendation` of pre-filled Sets — no prescribed-state column). API
`/api/programs` + `/api/recommendations/today[/start]`. Frontend: `/programs` (catalog + your Programs),
`/programs/quiz`, `/programs/[id]` (overview: weeks/days/volume-ramp + provenance receipts),
`/programs/today`; pure view helpers in `lib/program.ts`.

**Readiness + Autoregulation + Receipts + Adjust** (closing the engine loop — CONTEXT.md "Readiness";
ADR-0002 + ADR-0004; #14). Four pure cores (no DB/clock/LLM; query layers inject data + `now`), mirroring
`recovery`/`recommendation`:
- **Readiness** (`services/readiness.py`, query `readiness_query.py`, API `GET /api/readiness`) — a daily
  per-user **0–100 biometric** signal, **distinct from training-load Recovery (#10)**. Compares the most-recent
  HRV (`HeartRateVariabilitySDNN`), resting HR (`RestingHeartRate`) and sleep-hours (summed `%Asleep%`
  `SleepAnalysis` intervals) reading to the user's **trailing 28-day baseline** (robust deviation
  `(recent−mean)/spread`, spread floored at 5% of mean), orients so higher=better (HRV↑ good, RHR↑ bad, sleep
  saturating-above-baseline), logistic-squashes each to a 0–100 component, blends HRV .5 / RHR .25 / sleep .25
  **renormalised over present metrics**. Missing metric drops out; **no usable metric → `insufficient_data`,
  never a fake number**; at-baseline = neutral 50.
- **Autoregulation** (`services/autoregulation.py`) — adjusts the active Program day's generated set counts on
  Readiness + per-muscle Recovery: a combined factor trims top sets (readiness factor 1.0 at ≥60 → 0.5 at 0;
  per-muscle recovery factor 1.0 at ≥70 → 0.5 at 0), a strong+fresh day (≥85 / recovery ≥70) allows a small
  bump. **Clamped within the Program's Principle volume band** (per-session floor/ceiling from the ramp's
  accumulation weeks); a trim never *raises* an already-reduced **deload**. Emits a human reason. **User-edited
  slots pass through untouched** (cardinal invariant). `early_deload_triggered` (≥3 of last 5 days ≤45) fires a
  **fatigue early-deload**; `reflow_day_index` reflows past missed days. Wired into
  `program_recommendation.recommend_from_program` (injected `readiness`) → surfaced on
  `GET /api/recommendations/today` as `program.autoregulation` (`adjusted`/`reason`/`readiness`/`early_deload`).
- **Receipts UI** — every generated parameter taps to **`/principles/[key]`** (new route: statement + cited
  ranges + studies); `/programs/[id]` gained a "science behind this plan" Principle list (evidence grades +
  citation counts) and range-annotated tappable receipts; the dashboard `ReadinessCard` shows the score + the
  per-metric "X below your baseline" breakdown.
- **Conversational adjust** (`services/adjust.py` + `adjust_agent.py`, API `POST /api/recommendations/adjust[/start]`)
  — a swappable **`AdjustProvider` ABC**. The **`DeterministicAdjustProvider` is the default** (rules-based parse
  of "make it shorter / no barbell / I'm tired / dumbbells only" into bounded levers `volume_scale` /
  `exclude_equipment` / `max_exercises`) so it ships working with **no external service**. `ClaudeAgentAdjustProvider`
  (gated behind `ADJUST_PROVIDER=claude-agent`, default OFF) calls claude-agent-service's OpenAI-compatible
  `/v1/chat/completions` and **proposes only**: its JSON is parsed then **validated/clamped to Principle bounds
  by `validate_adjustment` (the engine's authority)** before `apply_adjustment` produces editable targets;
  falls back to deterministic on any error. The `today` page has a reason banner + conversational adjust UI;
  pure helpers in `lib/readiness.ts` (+ `lib/program.ts` receipt/grade helpers). **No new DB tables** — Readiness
  reads existing health tables; autoregulation/adjust are in-memory transforms (Alembic head unchanged).

**Fitbod CSV import** (the set-level strength-history seed — CONTEXT.md "Import"/"Source"; #9). Imports a
user's Fitbod "Export Workout Data" CSV into the live Session/Set tables — the only source of set-level
strength history, so it seeds Progression/Recovery/PRs. Two **pure, tested** cores + a DB-glue + a 2-step API:
- **`services/fitbod_parser.py`** — parses the CSV **by column NAME, not position** (Fitbod's columns vary by
  app version): header is `Date,Exercise,Reps,Weight(kg|lbs),Duration(s),Distance(m),Incline,Resistance,isWarmup,Note,multiplier`;
  the **weight unit lives in the header suffix** (`Weight(kg)` vs `Weight(lbs)`/`(lb)` → lb×0.45359237→kg, unmarked=kg);
  Date is `%Y-%m-%d %H:%M:%S %z` (e.g. `2021-12-27 10:02:51 +0000`, with tz-less/ISO fallbacks). Rows are
  **grouped into Sessions by their Date timestamp** (every set in one workout shares it; `started_at`=that time,
  `ended_at` set since imports are finished historical records); `isWarmup` truthy→`set_type=warmup` else `normal`.
  **Non-strength rows are skipped, not turned into garbage Sets**: weight≤0 AND reps≤0 (cardio/distance/duration-only)
  is dropped + counted in `skipped_rows`; bodyweight (weight 0, reps>0) is kept. Quoted/embedded-comma fields via stdlib `csv`.
- **`services/matcher.py`** — pure exercise-name matcher: `normalize_exercise_name` (lower, `-`/`/`→space, strip
  punct, collapse ws), then exact-normalised match against the visible library, then a **curated alias table**
  (Fitbod "Back Squat"↦library "Barbell Squat", etc.) that only fires when its target exists (never invents a
  match; exact always wins). `ExerciseNameIndex.resolve_all` → `(resolved {name:id}, sorted unresolved)`.
  Deliberately conservative — no fuzzy distance (would silently mis-map); unresolved names go to the manual-match UI.
- **`services/fitbod_import.py`** — DB glue. `preview_fitbod_import` (parse+match, NO writes) returns counts +
  unmatched names + per-name set counts; `commit_fitbod_import` writes idempotently. **Idempotency is at the
  Session grain**: a Session id = `uuid5(NS, f"{user_id}|{started_at_iso}")`, and a Session that already exists for
  the user is **skipped whole** (an imported workout is immutable; we never backfill sets into it) — re-importing
  adds only new workouts. This is both correct semantics AND avoids a `(session_id, order_index)` unique-constraint
  collision that set-level backfill would hit when the resolution set changed across runs (regression-tested). A
  `resolutions` map (raw name→Exercise id from the UI) overrides auto-matches and is **visibility-filtered** (global
  ∪ own — a foreign private id is dropped); still-unresolved names are skipped + counted. PRs are reconciled once
  per touched Exercise (warmup/zero-load excluded by `pr_service`). Registers a **Fitbod `DataSource`** + an
  `ImportBatch` audit row. **No new tables / no migration** (Alembic head unchanged) — reuses `training_sessions`/
  `training_sets`/`data_sources`/`import_batches`.
- **API** `POST /api/import/fitbod/preview` + `/commit` (JSON `csv_text` — the history is KBs, so it travels as text,
  not the multi-GB chunked-multipart Apple Health path; commit re-sends the text + resolutions, stateless + idempotent).
- **Frontend** `lib/fitbod.ts` (`looksLikeFitbodCsv` — pure header sniff to reject a wrong file before upload, vitest)
  + `components/import/FitbodImport.svelte` (mobile flow: upload → preview/summary → resolve unmatched via the reused
  `ExercisePicker` bottom-sheet or "create custom" → confirm → done), wired into the **settings page**.

**Full per-user data Export** (the data-ownership archive — CONTEXT.md "Export"; ADR-0006; #19). One authenticated
action (`GET /api/export`) streams a ZIP of ALL the caller's own data — the read-side mirror of the ingest API.
- **`services/export_archive.py`** is the engine. A declarative **`RecordSpec` registry** (one per record type: name,
  the ordered `(header, attr)` columns, and a `stmt_for(user_id)` user-scoped `Select`) is the **single source of
  per-user scope** — owner tables filter on `user_id` directly; child tables with no `user_id`
  (`training_sets` via Session, `workout_route_points` via Workout) filter through a subquery of the parent rows the
  user owns; **only the user's OWN custom Exercises** are exported (the shared global library is never personal data).
  Covered: Sessions, Sets, Workouts, route points, `health_records`, `category_records`, activity summaries, Programs
  (+ days + muscle volumes + provenance), PRs, custom Exercises, Gym Profile, and **Diary Entries when the nutrition
  tables exist** (probed via `inspect`; skipped gracefully otherwise — nutrition isn't built yet, #21/#22).
- **Streaming is the cardinal engineering constraint** (prod has ~6.6M `health_records` for one user): each record
  type is read through a **server-side cursor** (`AsyncSession.stream(stmt).partitions(chunk_size)`), the ZIP is
  assembled on a `tempfile` **on disk** (one CSV per record type + a single `export.json`), the JSON document is
  written **incrementally** (arrays opened, rows streamed comma-separated, closed — never a whole table in a list),
  and the finished file is streamed back in 64 KB byte chunks then deleted. Peak heap scales with `chunk_size`, NOT
  table size (~2 MB at chunk 500, ~21 MB at the default 5000 — flat regardless of row count). **Two coupled gotchas
  the tests pin**: (1) streaming a whole ORM **entity** returns JSONB columns as a Python-repr `str` — so the engine
  projects **explicit columns** (`with_only_columns`) to get the column result-processors; and (2) the value coercion
  passes `dict`/`list` through **unchanged** (`str(dict)` would emit invalid JSON). Both are required for JSONB
  (`workout.metadata`, `program.provenance`, `program_day.slots`, `exercise.instructions`/`images`, gym_profile lists)
  to round-trip as real structures in both JSON and CSV.
- **Archive layout**: `export.json` (full nested doc: `{user, generated_at, records:{...}}`) + `csv/<record_type>.csv`
  per type (header always present, even for an empty type), all in one ZIP named `health-export-<email>-<UTC>.zip`.
- **No new tables / no migration** (Alembic head unchanged) — read-only over existing tables.
- **Frontend** `lib/export.ts` (`filenameFromContentDisposition` — pure Content-Disposition parser, vitest) + the
  `api.download()` blob-download helper + `components/settings/ExportData.svelte` (one-tap button), wired into the
  **settings page**. YAGNI (ADR-0006): a full archive only — not per-type/selectable export, not scheduling, not
  read-scoped tokens (deferred).

**Nutrition: Food diary + macros** (the MyFitnessPal core — CONTEXT.md "Food"/"Diary Entry"/"Meal"; #21). Two tables:
- **`foods`** — the Food catalog, mirroring the Exercise library's shared+custom design: `user_id IS NULL` = a
  **shared** Food (the generic whole-foods seed, and later the OFF cache, #22), non-NULL = a user's private custom Food
  (#22); browse = global ∪ own. Macros are stored **per serving** (one serving = `serving_size` of `serving_unit`,
  e.g. 100 "g" or 1 "egg") — NOT per-gram, so whole-unit foods ("1 egg", "1 slice", "1 medium") are first-class with no
  density model. `source` (`generic`/`off`/`custom`) + nullable `off_id`/`brand` leave room for the OFF + custom slice
  (#22, NOT built). Two partial unique indexes key `slug` per namespace (same NULL-distinct idiom as `exercises`).
- **`diary_entries`** — a Food logged with a `quantity` to one `meal` (native enum breakfast/lunch/dinner/snack) of one
  `entry_date` (a plain DATE — a Diary Entry is a *day*+Meal, not an instant), **private** to its `user_id` (UUID PK).
- **Quantity semantics (documented decision):** `quantity` is the **number of servings** of the Food; an entry's macros
  = the Food's per-serving macros × quantity. So a 100 g Food at quantity 1.5 → the 150 g values; "Egg, large" at 2 → two
  eggs. The Food stays the single source of macro/unit truth; the entry only scales it.
- **`services/nutrition.py` is the PURE macro-totalling core** (no DB/clock — mirrors `volume.py`/`effort.py`): `EntryMacros`
  value objects → `daily_totals(entries)` → per-Meal + whole-day `MacroTotals`. Sums **unrounded then rounds once** to 1dp
  (per-entry rounding never compounds; per-meal sums reconcile to the day total); empty day = all-zero with every Meal slot
  present. Analytics/Budget (#23) reuse this exact definition. `api/nutrition.py` builds `EntryMacros` from ORM rows and
  feeds the core — never re-deriving the sum.
- **API** `/api/nutrition`: `GET /foods` (catalog search, visible = shared ∪ own), `GET /foods/{id}`, `POST/PATCH/DELETE
  /entries` (Diary CRUD; a logged/swapped Food is visibility-checked → 404 if not visible, no leak), `GET /diary?date=`
  (the day view: four Meal sections + subtotals + day total, all via the pure core; defaults to today), `GET
  /history?start=&end=` (per-day totals for the charts; only days with entries; scoped to the caller). All `get_current_user`-scoped.
- **Seed** `services/seed_foods.py` — ~25 generic whole foods authored in-code (like the Principles KB, not a vendored
  file): idempotent upsert by `slug` among shared rows, never touches custom Foods, runs from `entrypoint.sh` after
  migrations. Per-serving macros are Atwater-consistent (the seed test guards 4/4/9 kcal/g within tolerance).
- **Export** already includes Diary Entries (it probes for the `diary_entries` table and streams it via runtime reflection
  filtered on `user_id`); now that the table exists (#21) a user's diary round-trips through the archive.
- **Frontend** `lib/nutrition.ts` (PURE view-logic, vitest `nutrition.test.ts`: `entryMacros` quantity-scaling mirror,
  `formatMacro`/`formatServing`, `macroCalorieSplit` for the breakdown bar, `historyToSeries` → the chart `{time,value}`
  shape) + `components/nutrition/AddEntrySheet.svelte` (mobile bottom-sheet: search Food → pick → quantity stepper + Meal
  picker + live macro preview → save; also the edit flow) + routes `/nutrition` (day view: four Meals, entries, daily
  total + macro split bar, add/edit/delete) and `/nutrition/history` (calories/macros over a trailing window, reusing
  `BarChart`). Nav: "Nutrition" in the "More" sheet. YAGNI: no barcode/OFF/custom-Foods/Recipes/Budget (#22/#23).

**Nutrition: barcode + Open Food Facts + custom Foods + Recipes** (fast + complete logging — CONTEXT.md "Food"/
"Recipe"; #22). Extends #21 so the user can log packaged products by scanning, and anything via custom Foods/Recipes.
- **Barcode scanning (PWA, client-side)** — `lib/barcode.ts` is the **PURE, tested** scan logic (vitest `barcode.test.ts`):
  `normalizeBarcode` (digits only), `isLikelyBarcode` (6–14 digits, mirrors the backend guard), `pickScanEngine`
  (native `BarcodeDetector` when present else zxing), `ScanDebouncer` (the camera fires the same code on many frames →
  accept a code at most once per 1.5s, a new code instantly). `components/nutrition/BarcodeScanner.svelte` is the thin
  camera glue: native **`BarcodeDetector`** (Chrome/Android, formats EAN-13/EAN-8/UPC-A/UPC-E) with a **`@zxing/browser`**
  `BrowserMultiFormatReader` fallback (iOS Safari etc.), **dynamically imported** so native-capable browsers don't pay for
  it. Camera-permission denial / no-camera / unsupported → a clear message + graceful fallback to manual search (the
  **live camera path needs a real device** — only the pure decision logic is unit-tested).
- **Open Food Facts (server-side, cached)** — a scanned barcode resolves a packaged Food via the OFF v2 public API
  (`https://world.openfoodfacts.org/api/v2/product/<barcode>.json`, no key; a descriptive **User-Agent** is sent; the
  call is **server-side** so the cache is shared and CORS/UA are controlled). `services/off.py` is the **PURE** mapping
  (`map_off_product`, tested): OFF reports macros **per 100 g** (`energy-kcal_100g`/`proteins_100g`/`carbohydrates_100g`/
  `fat_100g`), so the resolved Food has a **100 g serving** and those per-100g values as its per-serving macros — no
  fragile parse of OFF's free-text `serving_size`, no unit guesswork. **Honesty rule** (mirrors the Fitbod skip-don't-
  fabricate): missing energy or **any** macro, or a non-numeric/negative value → **reject** (never a zero-macro Food).
  `services/off_lookup.py` is the **cache+fetch** glue: **cache-first** (a shared `source='off'`, `off_id=<barcode>`,
  `user_id IS NULL` Food) so re-scans/logs are instant and offline-ish and **re-scans hit the cache, not the network**;
  on a miss it fetches + maps + persists, **race-safe** on `uq_food_global_slug` (catch `IntegrityError` → re-select the
  winner); **fail-soft** (not-found / incomplete / network error → None → API 404 → client falls back to manual entry).
  The OFF HTTP client is **injectable** (httpx transport) so tests **mock it and never hit the network**.
- **Custom Foods** — a user creates a private `source='custom'` Food (per-serving macros), visible only to them (global ∪
  own, like Exercises). Editable/deletable **only if it's their own custom** (shared/recipe Foods 404). Editing a custom
  Food's macros triggers the Recipe **compute-on-write fan-out** (below). Delete is RESTRICT-guarded → **409** if the Food
  is still referenced by a Diary Entry or a Recipe ingredient.
- **Recipes** — `services/recipe.py` is the **PURE** macro core (`compute_recipe_macros`, tested): per-serving macros =
  **Σ (ingredient per-serving macros × quantity) ÷ yield servings**; rejects a non-positive yield / no ingredients. A
  **Recipe IS a Food** (`source='recipe'`, owned by the user) — so it is loggable/searchable/totalled **exactly like any
  Food, with zero diary-side changes**. Two tables (`recipes` 1:1 with the backing Food via `food_id` UNIQUE + `yield_servings`
  + `user_id`; `recipe_ingredients` = ingredient `food_id` + `quantity` + `position`). **Documented choice: compute-on-write**
  — the computed macros are stored on the backing Food at create/edit time, so the hot read path stays a plain Food read;
  "stays correct if an ingredient is edited" is honoured by `recompute_recipes_using_food` (a **bounded fan-out** that
  recomputes every Recipe using an edited ingredient Food) rather than pushing a join+sum into every Food read. Ingredient
  Foods are visibility-checked (a foreign private Food → 404). `services/recipe_query.py` is the DB glue;
  `load_recipe_with_ingredients` reloads with `selectinload`+`populate_existing` so a just-created Recipe's freshly-appended
  ingredient rows have their `food` materialised for the response (avoids a `MissingGreenlet` on lazy access).
- **API** (extends `/api/nutrition`): `GET /barcode/{code}` (resolve cache-first → `FoodRead`; 422 junk, 404 not-found),
  `POST/PATCH/DELETE /foods` (custom-Food CRUD; edit fans out to Recipes; delete 409 if in use), `GET /recipes`,
  `POST /recipes`, `GET/PATCH/DELETE /recipes/{id}` (Recipe CRUD; per-user scoped). All `get_current_user`-scoped.
- **Export** (#19): added `recipes` to the optional-table reflection set — it carries `user_id` so it round-trips per-user
  cleanly (`recipe_ingredients` has no `user_id`, so it is intentionally NOT reflected — it belongs to a Recipe, not a user).
- **Frontend** — `AddEntrySheet.svelte` gained a Scan / Custom / Recipe switcher on the search step, all converging on the
  existing quantity+Meal "detail" step: `BarcodeScanner.svelte` (scan → resolve → log; fallback to search), `CustomFoodForm.svelte`
  (per-serving macro form), `RecipeBuilder.svelte` (search+add ingredients with quantities + yield + a live computed
  per-serving preview). A recipe-backed Food shows a "Recipe" badge in search. YAGNI: no meal templates, no nutrition AI.

## Ingestion Pipeline

The XML parser uses a **producer-consumer** pattern:
1. **Producer** (`xml_parser.py`): lxml `iterparse` with `recover=True`, batches of 25K records
2. **Queue**: `asyncio.Queue(maxsize=8)` with backpressure
3. **Consumers** (3x): Concurrent table inserts via `asyncio.gather`
4. **Bulk insert**: PostgreSQL `COPY` via temp table staging for health_records, category_records,
   activity_summaries, and workout_route_points. Workouts use parameterized INSERT (JSONB column).

Key details:
- Producer yields to event loop every 2000 records (`await asyncio.sleep(0)`)
- Parser runs in a background thread via `BackgroundTasks` + `asyncio.run()`
- Temp tables use `DROP TABLE IF EXISTS` + `CREATE TEMP TABLE` (NOT `ON COMMIT DROP` —
  raw asyncpg connections from SQLAlchemy auto-commit each statement)
- ZIP extraction runs off event loop via `asyncio.to_thread()`

## Dashboard Query Optimizations

- **Sums** (steps, energy): Single query with conditional `CASE/SUM`
- **Latest values** (HR, HRV, SpO2, sleep): Single query with `DISTINCT ON (metric_type)`
- **Metrics endpoint**: Stats computed from fetched data (no second scan)
- **Raw metrics**: Capped at 10K rows (configurable via `limit` param, max 100K)
- **Workout listings**: JSONB `metadata_` column deferred via `defer()`

## Frontend Structure

```
frontend/src/
├── lib/
│   ├── api.ts          # API client (fetch with credentials: include)
│   ├── types.ts        # TypeScript interfaces
│   ├── pr.ts           # PR detection + e1RM (TS mirror of backend services/{e1rm,pr}.py)
│   ├── fitbod.ts       # Pure looksLikeFitbodCsv header-sniff (reject wrong file pre-upload, vitest) (#9)
│   ├── nutrition.ts    # Pure macro view-logic: scale/format/split + history→chart series (vitest) (#21)
│   ├── barcode.ts      # Pure scan logic: normalize/validate barcode, engine pick, ScanDebouncer (vitest) (#22)
│   ├── sync/           # Offline-first sync (ADR-0005, #6): queue.ts (PURE FIFO op
│   │                   #   log + replay/collapse/reconcile, vitest), store.ts (IndexedDB
│   │                   #   via idb), engine.ts (drain on reconnect/load), *.svelte.ts
│   │                   #   (runes data layer + sync-state the pages bind to)
│   ├── stores/
│   │   ├── auth.svelte.ts      # Current user from /api/auth/me (forward-auth)
│   │   └── date-range.svelte.ts # Global date range + resolution
│   ├── components/
│   │   ├── charts/     # BarChart, TimeSeriesChart, Sparkline, ActivityRings, etc.
│   │   ├── dashboard/  # MetricCard, TodaySummary, SleepSummary, RecentWorkouts
│   │   ├── import/     # XmlUpload, ImportStatus, FitbodImport (CSV → preview → resolve → commit, #9)
│   │   ├── sessions/   # ExercisePicker, SetTypeChip, EffortChips (RIR), PRCelebration, SyncIndicator
│   │   ├── nutrition/  # AddEntrySheet (search/scan/custom/recipe → quantity + Meal → save/edit, #21/#22),
│   │   │               #   BarcodeScanner (native BarcodeDetector + @zxing fallback), CustomFoodForm, RecipeBuilder (#22)
│   │   └── layout/     # Header, Sidebar, DateRangePicker, BottomNav
│   └── utils/          # constants.ts, format.ts
└── routes/
    ├── +page.svelte           # Dashboard (home)
    ├── sessions/+page.svelte       # Train: Sessions list + start/resume (primary mobile tab)
    ├── sessions/[id]/+page.svelte  # Live logging: groups by exercise, steppers, set-type/Effort chips, reorder, finish
    ├── workouts/+page.svelte  # Workout list
    ├── workouts/[id]/+page.svelte  # Workout detail + map
    ├── exercises/+page.svelte       # Exercise library browse (search + muscle/equipment filters)
    ├── exercises/[id]/+page.svelte  # Exercise detail (images, muscles, instructions, demo link)
    ├── exercises/new/+page.svelte   # Create custom exercise form
    ├── metrics/+page.svelte   # Available metrics
    ├── metrics/[type]/+page.svelte  # Metric drill-down
    ├── nutrition/+page.svelte       # Food diary day view (four Meals, entries, daily total) (#21)
    ├── nutrition/history/+page.svelte  # Calories/macros over time (reuses BarChart) (#21)
    ├── settings/+page.svelte  # Settings, import management
    ├── body/+page.svelte      # Body metrics
    ├── sleep/+page.svelte     # Sleep view
    └── trends/+page.svelte    # Trends
```

The mobile bottom-nav (`lib/nav.ts`) pins **Train** (`/sessions`) as a primary tab — the core
logging action — alongside Dashboard, Workouts, Exercises (Metrics moved to the "More" sheet).

## Auth

Authentik forward-auth identity (ADR-0003). No in-app login; no sessions.
- The ingress runs `auth="required"`; every request arrives with a trusted
  `X-authentik-email` header (forward-auth overwrites any client-supplied
  `X-authentik-*`, so it cannot be spoofed behind the ingress).
- `get_current_user` reads that header (fallback `DEV_AUTH_EMAIL` for local dev),
  then gets-or-creates the `User` by email and returns it.
- Local dev (docker-compose, no Authentik): set `DEV_AUTH_EMAIL` to act as that
  identity. A request with neither header nor override → 401.
- All API endpoints except `/api/health` require auth; `/api/auth/me` returns
  the resolved user.

## Migrations

Alembic migrations in `backend/alembic/versions/`. Current head: `d4e5f6a7b8c9`
(`add recipes + recipe ingredients`, #22; chains off `c3d4e5f6a7b8` nutrition).

Run: `alembic upgrade head` (runs automatically in `entrypoint.sh`)

After migrations, `entrypoint.sh` runs three idempotent seeds (best-effort — a seed failure
does not block boot), each runnable manually via the same `python -m` command:
`app.services.seed_exercises` (the shared Exercise library from the vendored free-exercise-db
dataset), `app.services.seed_principles` (the cited Principles KB, ADR-0004), and
`app.services.seed_foods` (the generic whole-foods Food catalog, #21).

## CI/CD

Woodpecker CI (`.woodpecker/default.yml`):
1. `plugins/docker` builds and pushes to `viktorbarzin/health:latest` + `:${CI_PIPELINE_NUMBER}`
2. `curl` patches the k8s deployment annotation at `https://kubernetes:6443`

## Environment Variables

```
DB_PASSWORD=...        # PostgreSQL password
DEV_AUTH_EMAIL=...     # Local dev only: identity used when no X-authentik-email
                       # header is present. MUST be unset in production.
ADJUST_PROVIDER=...    # Conversational-adjust provider (#14): "deterministic"
                       # (DEFAULT — rules-based, no external service) or
                       # "claude-agent" (the in-cluster LLM, proposes-only, gated).
CLAUDE_AGENT_URL=...   # claude-agent-service base URL (default the in-cluster svc);
CLAUDE_AGENT_TOKEN=... #   bearer from Vault secret/claude-agent-service. Read only
                       #   when ADJUST_PROVIDER=claude-agent; on any failure the
                       #   adjust falls back to the deterministic provider.
```

Set in `.env` file, loaded by docker-compose.

## Conventions

- **Backend**: Python 3.12, async everywhere, SQLAlchemy 2.0 style (mapped_column)
- **Frontend**: SvelteKit with Svelte 5 runes (`$state`, `$derived`, `$effect`, `$props`)
- **API**: All routes under `/api/`, JSON responses, forward-auth identity (ADR-0003)
- **DB**: Composite PKs for time-series tables, UUID PKs for entity tables
- **Imports**: Always use `from_attributes=True` in Pydantic model_config for ORM compatibility
