# Mobile-first PWA now; Capacitor Android shell later; iOS native deferred

Status: accepted (Viktor, 2026-06-13)

The phone is the primary surface — the app is used standing at a rack mid-Session, not at a
desk — so every screen is designed phone-first, and the desktop/web layout is the adaptation,
not the other way round. We follow the proven TripIt trajectory (tripit ADR-0013/0014/0017):

1. **Now: a mobile-first PWA.** Installable, offline-first Session logging (ADR-0005), built
   100% in-cluster — no app store, no signing, never expires, no paid account. This is the
   only surface M1–M3 target.
2. **Later: a Capacitor Android shell** wrapping the same SvelteKit build, with self-hosted OTA
   web bundles (rebuild the APK only for native-surface changes). Android because the second
   user (Anca) is on a Xiaomi and Android's useful native capabilities (FCM push, etc.) are
   free. Mirrors the shipped TripIt shell; not started until the PWA is solid.
3. **Deferred: iOS native.** Requires the paid Apple Developer Program (£79/yr) + a Mac build
   chain + 7-day re-sign churn on a free account — Viktor explicitly does not want to pay yet.
   The iPhone uses the PWA (home-screen install; Web Push since iOS 16.4 if ever needed).

## Consequences

- UI work is phone-first by default; AFK agents building screens target a narrow mobile
  viewport first and treat desktop as progressive enhancement.
- The Capacitor shell and any native concerns (OIDC Code+PKCE bearer host, OTA endpoints) are
  out of scope for the current milestones — revisit as a TripIt-style follow-on once the PWA
  is in daily use.
- iOS-only native features (HealthKit write-back, a watch app) remain structurally out (ADR-0006).
