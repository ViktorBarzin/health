# Server-scheduled Web Push is the rest timer's locked-phone and Watch path

Status: accepted (Viktor, 2026-07-13)

## Context

The rest timer (a Set is logged → countdown → cue) fires a WebAudio beep +
`navigator.vibrate` from the page. That only works while the PWA is foreground with the
screen on; pocket the phone and iOS suspends the page — the timer ends silently. Fitbod
solves this with native local notifications, which a PWA does not have: the Notification
Triggers API is dead, and iOS never runs page timers under lock. Viktor also wants the cue
on his Apple Watch, and watchOS cannot install a PWA at all — no browser, no home screen
(ADR-0007 keeps native apps out of scope).

The one mechanism that reaches a locked iPhone from a web app is **Web Push** (supported
for installed PWAs since iOS 16.4, standard protocol, no Apple developer account), and iOS
mirrors lock-screen notifications to a paired Watch — which covers the watch wish without
any watch app, exactly in the case that needs it (phone locked = phone in pocket).

## Decision

When a Set is logged online, the client also schedules a push server-side ("fire at
`ends_at`"); skipping or logging the next set early cancels it. The backend stores
subscriptions (VAPID, `pywebpush`) and delivers due pushes from a DB-backed schedule
(claim-with-`SKIP LOCKED` poller, safe across replicas/restarts). The in-page beep +
vibration stay the primary cue; push is the locked-phone overlay.

## Consequences

- Needs signal at set-log time: an offline-queued Set schedules no push, and a cancel that
  can't reach the server may let a stray notification fire. Accepted — the gym is
  "usually online, occasional drops" (2026-07-13), and degradation is to today's behavior.
- Push transit adds ~1–3 s of jitter on a 60–180 s timer. Accepted.
- The service worker stays `generateSW`; push/notificationclick handlers ride in via
  `importScripts` — no `injectManifest` migration.
- Watch delivery is OS mirroring, not ours to control: verified on-device as the feature's
  acceptance step; worst case the cue is still on the iPhone lock screen.
- New moving parts owned: VAPID keypair (Vault), `push_subscriptions` + scheduled-push
  tables, a poller task. All self-hosted and free — no external push vendor beyond the
  browser vendors' own push services, which is inherent to Web Push.
