# Continuous, damped, deterministic Program adaptation; the LLM narrates and proposes

Status: accepted (Viktor, 2026-07-14)

## Context

Viktor asked for a "recursive learning system": the Program should update itself from what
happens in the gym (missed sets/reps) and from health data, continuously — while he still
always has a schedule to follow, anchored to well-established programming. Two loops already
close (per-set Progression, per-day autoregulation); nothing ever changed the Program itself.
An LLM-driven adapter was on the table (in-cluster qwen3-8b via llama-swap, plus
claude-agent-service), as was requiring approval for every change.

## Decision

A third nested loop, the **Block Review** — deterministic, Principle-bounded, auto-applying —
with the LLM strictly in the propose-and-explain seat (ADR-0002 unchanged):

1. **Evaluation is continuous** (after each finished Session / data sync), but application is
   **damped**: changes touch future days only, each lever has a cooldown (a muscle's weekly
   volume target moves at most once per training week; an exercise rotates at most once per
   slot per week), and materiality thresholds stop noise from becoming churn. Viktor chose
   maximal reactivity twice in the grill; damping is the control-theory necessity that keeps a
   followable schedule out of it, not a preference override.
2. **All levers are in scope** — volume ramp, rep placement, exercise pool, and even split /
   days-per-week — but **structural changes land only at block boundaries and only as a switch
   to another established template** from the preset catalog (never a bespoke invented split,
   never a mid-week restructure). "Follow well-established schedules" survives full autonomy.
3. **Every change is versioned with a receipt** (what moved, from→to, which Adherence/Recovery
   evidence, which Principle bounds it) — the same receipts-everywhere covenant Programs
   already honour.
4. **The LLM narrates and proposes; it never decides.** Qwen (in-cluster, free) runs when a
   training week closes and on demand: a coach's-notes narrative plus structured Proposals that
   apply only after engine validation AND Viktor's approval. Research (Claude/deep-research)
   is gap-driven and produces candidate Principles/presets with verified citations that merge
   only after human review — ADR-0004's every-citation-verified guarantee is non-negotiable.
5. **Adherence requires persisting the Prescription.** Starting any Recommendation snapshots
   its slots immutably; performed Sets are measured against that snapshot. (Today the
   prescription is lost the moment the user edits a pre-filled Set — unmeasurable by design
   until now.)

## Consequences

- New schema: `prescriptions` (one per started Session), `program_revisions` (the versioned
  change log), later `proposals`. Programs gain a `version`.
- An LLM/GPU outage never stalls programming — the numeric loop is self-sufficient; only
  prose and proposals pause.
- Auto-applied changes are bounded by the same Principle bands autoregulation uses; anything
  outside the bands can only arrive as an approved Proposal or a re-quiz.
- The day-level autoregulation and set-level Progression keep running unchanged underneath;
  the Block Review only moves the targets they work toward.
- Rejected alternatives: LLM-driven auto-apply (nondeterministic churn, receipts impossible,
  outage-fragile); approve-everything (inconsistent with daily autoregulation, turns the app
  into a nag); block-end-only adaptation (a chronic in-block failure waits weeks for help).
