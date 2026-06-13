# Integration landscape for a self-hosted fitness platform (2026-06-13)

Deep-research run (107 agents, 3-vote adversarial verification) + a direct follow-up fetch
on Whoop, scoped to: how does a self-hosted FastAPI/K8s PWA with **no native mobile app**
ingest health data per-user, opt-in, in 2026. Decisions drawn from this live in ADR-0006.
All facts dated 2026-06-13; this space moves fast — re-verify before building any connector.

## Verified access matrix

| Platform | Best path for us | Auth | Push/Pull | HRV / RHR / sleep | Feasibility |
|---|---|---|---|---|---|
| **Apple Health** | push receiver (free iOS Shortcut, or HAE app) | per-user API key header | push (best-effort) | HRV via export.zip; Shortcut HRV coverage = build-time unknown | **High** — one endpoint our side |
| **Whoop** | scheduled puller on official API | OAuth2, server-side secret | webhooks + pull | **all three, native** (+ recovery score, SpO2) | **High** — official, individual-OK |
| **Health Connect (Android)** | scheduled-export zip → self-hosted storage poller | none (file pickup) | pull from storage | RHR + sleep (no HRV via OSS bridge) | **Medium** — zip/SQLite parsing |
| **Garmin** | python-garminconnect (unofficial) | unofficial login | pull (CronJob) | all three + readiness + nutrition | **Medium** — ToS/ban risk |
| **Fitbit** | Google Health API (replacing legacy) | Google OAuth2 | pull | yes (no nutrition at launch) | **Medium** — weeks-old, mid-migration |

## Key verified facts

- **No official HealthKit web/cloud API** — confirmed by the whole ecosystem of workaround
  apps. iOS continuous ingest = a companion pushing to our endpoint. HealthKit is
  unreadable while the phone is locked (Apple restriction, uncircumventable) → ingest is
  best-effort, idempotent batch receipt, never a reliable cron.
- **Health Auto Export** (iOS, v9.0.10): POSTs 150+ Apple Health metrics as JSON/CSV/GPX to
  any URL (self-hosted/LAN allowed) with custom auth headers. Paid: Basic $2.99 one-time /
  Premium $6.99-24.99. → optional client, not required (free Shortcut covers the no-pay
  path).
- **Whoop** (verified directly, developer.whoop.com): OAuth2, **v2 current** (v1 webhooks
  removed — build on v2), webhooks for real-time data, syncs workouts/sleep-with-stages/
  recovery/HRV/SpO2/body measurements. Up to 5 apps per developer; approval only needed
  beyond 10 users; no fee for individual development. Rate-limited (per-minute + per-day
  headers). **Anca's path — and the best Readiness source in the household.**
- **Google Fit REST API is a dead end** — sign-ups closed since 2024-05-01, all Fit APIs
  sunset end-2026, "no alternative to the Fit REST API." Cannot even register today.
- **Health Connect**: on-device store (no cloud API — very likely, not positively
  re-confirmable: the official comparison page vanished after Nov 2025). Native **scheduled
  export** (daily/weekly/monthly, Android 14+) writes a single `Health Connect.zip`
  (unencrypted SQLite, ~20 MB) to a user-chosen cloud-storage app — **not** an HTTP push.
  A self-hosted target (e.g. Nextcloud) + a poller is the pickup pattern. **HCGateway**
  (OSS, GPL-3.0, alive June 2026) is a push-bridge Android app, but **no HRV** and a 2026-03
  security caveat (server operator can decrypt stored data).
- **Garmin**: Connect Developer Program is "business/enterprise use" only — and per official
  forum staff replies (Apr/May 2026) the new-partner form is removed and **all** new API
  applications are paused, no projected reopen. No official individual path.
  **python-garminconnect** (unofficial, MIT, v0.3.5 2026-06-04, actively maintained) covers
  HRV/RHR/sleep/readiness/body-comp/nutrition + ~38 activity methods — drives internal
  endpoints (unquantified ToS/ban risk; headless-auth/MFA behavior unverified).
- **Fitbit**: legacy Web API **decommissioned ~September 2026**; replacement is the **Google
  Health API** (cloud REST, Google OAuth2, GA ~end-May 2026, weeks old, breaking scope
  renames at GA, **no nutrition at launch**, excludes legacy non-Google Fitbit accounts).

## Self-hosted ecosystem patterns (validated against our plan)

The working 2026 architectures, all of which our framework subsumes: (a) **companion-app
push** to an authenticated endpoint (HAE / HCGateway / our free Shortcut); (b) **scheduled
file export + server-side pickup** (Health Connect zip, Health Sync → Drive); (c)
**unofficial-API CronJob pollers** (python-garminconnect); (d) **official cloud OAuth**
(Whoop, Fitbit/Google Health). Our `SourceConnector` ABC = the union: push-receiver,
scheduled-puller, archive-Import — see ADR-0006.

## Not yet verified — research follow-up before building these connectors

Strava post-Nov-2024 API terms (data-use/AI restrictions); official individual APIs for
**Withings, Oura, Polar AccessLink, Suunto, Coros** (auth + webhook + recovery coverage);
nutrition exports (**MyFitnessPal, Cronometer, MacroFactor**); FIT/TCX/GPX Python library
maturity (fitdecode/fitparse/garmin-fit-sdk); aggregator pricing (Terra/Vital/Spike/Thryve
— assumed enterprise-priced and out, unconfirmed). None of these block M2 (Apple + Whoop).
