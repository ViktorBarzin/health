# Competitive research: top gym apps vs our plan (2026-06-13)

Deep-research run (103 agents, 3-vote adversarial verification per claim) on the most
popular gym/strength apps, diffed against the locked platform scope. Full verified output
with per-claim sources lived in the session transcript; this distills what survived.

## Verified landscape (top-3, not top-5)

Only three apps produced claims that survived verification — Strong and Jefit yielded no
verifiable profiles, so the popularity ordering beyond these three is unknown:

| App | Verified popularity signal | Identity |
|---|---|---|
| **Hevy** | 10M+ users (developer claim), 74K US App Store ratings @ 4.9, #33 Health & Fitness (Jun 2026) | The logging-UX leader; free tier covers most of the toolkit |
| **Fitbod** | ~15M cumulative downloads (Sensor Tower) | The generation/recovery algorithm leader |
| **Boostcamp** | 1M+ lifters (developer claim), 9.1K ratings @ 4.85 | The program-library leader (130+ expert, 12K+ community programs) |

Caveats: user counts are developer marketing (registered, not MAU); feature evidence is
mostly vendor self-description (existence-grade, not quality-grade); June-2026 snapshot —
Hevy Trainer (AI generation, Pro) launched 2026-02 and is evolving.

## Verified validations of our plan

- **Readiness is a real differentiator**: Fitbod's per-muscle recovery (0–100%) is computed
  *solely* from logged training load + recency — verified absence of HRV/sleep/RHR/biometric
  input anywhere in its system. Our HRV/RHR/sleep-driven autoregulation exceeds the
  market's recovery-aware leader.
- **Planned periodization + Deloads** covers Fitbod's documented weakness (reactive-only
  deloading, criticized by reviewers; conservative weight suggestions).
- **Preset catalog confirmed**: Boostcamp's most-demanded programs (GZCLP, 5/3/1 incl.
  BBB, Reddit PPL, nSuns, PHUL/PHAT) directly overlap our chosen four families.
- **RIR Effort chips** are at parity with Hevy/Boostcamp per-set RPE (Hevy: opt-in, 6–10
  scale). **Per-set notes cut vindicated** — even Hevy only has per-exercise notes.
- Nothing verified covers competitor *nutrition* tracking — likely differentiator,
  unverified.

## Gap analysis → adoption decisions (Viktor, 2026-06-13)

| # | Gap | Status before | Decision | Effort |
|---|---|---|---|---|
| 1 | Rest timer (per-exercise defaults, sound/vibration) | CUT 06-12 | **ADOPT — cut reversed on evidence** | S |
| 2 | Set-type flags (warmup/drop/failure + stats-exclusion toggle) | CUT 06-12 (UI) | **ADOPT — cut reversed on evidence** | S |
| 3 | Plate calculator + warm-up calculator (Gym Profile plates) | never considered | **ADOPT** | S |
| 4 | PR detection + live celebration (weight/reps/e1RM/volume bests) | never considered | **ADOPT** | S–M |
| 5 | Per-muscle volume heatmap (the one view all 3 apps share) | engine-internal only | **ADOPT** (SVG body map over existing engine data) | M |
| 6 | e1RM trend charts | engine-internal only | **ADOPT** | S–M |
| 7 | Offline-first Session logging | never considered | **ADOPT — ADR-0005** | M–L |
| 8 | Supersets (grouping + auto-advance; generator may emit them) | never considered | **ADOPT** | M |
| 9 | Exercise demo videos | never considered | **ADOPT as deep-links only** (no hosted video/licensing) | XS |
| 10 | User-authored program builder (Boostcamp's moat) | CUT 06-12 | **CUT REAFFIRMED** — the app builds the plans | — |
| 11 | Strava push (our Sessions → Strava activities) | never considered | **REJECTED** — Strava stays a mirror of the watch | — |
| 12 | Social feed/sharing | CUT 06-12 | stays cut (isolated accounts) | — |
| 13 | Watch companion / HealthKit write-back | — | structurally impossible for a PWA; mitigate with sub-3-tap logging + screen wake-lock (XS) | — |

## Open questions parked

- Strong/Jefit profiles never verified — revisit only if a concrete feature question arises.
- Whether ANY mainstream app autoregulates from biometric readiness (would upgrade our
  differentiator from "beats Fitbod" to "market-unique") — nice-to-know, not blocking.
- Hevy CSV export as an additional import source for switchers — check when multi-user
  onboarding beyond the household ever matters.
