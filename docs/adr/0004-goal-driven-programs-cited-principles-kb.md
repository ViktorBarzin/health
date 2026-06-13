# Goal-driven Programs generated from a cited Principles knowledge base

Status: accepted (Viktor, 2026-06-12); supersedes-in-part ADR-0002's "no plan concept"
consequence — generated multi-week Programs are added; user-authored plans remain out.

Same-day reopen of the plans cut: Viktor wants world-class, science-backed training
schedules (e.g. a bulk) grounded in peer-reviewed studies. He is not a gym expert and
delegates the exercise-science judgment to the platform — which means the science must be
encoded, inspectable, and cited, not implicit in code.

Decided:

1. **Two generation horizons.** A **Program** is a generated multi-week schedule serving
   the Goal: split structure chosen by days/week, ramping weekly per-muscle volume targets,
   a progression scheme, and Deloads. The per-visit **Recommendation** is drawn from the
   active Program; freestyle per-visit generation (original ADR-0002 behavior) remains when
   no Program is active. User-authored plans stay a non-goal.
2. **Principles knowledge base.** A versioned table of exercise-science rules — statement,
   parameter ranges, applicability (goal, experience), evidence grade, and citations
   (DOI/PubMed) to primary literature (e.g. volume dose-response ~10–20 sets/muscle/week,
   Schoenfeld 2017; frequency ≥2×/muscle/week, Schoenfeld 2016; 0–3 RIR effort zone,
   Refalo 2023; periodized > non-periodized for strength, Williams 2017; protein
   1.6–2.2 g/kg/d, Morton 2018). The deterministic generator composes Programs *only* from
   Principles, so every parameter is traceable to studies. The LLM layer (ADR-0002)
   explains and adjusts strictly within Principle bounds. Citations are verified against
   the primary literature during KB authoring, not trusted from memory.
3. **Receipts everywhere.** Every generated parameter is tappable to its Principle —
   plain-English rationale plus study links — and each Program carries a "science behind
   this plan" page. Entry is a guided quiz (goal, days/week, experience, equipment,
   session length) plus a browsable catalog of named presets (GZCLP, upper/lower
   hypertrophy mesocycle, PPL, 5/3/1-style) — presets are pinned parameterizations of the
   same generator; no copyrighted commercial program content is reproduced.
4. **Full autoregulation; unified Goal.** The engine acts on Recovery/Readiness — trims or
   swaps volume with the reason shown, reflows missed days, triggers early Deload on
   fatigue signals — and the user's edits always win. **Goal becomes one object driving
   both Program and Budget**: a bulk sets a 10–20% surplus targeting ~0.25–0.5%
   bodyweight/week, self-calibrated against the observed weight trend (internal trend math
   only — no forecast UI, per the extras cut).

## Consequences

- M1 grows: the Principles KB and Program layer are now the core of "workout generation",
  ahead of freestyle-only generation.
- KB authoring needs a dedicated research pass with citation verification — it is content
  work as much as code.
- Everything else in ADR-0002 stands (deterministic core, LLM proposes-never-decides).

### Realized design — Readiness + autoregulation + receipts + adjust (#14, 2026-06-13)

The four-pillar "full autoregulation" promise above was implemented as follows; each piece
is a pure, documented core (no DB/clock/LLM) behind a query layer, matching the
`recovery`/`recommendation` pattern:

- **Readiness** (`services/readiness.py`) — a daily per-user 0–100 biometric signal,
  **separate from training-load Recovery (#10)**. It compares the most-recent HRV (SDNN),
  resting HR and sleep-hours reading to the user's own **trailing 28-day baseline** (robust
  deviation = `(recent − mean)/spread`, spread floored at 5% of the mean), orients each so
  higher = better (HRV up good; resting-HR up bad; sleep saturating above baseline),
  squashes each through a logistic to a 0–100 component, and blends with weights HRV .5 /
  RHR .25 / sleep .25 **renormalised over present metrics**. A missing metric drops out;
  **no usable metric → an explicit `insufficient_data` state, never a fabricated number**.
  At-baseline reads the neutral 50.
- **Autoregulation** (`services/autoregulation.py`) — adjusts the active Program day's
  generated set counts on Readiness + per-muscle Recovery: a combined factor (readiness
  factor 1.0 at ≥60, falling to 0.5 at 0; recovery factor 1.0 at ≥70 per muscle, to 0.5 at
  0) **trims top sets**, a strong+fresh day (≥85, recovery ≥70) allows a small bump.
  Clamped strictly **within the Program's Principle volume band** (per-session floor/ceiling
  from the ramp's accumulation weeks); a trim never raises an already-reduced **deload**.
  Emits a human reason ("Readiness 48/100 — trimmed top sets…"). **User-edited slots pass
  through untouched** (the cardinal invariant). Sustained low readiness (≥3 of the last 5
  days ≤45) trips a **fatigue-triggered early deload**; the rotation **reflows** past
  missed days by Session count.
