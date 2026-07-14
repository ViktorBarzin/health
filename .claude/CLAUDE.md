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
│   ├── recommendations.py # /api/recommendations — freestyle + today (autoregulated; ?day_index=/?muscles= overrides) + adjust + shape + explicit WYSIWYG start
│   ├── programs.py   # /api/programs — generate (quiz/preset)/list/active/get/activate/delete (#13)
│   ├── readiness.py  # /api/readiness — daily biometric 0–100 signal (HRV/RHR/sleep vs baseline) (#14)
│   ├── nutrition.py  # /api/nutrition — Food catalog + Diary CRUD + day/history (#21); barcode→OFF, custom Foods, Recipes (#22)
│   ├── connections.py # /api/connections — per-user BYOT integrations: list/connect(paste token)/sync-now/disconnect (Oura, ADR-0006)
│   └── push.py       # /api/push — Web Push (ADR-0010): config/subscriptions + rest-timer schedule/cancel
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
│   ├── rollup.py      # Daily metric rollups (ADR-0009): backfill (gated) + targeted post-ingest recompute + day/week/month read helper
│   ├── seed_exercises.py  # Idempotent Exercise-library seed from vendored free-exercise-db
│   ├── effort.py      # Pure Effort RIR↔RPE mapping (one-tap chip ↔ stored RPE-equivalent)
│   ├── volume.py      # Pure volume helper (encodes the non-normal-set exclusion)
│   ├── e1rm.py        # Pure estimated-1RM core (1-rep-anchored Epley + optional RIR adjust)
│   ├── swap.py        # Pure Swap ranking core: ranked same-primary-muscle equivalents (fitbod-exit ①)
│   ├── swap_query.py  # Swap DB glue: pool + history + Recovery → rank_alternatives (alternatives endpoint)
│   ├── exclusion.py   # Exclusion filter: one shared not-excluded clause every generator path applies
│   ├── duration.py    # Pure duration shaper: fit today into N minutes via the bounded adjust levers (fitbod-exit ③)
│   ├── push.py        # Web Push send core: VAPID config (fail-closed) + classified one-shot send (ADR-0010)
│   ├── push_query.py  # Push DB glue: subscriptions upsert, one-pending-per-user timer, SKIP LOCKED delivery
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
│   ├── seed_foods.py  # Idempotent generic whole-foods Food-catalog seed (in-code; upsert by slug) (#21)
│   ├── weight_trend.py # Pure weight-trend smoother: time-aware EMA "true weight" + OLS-slope rate (kg/wk, %BW/wk) (#23)
│   ├── budget.py      # Pure Budget: adaptive TDEE from energy balance + goal-driven calorie/macro target (#23)
│   ├── budget_query.py # Budget glue: BodyMass→trend, Diary intake, protein Principle, active-Program goal → cores (#23)
│   ├── crypto.py      # Fernet credential cipher (encrypt-at-rest for Connection tokens; MultiFernet rotation) (connections)
│   ├── connection_query.py # Connection CRUD (encrypt) + sync_connection (decrypt→pull→dedup-ingest, idempotent) + sync_all_active (connections)
│   ├── connection_sync_cli.py # `python -m` scheduled-pull entrypoint a K8s CronJob invokes (connections)
│   └── connectors/    # SourceConnector ABC + registry + provider impls (connections, ADR-0006):
│       ├── base.py    #   ABC: pull(credential, since)→NormalizedRecord[]; ConnectorError/ConnectorAuthError
│       ├── oura.py    #   Oura API v2 (BYOT/PAT): sleep docs → HRV/RHR/SleepAnalysis, injectable httpx (mock in tests)
│       └── __init__.py #   _REGISTRY (one entry per provider) + get_connector / available_providers
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
| `metric_daily` | (user_id, metric_type, day) | — (PK serves the read + upsert) |
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
| `connections` | id (UUID) | UNIQUE(user_id, provider) |
| `user_exercise_prefs` | id | UNIQUE(user_id, exercise_id) — per-user rest default + `excluded` (Exclusion) |
| `push_subscriptions` | id (UUID) | UNIQUE(endpoint), (user_id) |
| `push_timers` | user_id (one pending per user) | (fire_at) |
| `recipe_ingredients` | id (UUID) | (recipe_id), (food_id) |
| `prescriptions` | id (UUID) | UNIQUE(session_id), (user_id) — immutable started-slots snapshot (ADR-0011) |
| `program_revisions` | id (UUID) | (program_id, version) — Block Review receipts |
| `analysis_reports` | id (UUID) | UNIQUE(program_id, week) — qwen coach's notes + digest |
| `proposals` | id (UUID) | (user_id, status) — LLM suggestions awaiting approval |

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

