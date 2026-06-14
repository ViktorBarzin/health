# UI redesign — Today-centered IA + "Athletic Instrument" design system

Decision record: ADR-0008. Surface strategy: ADR-0007 (phone-first PWA).
Built with the `frontend-design` skill, in a worktree, landed as incremental commits.

## Goal

Replace the inherited Apple-Health-dashboard UI with a mobile-first, action-centred fitness
platform: a **Today** hub home, a **Today · Train · Nutrition · Progress · More** nav, and an
**Athletic Instrument** design language (near-mono dark + follow-system light, single volt-lime
accent, Geist Sans + Geist Mono, big numeric readouts, tactile-precise motion). Whole app, all
24 routes + 35 components.

## Non-negotiable invariants (from the grill)

- **Semantic tokens only** — no hardcoded slate/emerald in any component; light theme is a second
  token value set via `prefers-color-scheme`.
- **Volt lime is the only chrome accent**; the 8 metric colors are confined to charts.
- **Geist self-hosted** (variable woff2, offline); **tabular figures** on all numeric data.
- **One primary action per screen**, big tap targets, hero numbers.
- **Motion never blocks logging**; haptics on set-log / PR / finish.
- Product name stays behind a **single swappable wordmark token**.
- No domain change → **CONTEXT.md untouched**; no migration; backend untouched.

## Phases (each a landable commit)

1. **Foundation** — `app.css` semantic token system (surface/text/accent/border/ring/space/radius/
   elevation/typescale; dark + `prefers-color-scheme` light + `[data-theme]` override hook); volt-lime
   + accent-ink; self-host Geist Sans/Mono (`@font-face`, font tokens, `tabular-nums`); `app.html`
   scheme-aware `theme-color` + wordmark-driven apple title; `lib/ui/haptics.ts` + motion tokens.
2. **Primitives** — `lib/components/ui/`: Button, Card, BottomSheet, SegmentedControl, Stepper,
   NumberReadout (mono), StatTile, Chip, Field, ProgressBar/Ring, Badge, EmptyState, Toast.
3. **App shell + nav** — `nav.ts` (5-tab + More sheet); redesign `BottomNav` (safe-area, volt active),
   `Header` (wordmark token; **evict global `DateRangePicker`**), `Sidebar` (desktop adaptation of the
   same nav); rewire `+layout.svelte`.
4. **Today hub** — rewrite `routes/+page.svelte`: Recommendation + Start/Resume Session hero, Budget
   remaining, Readiness, recent Sessions (restyle ReadinessCard/BudgetCard/TodaySummary/RecentWorkouts).
5. **Train** — `/sessions`, **`/sessions/[id]` (flagship)**, `/sessions/generate`, `/programs*`,
   `/exercises*`, `/workouts*`; rework Stepper/NumberReadout/EffortChips/SetTypeChip/RestTimer/
   PRCelebration/PlateCalculator/SyncIndicator/ExercisePicker + superset UI to the new system.
6. **Nutrition** — `/nutrition` (BudgetCard hero), `/nutrition/history`; AddEntrySheet/BarcodeScanner/
   CustomFoodForm/RecipeBuilder restyled to the new primitives.
7. **Progress** — `/metrics*`, `/trends`, `/body`, `/sleep`, `/analytics`, `/principles/[key]`;
   `DateRangePicker` mounts here; recolor the 8 chart components to tokens (metric palette lives here).
8. **More** — `/settings`, Connections, ExportData, GymProfileSettings, import (XmlUpload/ImportStatus/
   FitbodImport).
9. **PWA polish + verify** — scheme-aware manifest/theme/splash; run on a mobile viewport, screenshot
   key screens, keep all vitest green, `vite build` clean; land to master, watch CI → deploy → rollout.

## Verification

- Pure-logic changes (e.g. `nav.ts`) get/keep vitest coverage; **presentational restyle is verified
  visually** (mobile-viewport screenshots via the run/verify path) + by keeping existing suites green
  (`pr`, `nutrition`, `queue`, `engine`, `barcode`, `budget`, `connections`, `fitbod`).
- `vite build` must pass; both themes spot-checked; the live Session flow exercised offline.
