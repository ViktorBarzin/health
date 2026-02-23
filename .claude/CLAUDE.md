# Apple Health Dashboard — Project Knowledge

## Overview

Full-stack Apple Health data dashboard: FastAPI backend, SvelteKit frontend, TimescaleDB,
WebAuthn auth. Imports Apple Health XML/ZIP exports and provides interactive visualizations.

## Architecture

```
SvelteKit (:3000) → /api/*  → Backend (FastAPI :8000, internal proxy)
                  → /*      → SvelteKit SSR
```

**Stack:** Python 3.12, FastAPI, SQLAlchemy async + asyncpg, TimescaleDB (PG16), SvelteKit, Docker Compose

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
│   ├── auth.py    # /api/auth — WebAuthn register/login/logout/me
│   ├── dashboard.py  # /api/dashboard — summary endpoint
│   ├── metrics.py    # /api/metrics — available metrics + time-series queries
│   ├── workouts.py   # /api/workouts — list/detail with route points
│   ├── activity.py   # /api/activity — activity rings
│   └── ingestion.py  # /api/import — upload/status/cancel/delete
├── core/
│   ├── auth.py         # Session management (in-memory dict)
│   ├── dependencies.py # get_current_user (session cookie)
│   └── exceptions.py
├── models/        # SQLAlchemy ORM (see DB Models below)
├── schemas/       # Pydantic request/response models
├── services/
│   ├── xml_parser.py  # Producer-consumer XML parsing pipeline
│   └── dedup.py       # Bulk insert with COPY + ON CONFLICT DO NOTHING
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
| `user_credentials` | id (UUID) | UNIQUE(credential_id) |
| `data_sources` | id | UNIQUE(name, bundle_id) |
| `import_batches` | id (UUID) | — |

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
│   ├── webauthn.ts     # WebAuthn helpers
│   ├── stores/
│   │   ├── auth.svelte.ts      # User session state
│   │   └── date-range.svelte.ts # Global date range + resolution
│   ├── components/
│   │   ├── charts/     # BarChart, TimeSeriesChart, Sparkline, ActivityRings, etc.
│   │   ├── dashboard/  # MetricCard, TodaySummary, SleepSummary, RecentWorkouts
│   │   ├── import/     # XmlUpload, ImportStatus
│   │   └── layout/     # Header, Sidebar, DateRangePicker
│   └── utils/          # constants.ts, format.ts
└── routes/
    ├── +page.svelte           # Dashboard (home)
    ├── login/+page.svelte     # WebAuthn login
    ├── register/+page.svelte  # WebAuthn registration
    ├── workouts/+page.svelte  # Workout list
    ├── workouts/[id]/+page.svelte  # Workout detail + map
    ├── metrics/+page.svelte   # Available metrics
    ├── metrics/[type]/+page.svelte  # Metric drill-down
    ├── settings/+page.svelte  # Settings, import management
    ├── body/+page.svelte      # Body metrics
    ├── sleep/+page.svelte     # Sleep view
    └── trends/+page.svelte    # Trends
```

## Auth

WebAuthn passkeys (discoverable credentials). No passwords.
- Sessions: in-memory dict, HTTP-only cookie named `session`, 30-day expiry
- RP ID: `localhost`, Origin: `http://localhost:3000`
- All API endpoints except `/api/health` and `/api/auth/*` require auth

## Migrations

Alembic migrations in `backend/alembic/versions/`. Current head: `e6f0a4b8c3d5`.

Run: `alembic upgrade head` (runs automatically in `entrypoint.sh`)

## CI/CD

Woodpecker CI (`.woodpecker/default.yml`):
1. `plugins/docker` builds and pushes to `viktorbarzin/health:latest` + `:${CI_PIPELINE_NUMBER}`
2. `curl` patches the k8s deployment annotation at `https://kubernetes:6443`

## Environment Variables

```
DB_PASSWORD=...       # PostgreSQL password
SECRET_KEY=...        # Session signing key
```

Set in `.env` file, loaded by docker-compose.

## Conventions

- **Backend**: Python 3.12, async everywhere, SQLAlchemy 2.0 style (mapped_column)
- **Frontend**: SvelteKit with Svelte 5 runes (`$state`, `$derived`, `$effect`, `$props`)
- **API**: All routes under `/api/`, JSON responses, session cookie auth
- **DB**: Composite PKs for time-series tables, UUID PKs for entity tables
- **Imports**: Always use `from_attributes=True` in Pydantic model_config for ORM compatibility
