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
- Household devices: Viktor on iPhone + Apple Watch + a smart scale, all writing to Apple
  Health (HR/HRV/sleep/workouts/VO2max + weight/body comp). **Anca now wears a Whoop band**
  (she has legacy Apple Health from her old iPhone, already in the DB). Strava is a mirror
  of the watch — not a connector we build.
- Integrations are first-class and extensible, not export.zip-only (reversed 2026-06-13 —
  ADR-0006). Apple Health (push receiver) + Whoop (official API) are the household's two
  Connectors; the framework makes future ones one module each.
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
   muscle mappings, images); per-user custom Exercises; per-Exercise demo-video deep-links
   (no hosted video content).
5. **Fitbod importer**: CSV → Sessions/Sets (preserve warmup flags), exercise-name mapping
   onto the library with a manual-match UI for stragglers.
6. **Session logging UX** (offline-first — ADR-0005): phone-first logging — weight × reps
   + optional Effort (one-tap reps-in-reserve chips 0–4+, last-set nudge, never blocking);
   set-type chips (warmup/drop/failure, excluded from stats by default); supersets with
   auto-advance; rest timer (per-exercise defaults, sound/vibration); plate + warm-up
   calculators from the Gym Profile's plates; screen wake-lock; PR detection with live
   celebration (client-side, works offline); Gym Profile (equipment) management.
   (Rest timer + warmup flags: 2026-06-12 cuts reversed 2026-06-13 on competitive
   evidence — docs/research/2026-06-13-gym-app-competitive-research.md.)
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
11. **Training analytics**: per-muscle weekly volume + Recovery heatmap (SVG body map —
    the one view all three verified competitor apps share), per-exercise e1RM trend
    charts; both are display layers over data the engine already computes.

Exit criterion: Viktor starts a Goal-driven Program, trains from it, and deletes Fitbod.

## M2 — Health (continuous data + insights)

1. **Connector framework** (ADR-0006): `SourceConnector` ABC + per-user opt-in UI +
   per-user credential storage + a K8s CronJob scheduler + webhook receiver. The bearer
   ingest route (ADR-0003) doubles as the documented third-party push API. One idempotent,
   normalizing ingest path for all Connector kinds.
2. **Apple Health Connector**: free iOS Shortcut posting to the ingest receiver (one-tap,
   no payment); Health Auto Export app supported as an optional paid client of the same
   endpoint; export.zip upload stays as backfill. Best-effort/idempotent (HealthKit locked
   off when phone locked). Carries HRV/RHR/sleep for Readiness.
3. **Whoop Connector**: scheduled puller on the official OAuth2 v2 API + webhooks — Anca's
   recovery path (HRV, RHR, sleep stages, recovery score). Build on v2 (v1 webhooks gone).
4. **Full data Export** (ADR-0006): one-tap per-user JSON+CSV archive of all Sessions,
   Sets, Workouts, Metrics, Diary Entries.
5. **Readiness & insights**: daily Readiness from HRV/resting-HR/sleep trends; correlation
   views (training volume vs sleep, calories vs weight trend) on the existing chart library.
6. Dashboard refresh on the data already ingested (weight incl. scale body-comp, sleep,
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
  always generated). Reaffirmed 2026-06-13 after competitive research surfaced Boostcamp's
  12K+ community-program moat — the app builds the plans.
- Strava push (our Sessions → Strava) — rejected 2026-06-13; Strava remains a mirror of
  the watch, not of us.
- Watch companion / HealthKit write-back — structurally impossible for a PWA; mitigated by
  sub-3-tap offline logging + screen wake-lock.
- Hosted exercise demo videos — deep-links only (content licensing isn't our business).
- Read-API tokens, per-workout GPX/TCX/FIT export, outbound webhooks — deferred; full
  JSON+CSV Export ships in M2, the rest layer onto the same event model later (ADR-0006).
- Health Connect / Garmin / Fitbit / Withings / Oura connectors — deferred to M3+ and
  built per-module when a user with that device appears (ADR-0006); Apple + Whoop cover the
  household. Aggregator APIs (Terra et al.) are out — enterprise-priced.
- Sharing/social features: accounts are fully isolated; only the Exercise library and Food
  catalog are shared. (Revisit on real demand.)
- Staleness nudges, weekly LLM digest, weight forecasting (cut in the extras round).
  Internal weight-trend math for Budget self-calibration is allowed (ADR-0004) — there is
  just no forecast UI.
- TimescaleDB: prod stays plain Postgres on the shared CNPG cluster; partition
  `health_records` by time only if growth ever forces it.

## Open items for implementation sessions

- Whoop Connector at M2 build time: re-verify v2 API scopes, webhook payloads, rate
  limits, and token-refresh against developer.whoop.com (it moves fast).
- Apple Connector: settle the free-Shortcut health-sample coverage (does it carry HRV/SDNN
  and sleep stages, or is export.zip still needed for those?) and the ingest JSON schema.
- Connector research follow-up before building beyond Apple+Whoop: Strava post-2024 terms,
  Withings/Oura/Polar official APIs, nutrition exports (MFP/Cronometer/MacroFactor),
  FIT/GPX library maturity (docs/research/2026-06-13-integration-landscape.md "not yet
  verified").
- Recovery model details (muscle-group fatigue decay curves) — research at M1 build time.
- Progression mechanics at engine-build time: RIR→RPE mapping, effort-adjusted e1RM
  formula choice (Epley/Brzycki family), load-increment and back-off thresholds — all as
  cited Principles (Zourdos 2016; Graham & Cleather 2021; Refalo 2023).
- Principles KB content: author the rules and verify every citation against the primary
  literature (deep-research pass); define the preset parameterizations (GZCLP,
  upper/lower, PPL, 5/3/1-style) on top of the generator.
- Fitbod CSV column inventory against a real export from Viktor's account.
- Barcode decoder library choice; generic-foods seed source (USDA FDC vs curated list).
- Whether custom Exercises/Foods are visible to other users or private (default: private).
