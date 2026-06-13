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
│   └── exercises.py  # /api/exercises — browse/search/detail/create-custom (Exercise library)
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
│   └── seed_exercises.py  # Idempotent Exercise-library seed from vendored free-exercise-db
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

**Exercise library** (the shared movement catalog — CONTEXT.md "Exercise"): `exercises.user_id`
NULL = global/shared (seeded from free-exercise-db), non-NULL = that user's private custom
Exercise; browse = global ∪ own. Two partial unique indexes key the natural key `slug`
separately per namespace (NULLs compare distinct in a plain unique). Muscle mappings are
normalized in `exercise_muscles` with `muscle` a native Postgres enum (17 dataset groups) +
`role` enum (primary/secondary) — a GROUP-BY-able dimension for Recovery/volume analytics, not
free text. Demo-video link = computed YouTube "proper form" search URL (no hosted video).
Images = jsDelivr CDN URLs (no binaries vendored). API: `/api/exercises` (browse with
search/muscle/equipment filters, detail, create-custom, `/muscles` + `/equipment` options).

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
│   ├── stores/
│   │   ├── auth.svelte.ts      # Current user from /api/auth/me (forward-auth)
│   │   └── date-range.svelte.ts # Global date range + resolution
│   ├── components/
│   │   ├── charts/     # BarChart, TimeSeriesChart, Sparkline, ActivityRings, etc.
│   │   ├── dashboard/  # MetricCard, TodaySummary, SleepSummary, RecentWorkouts
│   │   ├── import/     # XmlUpload, ImportStatus
│   │   └── layout/     # Header, Sidebar, DateRangePicker
│   └── utils/          # constants.ts, format.ts
└── routes/
    ├── +page.svelte           # Dashboard (home)
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

Alembic migrations in `backend/alembic/versions/`. Current head: `c9d3e5f7a2b4`.

Run: `alembic upgrade head` (runs automatically in `entrypoint.sh`)

After migrations, `entrypoint.sh` also runs `python -m app.services.seed_exercises` to
idempotently upsert the shared Exercise library from the vendored free-exercise-db dataset
(best-effort — a seed failure does not block boot). Runnable manually with the same command.

## CI/CD

Woodpecker CI (`.woodpecker/default.yml`):
1. `plugins/docker` builds and pushes to `viktorbarzin/health:latest` + `:${CI_PIPELINE_NUMBER}`
2. `curl` patches the k8s deployment annotation at `https://kubernetes:6443`

## Environment Variables

```
DB_PASSWORD=...        # PostgreSQL password
DEV_AUTH_EMAIL=...     # Local dev only: identity used when no X-authentik-email
                       # header is present. MUST be unset in production.
```

Set in `.env` file, loaded by docker-compose.

## Conventions

- **Backend**: Python 3.12, async everywhere, SQLAlchemy 2.0 style (mapped_column)
- **Frontend**: SvelteKit with Svelte 5 runes (`$state`, `$derived`, `$effect`, `$props`)
- **API**: All routes under `/api/`, JSON responses, forward-auth identity (ADR-0003)
- **DB**: Composite PKs for time-series tables, UUID PKs for entity tables
- **Imports**: Always use `from_attributes=True` in Pydantic model_config for ORM compatibility