- **Receipts UI** — every generated parameter on a Program/today taps through to
  `/principles/{key}` (statement + evidence-backed range + cited studies, a new route), plus
  a per-Program "science behind this plan" list with evidence grades + citation counts. The
  daily Readiness card shows its per-metric "X below your baseline" breakdown.
- **Conversational adjust** (`services/adjust.py` + `adjust_agent.py`) — a swappable
  `AdjustProvider` ABC with a **deterministic, rules-based default** (parses "make it
  shorter / no barbell / I'm tired" into bounded levers — `volume_scale`,
  `exclude_equipment`, `max_exercises`) so the feature ships working with **no external
  service**. A real provider calling the in-cluster claude-agent-service is **gated behind
  `ADJUST_PROVIDER=claude-agent`** (default off) and **proposes only**: its JSON is
  validated/clamped to Principle bounds (`validate_adjustment`) before being applied as
  editable targets, and it falls back to deterministic on any failure. No new DB tables —
  Readiness reads existing `health_records`/`category_records`; autoregulation/adjust are
  in-memory transforms over the already-persisted Program + Recommendation.

### Realized design — the unified-Goal **Budget** + weight-trend smoother (#23, 2026-06-13)

Point 4's "Goal becomes one object driving both Program and Budget … self-calibrated
against the observed weight trend (internal trend math only — no forecast UI)" was
implemented as two pure cores behind a query layer, matching the
`readiness`/`recovery` pattern (no DB/clock/IO; `now` + data injected):

- **Weight-trend smoother** (`services/weight_trend.py`) — turns noisy daily BodyMass
  scale readings (`health_records`, `metric_type='BodyMass'`, normalised to kg) into a
  de-noised **"true weight"** (a **time-aware EMA**, half-life ~10 days, so a gap between
  weigh-ins decays history by *elapsed time* not sample count — irregular/sparse sampling
  is handled) and a **rate of change** (kg/week and %BW/week) from an **OLS slope of the
  raw in-window series** (least-squares is itself the noise-robust trend estimator;
  regressing the *raw* series avoids the EMA's lag flattening the slope). A 28-day window
  (matching the Readiness baseline). Empty/only-stale → an explicit `insufficient_data`;
  a single in-window reading → a weight but **no rate** (one point can't define a trend) —
  never a fabricated number.
- **Budget calculator** (`services/budget.py`) — the daily calorie/macro target. It
  **measures TDEE adaptively from energy balance** rather than a static formula:
  `TDEE = avg_logged_intake − rate_kg_per_week·7700/7` (a surplus/deficit shows up as
  weight change at ~7700 kcal/kg). The target is `TDEE + goal_delta`, where the delta is
  sized to drive the **Goal's** intended *rate* (`_GOAL_TARGET_RATE_PCT`, %BW/week: bulk
  +0.375, cut −0.75, maintain 0, strength +0.15) — so it is **self-calibrating**: a
  re-measured TDEE moves the target to keep the goal rate as the body responds. Protein
  comes from the **`protein-intake` Principle** (Morton 2018, 1.6-2.2 g/kg/d; goal-placed
  in the range — cut/strength to the top), fat is 25% of calories, carbs the remainder.
  When energy balance can't be measured (no intake *or* no weight rate) it falls back to a
  **labelled** bodyweight estimate (~31 kcal/kg, `method='estimated'`); with no bodyweight
  at all it returns `insufficient_data` — honest, never confidently wrong.
- **Goal lives in one place** — the Budget reads the user's **active Program's `goal`**
  (`services/budget_query.py` → `active_program`), defaulting to `maintain` when no
  Program is active; there is no second goal concept. **Target rates + the bodyweight
  basis are documented constants** keyed by goal in `budget.py` (not a new table — YAGNI).
- **No new DB tables / no migration** (Alembic head unchanged at `d4e5f6a7b8c9`) — reads
  existing `health_records` (BodyMass), `diary_entries` (intake via the pure
  `nutrition.daily_totals`, reused not re-derived), `principles`, and `programs`. Surfaced
  read-only at **`GET /api/nutrition/budget`** and a mobile **`BudgetCard`** on `/nutrition`
  (target vs logged → remaining, macro bars, the current weight trend/rate). **No forecast
  UI** (the ADR cut) — a current Budget + current trend only, no "you'll hit X by date Y".
