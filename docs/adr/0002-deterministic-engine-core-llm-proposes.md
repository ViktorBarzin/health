# Recommendation engine: deterministic core, LLM proposes on top

Status: accepted (Viktor, 2026-06-12). Consequence "generated each visit / no plan concept"
superseded-in-part by ADR-0004 the same day: generated multi-week **Programs** were added;
user-authored plans remain out. The engine architecture below stands.

The engine must replicate all four Fitbod capabilities: per-muscle recovery balancing,
per-exercise progressive overload, equipment-aware exercise selection, and whole-workout
generation. We chose a **deterministic rule-based core** that computes explainable state
(per-muscle Recovery scores from set history, per-exercise Progression targets, volume
trends) and generates each Recommendation from that state — unit-testable, reproducible,
costs no tokens at the gym door. An **LLM layer** (in-cluster claude-agent-service) sits on
top for drafting variations and conversational adjustments ("30 minutes, no barbell today"),
always grounded in the deterministic state. The LLM proposes; it never decides — the
computed state and the user's edits are authoritative. Rejected: LLM-first generation
(opaque, wobbly run-to-run, per-visit token cost) and pure-deterministic (no conversational
adjustment path).

## Consequences

- Recommendations are generated each visit, Fitbod-style. Plan authoring (user-designed
  splits/templates) is a deliberate non-goal for now — revisit only if generated workouts
  prove insufficient.
- The engine needs muscle mappings (exercise library) and an equipment profile (Gym
  Profile) as first-class inputs, and Fitbod CSV history to avoid a cold start.
