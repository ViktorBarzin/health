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
│   ├── ingestion.py  # /api/import — upload/status/cancel/delete
│   ├── exercises.py  # /api/exercises — browse/search/detail/create-custom (Exercise library)
│   ├── sessions.py   # /api/sessions — Session/Set logging CRUD + set add/edit/delete/reorder/finish
│   ├── principles.py # /api/principles — browse/scope-by-(goal,experience)/lookup-by-key (cited KB)
│   ├── recommendations.py # /api/recommendations — freestyle + today (autoregulated) + adjust preview/start
│   ├── programs.py   # /api/programs — generate (quiz/preset)/list/active/get/activate/delete (#13)
│   └── readiness.py  # /api/readiness — daily biometric 0–100 signal (HRV/RHR/sleep vs baseline) (#14)
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
│   └── adjust_agent.py # Gated claude-agent-service adjust provider (proposes-only; falls back) (#14)
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

**Exercise library** (the shared movement catalog — CONTEXT.md "Exercise"): `exercises.user_id`
NULL = global/shared (seeded from free-exercise-db), non-NULL = that user's private custom
Exercise; browse = global ∪ own. Two partial unique indexes key the natural key `slug`
separately per namespace (NULLs compare distinct in a plain unique). Muscle mappings are
normalized in `exercise_muscles` with `muscle` a native Postgres enum (17 dataset groups) +
`role` enum (primary/secondary) — a GROUP-BY-able dimension for Recovery/volume analytics, not
free text. Demo-video link = computed YouTube "proper form" search URL (no hosted video).
Images = jsDelivr CDN URLs (no binaries vendored). API: `/api/exercises` (browse with
search/muscle/equipment filters, detail, create-custom, `/muscles` + `/equipment` options).

**Session/Set logging** (the live gym-logging core — CONTEXT.md "Session"/"Set"; online only,
offline sync is #6). A **Session** is what the user logs live (NOT a `Workout`, which is reserved
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
`/{id}/sets/order` PUT reorder).

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
│   ├── stores/
│   │   ├── auth.svelte.ts      # Current user from /api/auth/me (forward-auth)
│   │   └── date-range.svelte.ts # Global date range + resolution
│   ├── components/
│   │   ├── charts/     # BarChart, TimeSeriesChart, Sparkline, ActivityRings, etc.
│   │   ├── dashboard/  # MetricCard, TodaySummary, SleepSummary, RecentWorkouts
│   │   ├── import/     # XmlUpload, ImportStatus
│   │   ├── sessions/   # ExercisePicker (bottom-sheet), SetTypeChip, EffortChips (RIR), PRCelebration (banner)
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

Alembic migrations in `backend/alembic/versions/`. Current head: `b2c3d4e5f6a7`
(`add goal-driven Programs`).

Run: `alembic upgrade head` (runs automatically in `entrypoint.sh`)

After migrations, `entrypoint.sh` runs two idempotent seeds (best-effort — a seed failure
does not block boot), each runnable manually via the same `python -m` command:
`app.services.seed_exercises` (the shared Exercise library from the vendored free-exercise-db
dataset) and `app.services.seed_principles` (the cited Principles KB, ADR-0004).

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
