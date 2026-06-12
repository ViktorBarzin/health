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
