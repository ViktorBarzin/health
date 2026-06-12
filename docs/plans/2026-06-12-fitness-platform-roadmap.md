# Fitness platform roadmap (grilled with Viktor, 2026-06-12)

Goal: evolve this app from an Apple Health dashboard into the household's multi-user
fitness platform — replacing **Fitbod** (workout generation) and **MyFitnessPal**
(nutrition) — fed by as much personal health data as possible.

Decisions of record: ADR-0001 (extend this app), ADR-0002 (deterministic engine core, LLM
proposes), ADR-0003 (Authentik identity), ADR-0004 (Goal-driven Programs from a cited
Principles KB — added same evening). Vocabulary: `CONTEXT.md`.

## Facts the plan is built on

- Live app at health.viktorbarzin.me; DB `health` on the shared CNPG cluster; 3 users,
  6.6M metric samples, 1,105 workouts — **stale since 2026-02-12** (manual exports died).
- All household data flows through Apple Health: watch (HR/HRV/sleep/workouts/VO2max) and
  smart scale (weight/body comp) both write to HealthKit. Strava is a mirror — no connector.
- Fitbod CSV export is the ONLY source of set-level strength history (Apple Health has
  Fitbod sessions only as opaque workouts).
- Priority order (Viktor): workout generation → health insights → nutrition. Fitbod is
  deleted at the end of M1.

## M1 — Workout generation (the Fitbod exit)

Foundations folded in only where M1 needs them:

1. **Identity swap** (ADR-0003): forward-auth user mapping, delete WebAuthn + in-memory
   sessions, reconcile the 3 user rows to Authentik emails (yahoo→gmail for Anca; merge or
   retire me@viktorbarzin.me after checking what it owns).
2. **Renovation riders**: DATABASE_URL → `pg-cluster-rw.dbaas` (legacy `postgresql` Service
   pins a pod IP), PWA shell (manifest, installable, phone-first gym screens), CLAUDE.md
   corrections.
3. **Catch-up Import**: one fresh export.zip per user through the existing upload path
   closes the Feb→now gap (dedup makes it safe).
4. **Exercise library**: seed global shared table from free-exercise-db (~870 exercises,
   muscle mappings, images); per-user custom Exercises.
5. **Fitbod importer**: CSV → Sessions/Sets (preserve warmup flags), exercise-name mapping
   onto the library with a manual-match UI for stragglers.
6. **Session logging UX**: phone-first logging — weight × reps + optional RPE; Gym Profile
   (equipment) management.
7. **Engine** (ADR-0002): per-muscle Recovery scores from Set history, per-exercise
   Progression targets, equipment-aware generator producing a Recommendation per visit;
   claude-agent-service layer for conversational adjustment (proposes, never decides).
8. **Principles KB** (ADR-0004): versioned exercise-science rules with parameter ranges,
   applicability, evidence grades, and verified peer-reviewed citations — the sole source
   the generators compose from. Authoring = research pass with citation verification.
9. **Program layer** (ADR-0004): guided quiz (goal, days/week, experience, equipment,
   session length) + preset catalog (GZCLP, upper/lower hypertrophy, PPL, 5/3/1-style)
   generating multi-week Programs; full autoregulation (Recovery/Readiness trims, week
   reflow, fatigue-triggered Deload; user edits win); "receipts everywhere" UI — every
   parameter tappable to its Principle and studies.
10. **Workout↔Session auto-linking** by time overlap (watch recording enriches the logged
    Session).

Exit criterion: Viktor starts a Goal-driven Program, trains from it, and deletes Fitbod.

## M2 — Health (continuous data + insights)

1. **One-tap ingest**: per-user API token + bearer ingest route excluded from forward-auth
   (ADR-0003); iOS share-sheet Shortcut so the flow is Health-app-export → Share → done.
   Import remains idempotent; make "only what's missing" fast and report it.
2. **Readiness & insights**: daily Readiness from HRV/resting-HR/sleep trends; correlation
   views (training volume vs sleep, calories vs weight trend) on the existing chart library.
3. Dashboard refresh on the data already ingested (weight incl. scale body-comp, sleep,
   activity).

## M3 — Nutrition (the MyFitnessPal exit)

1. Food diary + macros (four Meals/day), history charts.
2. Barcode scanning in the PWA (camera + JS decoder) → Open Food Facts lookup, cached
   locally on first scan; seeded generic whole-foods table; per-user custom Foods and
   Recipes with computed per-serving macros.
3. Dynamic Budget: calorie/macro targets from Goal (cut/maintain/bulk) + measured energy
   expenditure from watch data. No MFP history import (not an active user).

## Deliberate non-goals

- User-authored workout plans/templates (ADR-0002/ADR-0004 — Programs and visits are
  always generated).
- Strava/Garmin/Withings connectors; Health Auto Export or any third-party sync app.
- Sharing/social features: accounts are fully isolated; only the Exercise library and Food
  catalog are shared. (Revisit on real demand.)
- Staleness nudges, weekly LLM digest, weight forecasting (cut in the extras round).
  Internal weight-trend math for Budget self-calibration is allowed (ADR-0004) — there is
  just no forecast UI.
- TimescaleDB: prod stays plain Postgres on the shared CNPG cluster; partition
  `health_records` by time only if growth ever forces it.

## Open items for implementation sessions

- Recovery model details (muscle-group fatigue decay curves) — research at M1 build time.
- Principles KB content: author the rules and verify every citation against the primary
  literature (deep-research pass); define the preset parameterizations (GZCLP,
  upper/lower, PPL, 5/3/1-style) on top of the generator.
- Fitbod CSV column inventory against a real export from Viktor's account.
- Barcode decoder library choice; generic-foods seed source (USDA FDC vs curated list).
- Whether custom Exercises/Foods are visible to other users or private (default: private).
