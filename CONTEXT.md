# Health

Self-hosted multi-user fitness platform: continuously ingests each user's health data
(Apple Health, scale, Strava), tracks gym training and nutrition, and recommends workouts —
replacing Fitbod and MyFitnessPal.

## Language

### Training

**Session**:
A gym workout logged live in the app by the user — an ordered list of Sets.
_Avoid_: workout, routine, training (as a noun)

**Workout**:
An activity recorded by a device or external app and imported (heart rate, calories,
duration, optional GPS route). Always means the imported sensor record, never the thing
the user logs.
_Avoid_: activity, exercise session

**Set**:
One performed set within a Session: an Exercise, weight × reps, optional Effort.
Warmup flags exist on imported history but are not part of the live logging flow.

**Effort**:
A one-tap reps-in-reserve rating on a Set (0 / 1 / 2 / 3 / 4+ — "how many more reps were
left?"); optional on every Set, nudged on an Exercise's last Set, stored as RPE-equivalent.
_Avoid_: RPE, difficulty

**Exercise**:
An entry in the shared exercise library — a movement with muscle mappings. Seeded from
free-exercise-db; users can add custom Exercises.
_Avoid_: movement, lift

### Recommendation

**Program**:
A generated multi-week training schedule serving the user's Goal — split structure,
ramping weekly per-muscle volume targets, progression scheme, and Deloads. Entered via a
guided quiz or picked from a catalog of named presets; never user-authored.
_Avoid_: template, routine, plan

**Recommendation**:
A generated Session proposal — exercises with target sets × reps × weight — for one gym
visit: drawn from the active Program when one is running, freestyle otherwise; starting it
instantiates the Session the user logs against.
_Avoid_: plan, routine

**Principle**:
A versioned rule in the exercise-science knowledge base — statement, parameter ranges,
applicability, evidence grade, and peer-reviewed citations — from which every Program and
Recommendation parameter derives.

**Deload**:
A planned reduced-load period closing a Program block; calendar-scheduled by the Program
and triggered early by fatigue signals.

**Recovery**:
The per-muscle freshness score computed from recent Set history; steers exercise selection
away from still-fatigued muscles.
_Avoid_: fatigue (it's the same scale, inverted — pick one and we picked Recovery)

**Progression**:
The per-exercise next-target logic ("last time 80kg×8 → try 82.5kg×8") derived from that
exercise's Set history.

**Gym Profile**:
A user's set of available equipment; constrains which Exercises a Recommendation may select.

**Readiness**:
A daily per-user signal derived from HRV, resting heart rate, and sleep trends; an input the
engine may weigh, and a dashboard insight in its own right.

### Nutrition

**Food**:
An entry in the food catalog with per-serving macros — from the Open Food Facts cache, the
generic whole-foods seed, or user-created.

**Recipe**:
A user-defined Food composed of other Foods, with computed per-serving macros.

**Diary Entry**:
A Food logged with a quantity to one Meal of one day.
_Avoid_: log, food log entry

**Meal**:
One of the four daily slots a Diary Entry lands in: breakfast, lunch, dinner, snack.

**Budget**:
The daily calorie/macro target derived from the user's Goal and their measured energy
expenditure (watch data), self-calibrating against the observed weight trend — never a
static formula.
_Avoid_: target, allowance

**Goal**:
The user's current intent — bulk, cut, maintain, strength — a single object parameterizing
both the active Program and the Budget.

### Ingestion

**Import**:
One idempotent ingestion run of a user-supplied archive (Apple Health export.zip, Fitbod
CSV). Re-running an Import never duplicates data.
_Avoid_: sync, upload (the upload is the act; the Import is the run)

**Source**:
The device or app that originally produced a record (Apple Watch, iPhone, Fitbod, smart
scale, Strava).

**Metric**:
A typed per-user health time series (heart rate, body mass, HRV, …) made of timestamped
samples.

## Relationships

- A **Session** contains one or more **Sets**; each **Set** references exactly one **Exercise**
- A **Workout** covering the same physical event as a **Session** is auto-linked to it by
  time overlap; the UI presents the linked pair as one enriched Session
- An **Import** produces **Workouts** and **Metric** samples, each attributed to a **Source**
- A **Goal** drives both the active **Program** and the **Budget** — one object across
  training and nutrition (ADR-0004)
- A **Program** is generated from **Principles**; the daily **Recommendation** is drawn
  from the active **Program** and autoregulated by **Recovery** and **Readiness** — the
  user's edits always win
- A **Recommendation** without an active **Program** is generated freestyle from
  **Recovery** + **Progression** state within the user's **Gym Profile**
- **Progression** consumes rep performance and logged **Effort** (effort-gated double
  progression); when Effort is missing it falls back to rep performance alone — rating is
  never required
- Programs and Recommendations are always generated — user-authored plans remain a
  non-goal (ADR-0002, ADR-0004)
- The **Exercise** library is shared across users; Sessions, Sets, Workouts, and Metric
  samples are private to their user

## Example dialogue

> **Dev:** "He benched on Tuesday with the watch running — do we create a **Workout**?"
> **Domain expert:** "The watch recording becomes a **Workout** at the next **Import**. The
> sets he logged live are already a **Session**. The matcher links the two; he sees one
> Tuesday Session with his sets *and* his heart rate."
> **Dev:** "And if he forgot the watch?"
> **Domain expert:** "Then there's just a **Session** with no linked **Workout** — fully valid."

## Flagged ambiguities

- "workout" was used for both the logged gym activity and the imported watch recording —
  resolved 2026-06-12: logged = **Session**, imported = **Workout**.
- "plan" was cut, then reopened the same evening — resolved 2026-06-12: generated
  multi-week **Programs** exist (ADR-0004); *user-authored* plans remain out. "Plan" stays
  an avoided word; say **Program** (multi-week) or **Recommendation** (today).