**Unified Goal → dynamic Budget + weight-trend smoother** (the self-calibrating daily target — CONTEXT.md "Budget"/"Goal";
ADR-0004; #23). Two **pure, tested** cores behind a query layer (no DB/clock/IO; `now` + data injected — the
`readiness`/`recovery` shape):
- **`services/weight_trend.py`** — de-noises a noisy daily BodyMass series into a **"true weight"** + a **rate of change**.
  True weight = a **time-aware EMA** (half-life `_HALFLIFE_DAYS` ≈ 10 days): each step decays the running estimate by
  `0.5**(Δdays/halflife)` then blends the new reading, so a *gap* between weigh-ins decays history by **elapsed time, not
  sample count** — irregular/sparse sampling just works. Rate = the **OLS slope of the *raw* in-window samples** (kg/day →
  kg/week, plus %BW/week); least-squares is itself the noise-robust trend estimator, and regressing the *raw* (not the EMA)
  avoids the EMA's lag flattening the slope. 28-day window (matches Readiness). Empty/only-stale → `insufficient_data`; a
  single in-window reading → a weight but **no rate** (one point ≠ a trend) — never a fabricated number. Fully unit-tested
  (smooths noise; correct rate sign/magnitude on synthetic trends incl. with noise; irregular/sparse/empty/unordered).
