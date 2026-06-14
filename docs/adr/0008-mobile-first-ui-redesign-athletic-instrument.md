# Mobile-first UI redesign: Today-centered IA + "Athletic Instrument" design system

Status: accepted (Viktor, 2026-06-14)

The UI still wears its origins. This repo began as an Apple Health *dashboard* (ADR-0001) and
the chrome never caught up with the platform it became: you land on a passive health-metrics
dashboard, a global date-range picker (`7D/30D/90D/1Y/All` + `Raw/Day/Week/Month` + two date
inputs) is bolted to the top of *every* screen — including the live Session page, where it is
meaningless — Nutrition is buried two taps deep in a "More" sheet despite the app explicitly
replacing MyFitnessPal, and the visual language is the generic "dark dashboard" recipe (system
font stack, slate surfaces, emerald accent) that reads as template, not product. ADR-0007 fixed
the *surface* strategy (phone-first PWA, used standing at a rack mid-Session); this ADR fixes the
*design language and information architecture* that surface presents.

We decided to do a **system + IA rework**, not a repaint — a repaint would leave a prettier
version of the wrong shape.

## Decision

**Information architecture — re-centred on the train/eat/recover loop:**

- **Home is "Today"**, an action-first hub (today's Recommendation with a Start/Resume Session
  button, Budget remaining, Readiness, recent Sessions) — not the health-metrics dashboard, which
  demotes to a review surface.
- **Five-slot primary nav: Today · Train · Nutrition · Progress · More.** Train owns Sessions +
  Programs + Exercises + imported Workouts; Nutrition (Diary + Budget) is promoted out of "More";
  Progress is the review surface (metrics, trends, PRs, body, sleep, readiness); More holds
  settings, connections, import/export. The tab is **Train** (the verb / the action) — deliberately
  not "Training" (a noun CONTEXT.md avoids) nor "Workouts" (which means imported sensor records).
- **The global date-range picker is evicted from the shell** and lives only on the Progress/review
  screens, where a date range is meaningful.

**Design language — "Athletic Instrument":** dark-native, premium, data-confident; designed to be
read at arm's length, one-handed, mid-set, under gym lighting.

- **Near-monochrome surfaces**, dark by default and a **follow-the-system light theme**, driven by
  strictly semantic tokens (`--surface`, `--text`, `--accent`, …) — zero hardcoded slate/emerald
  anywhere, so the light theme is the same tokens with a second value set.
- **One electric accent — volt lime** — for the primary action and live state. The eight
  metric colors (heart/steps/energy/sleep/oxygen/weight/workout/distance) are **confined to data
  visualisation**; they never appear in chrome.
- **Type is a precision-readout pairing: Geist Sans** (UI/headlines) **+ Geist Mono** (every live
  number — weight×reps, the rest timer, calories remaining, Readiness). Self-hosted variable woff2
  (offline PWA, no CDN), **tabular figures** so numbers don't jiggle as they tick.
- **The hero number is the screen.** One primary action per screen, large tap targets, big
  confident numerals; chrome recedes.
- **Motion is tactile-precise** + haptics: logging a Set is a crisp tick + buzz, steppers feel
  mechanical, a PR is a sharp confident flash (not confetti). Feedback never blocks logging.

**Identity deferred.** The product name is not yet chosen; the UI renders it through a single
swappable wordmark/name token so renaming later (and adding a real logo) is a one-line change, not
a hunt-and-replace.

**Rollout.** The whole app is redesigned in this engagement, in incremental landable commits, with
the foundation (tokens, self-hosted fonts, the new app shell + nav, base components, the Today hub)
landing first because every screen depends on it.

## Alternatives considered

- **Visual refresh only** (restyle, keep IA): rejected — leaves the vestigial date header,
  dashboard-first home, and buried Nutrition in place.
- **Keep the health dashboard as home** / **Train as home** / **adaptive home**: rejected in favour
  of the Today hub as the action-first launchpad that unifies training, nutrition, and readiness.
- **Editorial / Gamified / Clinical-minimal** aesthetics: rejected — editorial and gamified fight
  the fast mid-set logging use; clinical-minimal is calm but undifferentiated.
- **Electric-blue / energy-orange / keep-emerald** accents: rejected for volt lime as the most
  unmistakably athletic identity (blue kept as the safe runner-up).
- **Space Grotesk + Inter** / **condensed scoreboard** / **Inter-only**: rejected — Geist Mono's
  device-readout numerals embody the instrument metaphor best; condensed risks the gym-flyer
  cliché; Inter-only stays generic.
- **Dark-only** / **build both themes with no system-following**: superseded by dark default +
  `prefers-color-scheme` light.

## Consequences

- **Semantic tokens are now load-bearing.** Any hardcoded color in a component is a bug; both
  themes must be QA'd, and charts are recolored so the metric palette lives only in data-viz.
- `app.html` `theme-color` becomes scheme-aware (was hardcoded `#10b981`); the PWA manifest name and
  apple title route through the deferred wordmark token.
- Self-hosted Geist adds font weight to the bundle but is offline-safe and removes a CDN/privacy
  dependency.
- Navigation muscle memory changes (Dashboard→Today, Nutrition promoted); the change is one-time and
  intentional.
- Deferring the name keeps the identity cheap to finalise later; the light theme and any rename are
  token flips, not rewrites.
- Complements ADR-0007 (surface strategy) and serves the unified Goal of ADR-0004 (Today surfaces
  both the training Recommendation and the nutrition Budget on one screen).
