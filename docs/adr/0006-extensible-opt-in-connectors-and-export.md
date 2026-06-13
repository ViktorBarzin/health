# Integrations: extensible opt-in Connectors + full data Export

Status: accepted (Viktor, 2026-06-13). Reverses the 2026-06-12 "no connectors — everything
rides Apple Health export.zip; Strava is a pure mirror" position (memory; CONTEXT.md
flagged ambiguity).

Viktor's framing: "if a new app can't import from everywhere and export to everywhere it's
unlikely to be used." People who care about a health app already track eating and activity
somewhere, so integrations are core, not optional polish. Verified by deep research
(docs/research/2026-06-13-integration-landscape.md), and reshaped by the household reality
that the second user (Anca) now wears a **Whoop** band (excellent recovery data) rather
than an Apple device.

## Decided

1. **A Connector framework, two plug-in surfaces, one data path.** First-party Connectors
   are in-repo Python modules behind a `SourceConnector` ABC (the TripIt provider-ABC
   pattern), each per-user opt-in with credentials stored per user. Three Connector kinds:
   **push receivers** (external client → our bearer-authenticated ingest API), **scheduled
   pullers** (K8s CronJob polling a remote API), and **archive Imports** (uploaded files).
   The second plug-in surface is the **documented bearer ingest API itself** — any external
   script or app can push normalized data without touching our code (ADR-0003 token family).
   All three kinds normalize into the same idempotent ingest pipeline.
2. **Free paths first; paid clients optional, never required.** On iOS (no native app, no
   official HealthKit web API) the continuous path is a push receiver: the **free iOS
   Shortcut** automation is first-class; the **Health Auto Export** app ($2.99+) is an
   optional turnkey client of the same endpoint. Ingest must be best-effort and idempotent
   — HealthKit is unreadable while the phone is locked, so no client can guarantee delivery.
3. **Unofficial-API Connectors are allowed, clearly flagged.** Where no official individual
   API exists (Garmin's program is enterprise-only *and* paused to all applicants as of
   June 2026), an unofficial-API Connector (e.g. python-garminconnect) is permitted as an
   opt-in module labeled "unofficial — best-effort, may break, small ban risk." It's the
   user's account and their call. Built only when a user with that device actually exists.
4. **Full data Export is table stakes.** One-tap per-user archive of all Sessions, Sets,
   Workouts, Metrics, and Diary Entries as JSON + CSV — data ownership and our own DR story.
   Read-scoped API tokens, per-workout GPX/TCX/FIT, and outbound webhooks are deliberately
   deferred (easy to add later on the same event model).
5. **Audience: household now, friends-ready.** Build the framework plus the Connectors the
   household needs; adding Garmin/Fitbit/Oura/Withings later is one module each, not a
   rework.

## Connector lineup (priority for M2 "health")

- **Apple Health** — push receiver (free Shortcut + optional HAE) for Viktor's
  iPhone+Watch; export.zip upload remains as backfill. Carries HRV/RHR/sleep for Readiness.
- **Whoop** — scheduled puller on the official OAuth2 API (v2; webhooks for real-time
  sleep/recovery/workout events; HRV, RHR, sleep stages, SpO2). This is Anca's recovery
  path and arguably the best Readiness input in the household.
- **Deferred to M3+ unless a need appears:** Health Connect scheduled-export pickup (zip →
  self-hosted storage poller; no HRV via the OSS HCGateway bridge) for Android-phone-only
  users; Garmin (unofficial) and Fitbit (Google Health API) when such devices show up.

## Consequences

- M2 carries the framework (opt-in UI, per-user credential storage, CronJob scheduler,
  webhook receiver) up front — the cost that makes every later Connector cheap.
- Platform-fact volatility is real (Fitbit→Google Health API mid-migration, Garmin paused,
  Google Fit dead end-2026); Connectors must be individually swappable and the access
  matrix re-checked before each one is built. Several platforms (Strava post-2024,
  Withings/Oura/Polar, nutrition exports) are not yet verified — research follow-up before
  building those.