- **`services/budget.py`** — the daily calorie/macro **Budget**. **Adaptive TDEE from energy balance**, NOT a static
  formula: `TDEE = avg_logged_intake − rate_kg_per_week·KCAL_PER_KG/7` (a surplus/deficit manifests as weight change at
  `KCAL_PER_KG`=7700 kcal/kg). Target = `TDEE + goal_delta`, the delta sized to drive the **Goal's** intended *rate*
  (`_GOAL_TARGET_RATE_PCT`, %BW/wk: bulk +0.375 / cut −0.75 / maintain 0 / strength +0.15). **Self-calibrating**: each
  recompute re-measures TDEE from the latest trend, so the target moves to hold the goal rate as the body responds (a bulk
  gaining too fast lands a lower target; a stalled cut tightens). Protein from the injected **`protein-intake` Principle**
  g/kg range (Morton 2018; goal-placed — cut/strength to the top), fat = 25% of kcal, carbs the remainder (floored ≥0).
  **Honesty rule** (mirrors Readiness `insufficient_data` / the OFF skip-don't-fabricate): can't measure TDEE (no intake
  *or* no weight rate) → a **labelled** bodyweight estimate (`_KCAL_PER_KG_MAINTENANCE`≈31 kcal/kg, `method='estimated'`);
  **no bodyweight at all** → `insufficient_data`, null numbers — never a confidently-wrong target. All constants documented
  at the top of each module.
- **Goal lives in ONE place** — `services/budget_query.py` reads the user's **active Program's `goal`** (`active_program`),
  default `maintain` when none; no second goal concept (ADR-0004 unified Goal). The query layer reduces BodyMass (kg-
  normalised; lb→kg) → trend, Diary Entries → avg intake via the **pure `nutrition.daily_totals`** (reused, never
  re-derived), the protein Principle, and the goal, then runs the cores. **Target rates + bodyweight basis are documented
  constants keyed by goal** in `budget.py` — not a new table (YAGNI).
- **No new DB tables / no migration** (Alembic head unchanged at `d4e5f6a7b8c9`) — read-only over `health_records` /
  `diary_entries` / `principles` / `programs`. API **`GET /api/nutrition/budget`** (the Goal-driven target + the weight
  trend, per-user scoped). Frontend **`lib/budget.ts`** (PURE: `remainingMacros` target−logged floored, `goalLabel`,
  `formatRate`, `trendSummary`; vitest `budget.test.ts`) + **`components/nutrition/BudgetCard.svelte`** on `/nutrition`
  (today only): calorie target vs logged → remaining + progress bar, per-macro remaining bars, the current weight trend/rate,
  and an "estimated" footnote when the fallback is active. **No forecast UI** (ADR-0004 cut) — current Budget + current
  trend only, no "you'll hit X by date Y" projection.

**Per-user Connections — BYOT integrations** (the opt-in data-source framework — CONTEXT.md "Connector"/"Source"/"Import"/
"Metric"; ADR-0006, the **BYOT variant**: each user pastes their OWN token rather than an infra-gated push receiver or a
single-app OAuth). The framework + one reference provider (Oura), structured so more providers slot in:
- **`connections` table / `models/connection.py`** — one row per `(user_id, provider)` (UNIQUE). `provider` + `status`
  (active/error/disabled) are native enums (extensible by a label). The user's credential lives ONLY in
  `encrypted_credential` (a `bytea` of Fernet ciphertext) — **never plaintext, never logged, never returned** (there is no
  plaintext/masked/last-4 column at all, so a leak is structurally impossible from a row read). Operational metadata:
  `last_sync_at`, `last_error` (credential-free), timestamps.
- **Encryption at rest** (`services/crypto.py`, security-critical) — **Fernet** (authenticated AES-128-CBC+HMAC, the
  `cryptography` recipes layer). `CredentialCipher.from_settings()` reads `CONNECTION_ENCRYPTION_KEY` (URL-safe base64
  32-byte key; comma-separated = **MultiFernet rotation**, new key encrypts / all keys decrypt). **Fail closed**: no key ⇒
  the API 503s, we never store a token unprotected. Encrypt before insert; decrypt only in-memory at pull time. Tested:
  round-trip, ciphertext≠plaintext (the secret never appears in the bytes), wrong-key/tamper → `InvalidToken`, rotation.
- **`SourceConnector` ABC** (`services/connectors/base.py`) — `pull(credential, since) -> NormalizedRecord[]`; the connector
  is DB-free pure-mapping (HTTP in, normalized records out) so it's trivially mockable. A `NormalizedRecord` targets either
  `health_records` (`kind=metric`) or `category_records` (`kind=category`) via one discriminator. `ConnectorAuthError`
  (invalid/expired token) vs `ConnectorError` (transient). **Registry** (`connectors/__init__.py` `_REGISTRY`): adding a
  provider is one enum label + one subclass + one registry entry — nothing else changes.
- **Oura reference provider** (`services/connectors/oura.py`, BYOT/PAT — no app registration, no OAuth, no infra host) —
  pulls **Oura API v2** `GET /v2/usercollection/sleep` (one call carries all three signals) with `Authorization: Bearer
  <PAT>`, maps per-night: `average_hrv`→`HeartRateVariabilitySDNN` (ms), `lowest_heart_rate`→`RestingHeartRate` (count/min),
  `total_sleep_duration`→a `SleepAnalysis` asleep interval ending at `bedtime_end` (raw `HKCategoryValueSleepAnalysisAsleep`
  value + cleaned `"Asleep"` label, mirroring the XML importer) — so **Readiness (#14) consumes Oura data identically to
  Apple data**. Honesty rule: a night missing a metric contributes only what it has (never a fake 0). Injectable httpx
  transport ⇒ tests MOCK Oura (no network, the OFF pattern). 401/403 → `ConnectorAuthError`; 5xx → `ConnectorError`.
- **Sync** (`services/connection_query.py`) — `sync_connection` decrypts the credential **in memory**, calls
  `connector.pull(since=last_sync_at)`, lands the records via the **existing idempotent dedup** (`bulk_insert_health_records`
  / `bulk_insert_category_records` — ON CONFLICT DO NOTHING on each table's natural key, so a re-pull adds nothing),
  registers an Oura **`DataSource`** + an **`ImportBatch`** audit row, and updates status/`last_sync_at`/`last_error`. A
  `ConnectorError` is caught → `status=error` with a clear, **token-free** message (never crashes). `sync_all_active` syncs
  every active Connection independently (commits per-connection; one failure can't abort the rest) — the **scheduled-puller**
  kind, invoked by `python -m app.services.connection_sync_cli` (the **K8s CronJob** manifest is infra/HITL — documented stub
  in `docs/connectors/oura-cronjob.md`; the command itself works + is tested).
- **API** (`api/connections.py`, all `get_current_user`-scoped) — `GET /api/connections` (catalog + this user's state, token
  NEVER returned), `POST /api/connections` (connect: paste token; 503 if no key), `POST /api/connections/{provider}/sync`
  (sync now; an invalid token reports `status=error` at HTTP 200, not a 500), `DELETE /api/connections/{provider}`
  (disconnect). Per-user scoped: a user can't read/sync/disconnect another's Connection (404). The connect token is
  **write-only** (a request field on `ConnectionConnect` only — no read schema has a token field).
- **Frontend** — `lib/connections.ts` (PURE view-logic: `statusLabel`/tone, `lastSyncSummary` relative time, `canSync`/
  `canSubmitToken` gates; vitest `connections.test.ts`) + `components/settings/Connections.svelte` (mobile-first: list
  providers → "Connect Oura" reveals a **password** PAT field + a "get your token" link to cloud.ouraring.com → save & sync →
  status badge + last-synced + Sync now + Update token + Disconnect). The token field is write-only and cleared from memory
  immediately after submit; it is never rendered back. Wired into the **settings page** as a "Connections" section.
- **Extending (documented, NOT built — YAGNI)**: **Whoop** (OAuth-gated, deferred until an app is registered) = a new
  `ConnectionProvider.whoop` label + a `WhoopConnector` whose stored credential is the OAuth access/refresh token the
  connector refreshes (the connect flow becomes a redirect instead of a paste; `token_based=False`). **Garmin** (no official
  individual API — the "allowed-but-clearly-flagged" unofficial path) = a `GarminConnector` over python-garminconnect whose
  credential is the username/password it logs in with, labelled unofficial. Both reuse the SAME encrypted-credential storage,
  idempotent ingest, Source/ImportBatch bookkeeping, sync endpoint, scheduler, and UI — only the connector class is new.

**Fitbod-exit gym toolkit** (plan docs/plans/2026-07-13-fitbod-exit-gym-pwa.md; CONTEXT.md
"Swap"/"Exclusion"; ADR-0010). Four in-gym affordances over the existing engine:
- **Swap** (①): every Recommendation surface + the live Session offer ranked equivalents for one
  slot — pure `services/swap.py` (shared-primary-muscle > has-history > freshness > stable id;
  equipment hard filter; prescription from the alternative's OWN Progression; slot set count stays)
  behind `GET /api/exercises/{id}/alternatives` (`?exclude=` = today's other ids). The client
  PREFETCHES per visible Exercise into IndexedDB (`alts:{id}`), so the SwapSheet opens through a
  signal drop; a mid-Session swap = delete+add+reorder op-queue verbs (pure `lib/swap.ts` plan) —
  fully offline. **Exclusion**: "don't suggest again" (two-tap) sets `excluded` on the existing
  `user_exercise_prefs` row; ONE shared SQL clause (`services/exclusion.py`) filters every
  generator path (freestyle candidates, Program slots, alternatives pool) exactly like Gym
  Profile equipment; managed under Settings → Excluded exercises. Explicit only — never inferred
  (ADR-0002). A swapped/shaped/overridden preview starts via **`POST /api/recommendations/start`**
  (WYSIWYG: instantiate exactly the displayed slots, visibility-checked) instead of a regenerate.
- **Rest-timer Web Push** (②, ADR-0010): logging a Set online also schedules a server push at the
  countdown's end (`POST/DELETE /api/push/rest-timer`, ONE pending per user, replaced on
  reschedule); skip/adjust/early-log/visible-completion cancel it, so the push only lands when the
  page was frozen (= phone locked, exactly the case that needs it; iOS mirrors it to a paired
  Watch). Delivery: `push_timers` rows claimed `FOR UPDATE SKIP LOCKED` + deleted in the sending
  transaction by a 1 s asyncio poller in every replica (`main.py` lifespan) → at-most-once, no
  retries (a late rest cue is worthless). Subscriptions upsert by endpoint; 404/410 prunes.
  VAPID identity fails closed (`PUSH_VAPID_*`); `GET /api/push/config` tells the client to hide
  the toggle. SW stays `generateSW` — `static/push-sw.js` rides in via workbox `importScripts`.
  Settings → Notifications owns the iOS user-gesture permission flow (installed PWA only).
- **Duration shaper** (③): `POST /api/recommendations/shape {minutes}` — pure `services/duration.py`
  picks the (exercise count, volume scale ≤ 1) using the most of the budget (setup 90 s + work
  40 s/set + rest between sets), applied via the EXISTING bounded adjust pipeline; honest
  "runs over" note when nothing fits. Today gets 30/45/60-min chips.
- **Day-type override** (④): `GET /api/recommendations/today?day_index=` previews any active-Program
  day through the same autoregulation (pointer never moves — reflow self-heals); `?muscles=` is the
  freestyle muscle-group focus (validated against the typed dimension). Today gets a "Train a
  different day?" picker (Program day pills / Push-Pull-Legs-Core groups).

**Adaptive programming — the Block Review loop** (ADR-0011; plan
docs/plans/2026-07-14-adaptive-programming.md; CONTEXT.md "Prescription"/"Adherence"/"Block
Review"/"Proposal"). The third nested loop (above per-set Progression, per-day autoregulation):
- Every start path snapshots a **Prescription** (`instantiate_session` writes `prescriptions`);
  pure `services/adherence.py` measures performed-vs-planned (hard failure = rep shortfall at
  RIR 0 vs soft with reserve; normal sets only; no Prescription ⇒ None never fake 100%).
- Pure `services/block_review.py` = the damped rules (2 complete weeks required; volume ±1–2
  within the Principle band; rotation after 3 consecutive failed sessions via the Swap ranking
  pinned into `day.slots[i]["exercise_id"]` — honored by `program_recommendation`; per-lever
  weekly cooldowns; no flip-flop). `services/review_query.py` applies as versioned
  `program_revisions` receipts (future weeks only), **evaluate-on-read** (Today preview +
  Session finish; 6h `reviewed_at` gate + new-finished-Session check), and at block end
  auto-generates the successor Program (`parent_program_id` chain; achieved volume = new week-1
  start; days/week steps down when block day-completion <70%) — a Program never dead-ends.
- **M5 qwen layer** (`services/analysis.py`, `/api/analysis`): deterministic weekly digest →
  llama-swap qwen3-8b → stored coach's-notes narrative (`analysis_reports`, one per Program
  week) + volume `proposals`; approval re-validates against the CURRENT Program, clamps into
  the band, lands as a `trigger=proposal` revision; a 30-min self-gating poller (`main.py`)
  runs the weekly cadence. LLM down ⇒ numbers still adapt (ADR-0002 posture).
- Surfaces: program page (adherence strip, adaptations timeline, coach's notes + Approve/
  Reject, Analyze now), Today banner for <48h revisions, Progress body-comp-vs-volume overlay
  (`/api/analytics/volume-series` + pure `lib/bodycomp.ts`). Research pipeline is PROCESS not
  code: docs/runbooks/research-pipeline.md (gap-driven, citations verified, human-reviewed).

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

## Daily metric rollups (ADR-0009)

The dashboard/metrics read path used to aggregate raw `health_records` on every wide-window
load — a `GROUP BY date_trunc('day', time)` over ~1.05M HeartRate rows spills the sort to disk
(~1.6 s), several per load. Fix: a **`metric_daily` rollup table** (one row per
`(user_id, metric_type, day)` with `count`/`sum`/`min`/`max`/`unit`; avg is **derived**
`sum/count`, never stored) and the read path reads that. A 1M-row scan becomes a ≤~1,900-row
read. All in `services/rollup.py` (the clean, unit-tested home for the recompute + read logic):

- **Read path** (`fetch_rollup_series`, wired into `api/metrics.py` `_fetch_health_metric` and
  the `api/dashboard.py` summary SUM) serves **day/week/month** from `metric_daily`. Week/month
  **re-bucket the daily rows** with the **same** `date_trunc` the raw path used
  (`date_trunc(interval, day::timestamptz)`, UTC session) so rollup answers **equal** the old
  raw-aggregation answers (the cardinal property, pinned by `test_rollup*`; avg agrees to float
  tolerance — Σ-of-day-sums regroups double addition, ~1e-4 at the 4dp boundary). Sum-vs-avg
  reuses the endpoints' existing `_CUMULATIVE_METRICS`/`_SUM_METRICS` split: cumulative → Σsum,
  else Σsum/Σcount. **`raw` resolution still reads `health_records`** directly (capped). The
  summary's **latest-value** (`DISTINCT ON`) + **sleep** parts stay on the raw tables (already fast).
  The **available-metrics list** (`GET /api/metrics/available` → `_list_health_metrics`) also reads
  the rollup (`fetch_available_health_metrics`): Σ`count` (exact) + `max(day)` + a representative
  `unit`, replacing an 8 s `GROUP BY metric_type` over 6.6M raw rows (on the dashboard first-load
  critical path — #51 clamps the default window from its `latest_time`). **`latest_time` is now
  day-granular** for health metrics (`max(day)` at midnight UTC, not the reading instant) — all its
  consumers (display + the day-granular default-window clamp) only need day precision. The
  **category_records portion stays query-time** (ADR-0009: ~45 ms even at a generous 200K rows;
  it never showed up as a bottleneck).
- **Backfill / rebuild** (`backfill_all`, `python -m app.services.rollup`, run from
  `entrypoint.sh`) is one `GROUP BY user_id, metric_type, date_trunc('day', time)`. **Gated**: it
  skips immediately when `metric_daily` is already populated (a `LIMIT 1` probe), so a normal pod
  restart does NOT re-scan the ~6.6M-row table — only the first deploy pays the GROUP BY.
  `--rebuild` (or `ROLLUP_REBUILD=1`) TRUNCATEs + rebuilds for recovery. Derived data: a rebuild
  is always the recovery path.
- **Kept fresh on ingest** by a **targeted** post-batch recompute (`recompute_for_rows` →
  `recompute_buckets`): after a batch writes `health_records`, only the distinct
  `(user, metric, day)` keys that batch touched are re-derived (delete-then-reinsert per key, so
  idempotent + self-healing — a bucket whose raw rows all vanished is removed). Wired into the
  **Apple Health XML pipeline** (`xml_parser._flush_batch`, isolated session, never breaks the
  import) and the **Connector sync** (`connection_query.sync_connection`, same transaction,
  idempotent like the dedup). **Fitbod import writes `training_sets`, not `health_records`, so it's
  out of scope.** Only `health_records` is rolled up — `category_records` (sleep) stay query-time.

## Observability (perf-telemetry)

Lightweight, structured backend telemetry to stdout (scraped by the cluster's Loki — no HTTP log
shipper, stdlib `logging` only), all in `core/observability.py`:
- **Request timing** — `RequestTimingMiddleware` (a `BaseHTTPMiddleware`, added in `main.py` just
  inside CORS) logs one **logfmt** line per request on the `app.request` logger
  (`method=… path=… route=… status=… dur_ms=… user=…`), where `route` is the matched route
  template (falls back to the raw path on a 404) and `user` mirrors `_identity_email` (the
  `X-authentik-email` header or `DEV_AUTH_EMAIL`, **`-` when absent — no DB lookup, never raises**).
  It also sets `Server-Timing: app;dur=<ms>` + `X-Process-Time-Ms` response headers so client
  devtools see backend time. Logging never breaks a request (all emission is wrapped).
- **Slow-query logging** — `register_slow_query_logging(engine)` attaches `before/after_cursor_execute`
  events to the async engine's **`engine.sync_engine`** (a start time stashed on `conn.info`); any
  statement over `SLOW_QUERY_MS` (default 200) is logged once on `app.slow_query` (warning) with the
  elapsed ms + the **truncated** statement (bound params omitted). Idempotent (guarded by a marker).
- **Config** — `configure_logging()` (idempotent: one stdout handler on each named logger,
  `propagate=False` so uvicorn's root handler can't re-emit) at `LOG_LEVEL` (default INFO);
  **uvicorn's own loggers are left untouched**. Both `configure_logging` + the slow-query listener
  run at `main.py` import time. Knobs: `LOG_LEVEL`, `SLOW_QUERY_MS`. (YAGNI: no Prometheus/tracing.)

## Dashboard fast + progressive load (perf-telemetry, #51)

The frontend half of the slow-load fix (the backend half is the daily rollups above). The dashboard
"became unresponsive until all data loaded" — three problems, all fixed in `routes/+page.svelte` +
two pure helpers in `lib/dashboard.ts` (vitest `dashboard.test.ts`):
- **Parallel, not serial** — the page fired **6 requests in 3 SERIAL `Promise.allSettled` pairs**
  (3 round-trips). Now it fires **all 6 concurrently in one batch**, so total latency ≈ the slowest
  single request. The `loadVersion` stale-response race guard is kept (each request's `.then/.finally`
  is version-gated via a `fresh()` check, so a fast range change can't render stale data).
- **Progressive render** — the single global `loading` gate **blanked the whole dashboard** until the
  slowest request returned. Replaced with **per-source loading flags** (summary / rings / steps /
  energy / hr / exercise): the page is interactive immediately (skeletons) and **each card fills in
  independently** as its own request resolves. The error banner shows **only when every request
  failed** (a card that loaded stands on its own).
- **Downsample / cap rendered points** — `lib/dashboard.ts` `downsample` is **Largest-Triangle-
  Three-Buckets** (preserves first/last + peaks/troughs; input ≤ N → returned unchanged by reference;
  empty → empty; threshold < 2 → the two endpoints), with a `downsampleSeries` wrapper for the
  `{time,value}` chart shape. Applied **defensively inside the chart components themselves**
  (`Sparkline`, `TimeSeriesChart`, `BarChart`) at `DEFAULT_MAX_POINTS` (365 ≈ one-per-day for a year),
  so every caller is protected and a wide `raw`/all-time window can't flood Chart.js + freeze the main
  thread. With day-resolution rollups this is usually a no-op.
- **Default window clamps to the user's latest data** — the date-range default was the trailing 30
  days **ending today**, which is **empty** for a user whose data ended in the past → a blank
  dashboard. On first load the dashboard fetches `GET /api/metrics/available`, takes the **max
  `latest_time`** across metrics, and opens on the **trailing 90 days ending at that instant** via
  `lib/dashboard.ts` `computeDefaultWindow` (midnight-normalised bounds, matching the store's
  `startISO`/`endISO`; **no data anywhere → the prior last-30-days-ending-today fallback**). The store
  (`stores/date-range.svelte.ts`) gained `applyDefaultWindow(metrics)` + a `defaultApplied` flag so it
  applies **once** and a manual preset/range choice (which sets `defaultApplied`) is never clobbered.
  The first data load is gated on this resolution so no wasted fetch fires over the empty default.

## Frontend Structure

```
frontend/src/
├── lib/
│   ├── api.ts          # API client (fetch with credentials: include)
│   ├── types.ts        # TypeScript interfaces
│   ├── pr.ts           # PR detection + e1RM (TS mirror of backend services/{e1rm,pr}.py)
│   ├── swap.ts         # Pure Swap plan: incoming Sets + swapped order (op-queue verbs, offline-capable; vitest)
│   ├── push.ts         # Pure Web Push helpers: applicationServerKey decode, support detect (vitest)
│   ├── push-client.ts  # Push IO glue: subscribe/unsubscribe + best-effort rest-timer schedule/cancel
│   ├── fitbod.ts       # Pure looksLikeFitbodCsv header-sniff (reject wrong file pre-upload, vitest) (#9)
│   ├── nutrition.ts    # Pure macro view-logic: scale/format/split + history→chart series (vitest) (#21)
│   ├── barcode.ts      # Pure scan logic: normalize/validate barcode, engine pick, ScanDebouncer (vitest) (#22)
│   ├── budget.ts       # Pure Budget view-logic: remaining (target−logged), goal label, rate/trend strings (vitest) (#23)
│   ├── dashboard.ts    # Pure dashboard perf helpers: downsample (LTTB, cap rendered points) + computeDefaultWindow (clamp to latest data) (vitest) (#51)
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
│   │   ├── sessions/   # ExercisePicker, SetTypeChip, EffortChips (RIR), PRCelebration, SyncIndicator,
│   │   │               #   SwapSheet (ranked equivalents + exclude, fitbod-exit ①), RestTimer (+ onendsat → push)
│   │   ├── nutrition/  # AddEntrySheet (search/scan/custom/recipe → quantity + Meal → save/edit, #21/#22),
│   │   │               #   BarcodeScanner (native BarcodeDetector + @zxing fallback), CustomFoodForm, RecipeBuilder (#22),
│   │   │               #   BudgetCard (Goal-driven target vs logged → remaining + macro bars + weight trend, #23)
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

Alembic migrations in `backend/alembic/versions/`. Current head: `d0e1f2a3b4c9`
(analysis reports + proposals; chains … → a7b8c9d0e1f2 (excluded flag) →
b8c9d0e1f2a3 (web push) → c9d0e1f2a3b4 (prescriptions + program revisions +
program version/reviewed_at/parent, ADR-0011) → d0e1f2a3b4c9). Revision ids
follow a rolling-hex pattern — check `ls alembic/versions` before minting one.

Run: `alembic upgrade head` (runs automatically in `entrypoint.sh`)

After migrations, `entrypoint.sh` runs three idempotent seeds then the rollup backfill
(best-effort — a failure does not block boot), each runnable manually via the same `python -m`
command: `app.services.seed_exercises` (the shared Exercise library from the vendored
free-exercise-db dataset), `app.services.seed_principles` (the cited Principles KB, ADR-0004),
`app.services.seed_foods` (the generic whole-foods Food catalog, #21), and
`app.services.rollup` (the daily metric-rollup backfill, ADR-0009 — gated to skip when already
populated; `--rebuild` forces a full rebuild).

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
CONNECTION_ENCRYPTION_KEY=...  # Fernet key (URL-safe base64 32-byte) encrypting
                       #   per-user Connection credentials at rest (BYOT, connections).
                       #   Prod: from Vault secret/health-connection-key — the SAME
                       #   value on the app AND the sync CronJob. Comma-separated
                       #   list = key rotation (new,old). UNSET ⇒ Connections
                       #   disabled (API 503) — fail closed, never store plaintext.
ANALYSIS_ENABLED=...   # LLM analysis (ADR-0011 M5): weekly qwen coach's-notes
ANALYSIS_LLM_URL=...   #   poller + /api/analysis. Defaults: enabled, in-cluster
ANALYSIS_LLM_MODEL=... #   llama-swap /v1, model qwen3-8b. Fail-soft: LLM down =>
                       #   prose pauses, the numeric Block Review keeps adapting.
PUSH_VAPID_PRIVATE_KEY=...  # Web Push (ADR-0010): VAPID identity signing the
PUSH_VAPID_PUBLIC_KEY=...   #   rest-timer notifications (the locked-iPhone /
PUSH_VAPID_SUBJECT=...      #   mirrored-Apple-Watch cue). Prod: Vault
                       #   secret/health (push_vapid_*) via the kv ExternalSecret.
                       #   ANY unset ⇒ push disabled (config reports it, writes
                       #   503) — fail closed like CONNECTION_ENCRYPTION_KEY.
LOG_LEVEL=...          # Observability (perf-telemetry): level for the app's own
                       #   loggers (app.request / app.slow_query). Default INFO;
                       #   uvicorn's loggers are left untouched.
SLOW_QUERY_MS=...      # Observability (perf-telemetry): any SQL statement slower
                       #   than this many ms is logged once on app.slow_query with
                       #   its elapsed time + truncated statement. Default 200;
                       #   <=0 logs every statement.
ROLLUP_REBUILD=...     # Daily metric rollups (ADR-0009): set to "1" to force the
                       #   `python -m app.services.rollup` backfill to TRUNCATE +
                       #   fully rebuild metric_daily (recovery). Default unset —
                       #   the backfill skips when the table is already populated
                       #   (a normal restart never re-scans health_records).
```

Set in `.env` file, loaded by docker-compose.

## Conventions

- **Backend**: Python 3.12, async everywhere, SQLAlchemy 2.0 style (mapped_column)
- **Frontend**: SvelteKit with Svelte 5 runes (`$state`, `$derived`, `$effect`, `$props`)
- **API**: All routes under `/api/`, JSON responses, forward-auth identity (ADR-0003)
- **DB**: Composite PKs for time-series tables, UUID PKs for entity tables
- **Imports**: Always use `from_attributes=True` in Pydantic model_config for ORM compatibility
