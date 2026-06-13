# Goal-driven Program generation (ADR-0004, issue #13)

The deterministic generator that turns a short quiz into a multi-week **Program**
composed *only* from the **Principles** KB, plus the preset catalog and the path
that lets an active Program drive the daily **Recommendation**. No LLM (that is
#14); no fatigue-triggered early deload (also #14 — calendar deloads only here).

This doc is the spec for the generation algorithm, the preset → quiz mapping, and
how parameter→Principle **provenance** ("why this number") is stored for #14's
receipts UI.

## 1. Data model

A Program is generated, multi-week, one-active-per-user, and fully derived from
Principles. It is persisted across three tables (entity-style UUID PKs, matching
`workouts`/`exercises`/`training_sessions`):

### `programs`
One generated Program for a user.

| column | type | meaning |
|--------|------|---------|
| `id` | UUID PK | |
| `user_id` | int FK users | owner |
| `name` | str | "Upper/Lower Hypertrophy", "GZCLP", or a goal-derived name |
| `preset_key` | str NULL | the catalog preset it was generated from (`gzclp`, …) or NULL for a custom quiz |
| `goal` | `training_goal` enum | bulk/cut/maintain/strength |
| `experience` | `experience_level` enum | beginner/intermediate/advanced |
| `days_per_week` | int | training days/week the quiz asked for |
| `session_minutes` | int | target session length (caps slots/day) |
| `mesocycle_weeks` | int | accumulation weeks before the deload (derived) |
| `total_weeks` | int | `mesocycle_weeks + 1` (the trailing deload week) |
| `deload_week` | int | 1-based week index that is the deload (== `total_weeks`) |
| `status` | `program_status` enum | `active` / `archived` |
| `provenance` | JSONB | `{param_name: {principle_key, value, unit, min?, max?}}` — every Program-level number's receipt |
| `created_at` | timestamptz | |

Active-Program rule: **at most one `active` Program per user** (partial unique
index on `(user_id) WHERE status='active'`). Generating a new one archives the
prior active Program (kept, not deleted — history preserved; documented choice).

### `program_days`
The split: which training day holds which muscle-group slots. One row per
training day in the weekly microcycle (so `days_per_week` rows per Program).

| column | type | meaning |
|--------|------|---------|
| `id` | UUID PK | |
| `program_id` | UUID FK programs (cascade) | |
| `day_index` | int | 0-based position in the week (0 = first training day) |
| `name` | str | "Upper A", "Push", "Full Body", … |
| `slots` | JSONB | ordered list of `{muscle, role_hint?}` exercise slots to fill |

`UNIQUE(program_id, day_index)`.

### `program_muscle_volumes`
Per-muscle **weekly volume target** that **ramps** across the mesocycle then drops
on the deload week. One row per (muscle, week).

| column | type | meaning |
|--------|------|---------|
| `id` | int PK | |
| `program_id` | UUID FK programs (cascade) | |
| `muscle` | `muscle` enum | the dataset muscle group |
| `week` | int | 1-based week index |
| `target_sets` | int | weekly sets for that muscle that week |
| `is_deload` | bool | true on the deload week |

`UNIQUE(program_id, muscle, week)`.

Why store the ramp explicitly rather than recompute: it is small, it is the
receipt the overview UI renders, and #14 will read it to autoregulate; storing it
keeps the generator's output inspectable and deterministic.

## 2. Principle-derived parameters (the ADR-0004 guarantee)

Every numeric choice the generator makes is read from a Principle's `params`
range via `applicable_principles(goal, experience)`. Picked value within a
`{min,max}` range = a documented rule: **midpoint, rounded, clamped to the
range** — deterministic, defensible, and re-derived if the Principle changes.

| generator parameter | Principle key | param read | pick rule |
|---------------------|---------------|-----------|-----------|
| weekly sets/muscle (mesocycle target, the ramp's top) | `volume-dose-response` | `sets_per_muscle_per_week {min,max}` | top of ramp = max; ramp start = min; intermediate weeks interpolate |
| sessions/muscle/week → frequency floor | `training-frequency` | `sessions_per_muscle_per_week {min}` | each muscle's weekly sets split across ≥ min days |
| rep range | `rep-scheme` (NEW) | `rep_range_low`, `rep_range_high` (goal-specific) | read low/high directly |
| effort target (RIR) | `effort-proximity-to-failure` | `reps_in_reserve {min,max}` | working RIR = max of range (furthest from failure within the evidence window) |
| mesocycle length | `periodization` (bulk/strength, int+/adv) → else `deload` | `mesocycle_weeks {min,max}` / `weeks_between_deloads {min,max}` | midpoint, rounded |
| deload timing | `deload` | `weeks_between_deloads {min,max}` | deload after `mesocycle_weeks` |
| deload volume cut | `deload` | `deload_load_reduction_percent {min,max}` | midpoint → deload sets = round(meso_top × (1 − pct/100)) |
| load progression step | `progressive-overload` | `load_increase_percent {min,max}` | recorded as provenance; the per-exercise load comes from the existing Progression core |

**New Principle `rep-scheme`** (category `intensity`): the KB today has no rep-range
parameter, yet the generator must derive rep ranges *from* Principles (not
hardcode). So #13 adds one cited rule carrying goal-specific rep ranges:
strength ≈ 3–6, hypertrophy/bulk ≈ 6–12, maintain ≈ 8–15 — backed by the ACSM
position stand (already cited for progression) + Schoenfeld 2021 loading
meta-analysis (hypertrophy is similar across a wide load range; strength favours
heavier/lower reps). This is the one KB addition; everything else reads existing
rules. Per-goal ranges are encoded as separate params and the generator selects
by goal.

Because rep ranges are now Principle-derived, the strength preset's low reps and
the hypertrophy preset's moderate reps both trace to `rep-scheme` — satisfying
"if Principles change, generation changes".

## 3. Generation algorithm (deterministic, pure core)

`services/program_generation.py` — a pure module mirroring `recommendation.py`:
input = a `QuizInput` + the applicable Principles (already fetched); output = a
`GeneratedProgram` dataclass (days, per-muscle weekly ramp, provenance). No DB, no
clock.

1. **Read params + record provenance.** For each parameter in §2, read the
   Principle range and apply the pick rule; append a provenance entry
   `{param: {principle_key, value, unit, min, max}}`.
2. **Choose the split** by `days_per_week` (the structural choice; see §4 split
   templates). Each split is a fixed list of training days, each day a list of
   muscle **slots**. Slot count per day is capped by `session_minutes` (≈ one slot
   per ~12 min, floored at the split's natural size's minimum) — documented,
   deterministic.
3. **Frequency check.** Count, across the week's days, how many days train each
   muscle. The split templates are authored so every primary muscle is hit ≥ the
   `training-frequency` floor (≥2×) at the supported days/week; the generator
   asserts this (a test pins it) — if a split violated the floor it would be a bug.
4. **Weekly volume ramp.** For each muscle, the mesocycle **top** = volume max,
   the **start** = volume min (both from `volume-dose-response`). Across weeks
   `1..mesocycle_weeks`, linearly interpolate start→top (rounded), so volume
   *ramps up*. The **deload week** sets each muscle to
   `round(top × (1 − deload_pct/100))` — a clear drop. This yields the
   `program_muscle_volumes` rows. Only muscles the split actually trains get rows.
5. **Per-day set distribution (derived, not stored separately).** A day's slot for
   a muscle is prescribed `ceil(week_target / times_trained_this_week)` sets, so
   the per-session sets realise the weekly target across the muscle's training
   days. Rep range + effort target come from §2.

Determinism: no randomness, no clock; integer rounding is fixed; the same quiz +
same Principles → byte-identical Program.

## 4. Split templates (structural, not copyrighted)

A split = a shape: a list of named training days, each a list of muscle slots.
Authored in `services/program_templates.py` keyed by `days_per_week` (the quiz
answer) with a "preferred style" hint a preset can pin. These are generic
strength-training structures (full-body, upper/lower, push/pull/legs) — no
program's copyrighted text or trademarked specifics.

| days/week | default split | days |
|-----------|---------------|------|
| 2 | Full Body ×2 | FB-A, FB-B |
| 3 | Full Body ×3 (or PPL if preset) | FB-A, FB-B, FB-C |
| 4 | Upper/Lower ×2 | Upper-A, Lower-A, Upper-B, Lower-B |
| 5 | PPL + Upper/Lower | Push, Pull, Legs, Upper, Lower |
| 6 | PPL ×2 | Push-A, Pull-A, Legs-A, Push-B, Pull-B, Legs-B |

Each day's slots are muscle groups drawn from the dataset `muscle` enum (chest,
back via lats/middle_back, shoulders, biceps, triceps, quadriceps, hamstrings,
glutes, calves, abdominals). The set realises ≥2×/week frequency for the major
muscles at every supported day count.

## 5. Preset catalog (pinned parameterizations)

A preset = a fixed `QuizInput` + an optional structural style, fed through the
*same* generator (CONTEXT.md/ADR-0004). `services/program_presets.py` holds the
catalog as data:

| preset_key | name | goal | experience | days | style |
|------------|------|------|-----------|------|-------|
| `gzclp` | GZCLP (linear, beginner) | strength | beginner | 3 | full-body, linear |
| `upper-lower-hypertrophy` | Upper/Lower Hypertrophy | bulk | intermediate | 4 | upper/lower |
| `ppl-hypertrophy` | Push/Pull/Legs | bulk | intermediate | 6 | PPL |
| `531-strength` | 5/3/1-style Strength | strength | intermediate | 4 | upper/lower |

A preset's numbers still come from Principles for that (goal, experience) — the
preset only pins the *answers*, not the numbers. So "GZCLP" gets the strength rep
range and the beginner-appropriate volume/mesocycle straight from the KB, and we
reproduce no copyrighted program content (just the structural shape + the
science-based parameters). Browsable + selectable: selecting a preset = generating
a Program with that preset_key.

## 6. Provenance ("why this number")

Stored two ways so #14 can render receipts without recomputing:
- **Program-level** `provenance` JSONB: every scalar parameter →
  `{principle_key, value, unit, min, max}`.
- **Per-muscle ramp**: each `program_muscle_volumes` row carries `target_sets` and
  the `volume-dose-response` key is the Program-level provenance for the volume
  band; the deload rows trace to `deload`.

The API returns `provenance` with the Program so the overview can already show
"10–20 sets/muscle/wk — Schoenfeld 2017" beside each number; #14 turns each
`principle_key` into the full citation card via the existing `/api/principles/{key}`.

## 7. Active Program drives the Recommendation

Extend the recommendation path (#11), do not duplicate it.
`services/recommendation_query.py` gains `recommend_for_user` branching:
- **Active Program exists** → today's Recommendation = the Program's prescription
  for the **next due training day**. "Next due" = `(count of Sessions started
  since the Program's `created_at`) mod days_per_week` → the `program_days` row at
  that `day_index`. The current **week** = `min(weeks_elapsed+1, total_weeks)`
  (weeks since `created_at`, capped). For each slot on that day, pick an Exercise
  matching the slot's muscle, constrained by the Gym Profile (reusing the existing
  equipment filter + the trained-history candidate population, falling back to any
  library Exercise for the muscle when the user has no history for it — a Program
  legitimately introduces movements), and fill load/reps via the existing
  **Progression** core. Sets/slot + rep range + effort come from the Program;
  **deload week reduces** sets (already encoded in the week's volume rows) and the
  Recommendation surfaces it.
- **No active Program** → unchanged freestyle generator.

Starting today's Program workout reuses #11's `instantiate_session` exactly — a
Program Recommendation is the same `Recommendation` dataclass, so the existing
instantiate path and "user edits always win" model apply with no new state.

## 8. API (`/api/programs`)

- `GET  /api/programs/presets` — the catalog (static, for browse).
- `GET  /api/programs/quiz-options` — enum options for the quiz (goals,
  experience levels, day counts) so the UI never hardcodes them.
- `POST /api/programs/generate` — body = quiz answers; generates, persists
  (archiving any prior active), returns the Program with days + volume ramp +
  provenance. `preset_key` in the body = generate from a preset.
- `GET  /api/programs/active` — the user's active Program (or 204/empty).
- `GET  /api/programs/{id}` — a Program overview (own only).
- `GET  /api/programs` — the user's Programs (active first).
- `POST /api/programs/{id}/activate` — re-activate an archived Program.
- `DELETE /api/programs/{id}` — delete a Program.
- Recommendation: `GET /api/recommendations/today` + `POST
  /api/recommendations/today/start` — the unified "today" path that uses the
  active Program when present, else freestyle. (The existing
  `/freestyle` endpoints stay for explicit freestyle.)

## 9. Frontend (mobile-first)

- `/programs` — browse the preset catalog + the user's Programs; CTA to the quiz.
- `/programs/quiz` — the guided quiz (goal, days/week, experience, session
  length); submit → generate → navigate to the new Program overview.
- `/programs/[id]` — Program overview: the weeks × days structure, the per-muscle
  weekly volume ramp (a small bar/heat strip), the deload week flagged, and each
  derived number with its Principle key shown (receipt stub for #14).
- `/programs/today` (or the existing generate page extended) — "today's workout"
  drawn from the active Program; **Start** instantiates a Session (reuse #11).
- Nav: add a "Program" entry (overflow "More" sheet).
- Types in `lib/types.ts`; API methods follow the `api.get/post` pattern.

## 10. Testing (TDD, engine core)

Pure-core tests (`tests/test_program_generation.py`): a generated value lies
within its cited Principle range and provenance maps to that key; if a Principle's
range changes, the generated value changes (inject Principles); split structure
matches days/week; weekly volume ramps then deloads; frequency ≥ Principle min;
each preset produces the expected shape (days, goal-appropriate rep range).
API/integration tests (`tests/test_programs_api.py`,
extend `tests/test_recommendation_api.py`): quiz→generate persists with
provenance; one-active-per-user (generating archives the prior); active Program
overrides freestyle in the recommendation while no-Program still freestyles;
deload week reduces prescribed sets; start instantiates a Session. Keep all 293
backend + 109 frontend tests green.
