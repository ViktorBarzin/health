# Extend the existing app into the fitness platform — no greenfield, no SparkyFitness

Status: accepted (Viktor, 2026-06-12)

This repo started as an Apple Health dashboard (import export.zip, visualize). The new goal is a
full multi-user fitness platform: continuous health-data ingestion, gym workout logging and
plan building (replacing Fitbod), nutrition tracking (replacing MyFitnessPal), and a
recommendation engine. We considered a greenfield rebuild and adopting SparkyFitness (OSS
MyFitnessPal alternative), and decided to **extend this app instead**.

Why: the hard, battle-tested pieces are reusable as-is — the streaming XML ingest pipeline
(lxml iterparse → COPY bulk insert → dedup), the Svelte chart library, multi-user WebAuthn
auth, and the live DB with 6.6M records. The new fitness domain (exercises, sets, plans,
nutrition, recommendations) is *additive*: new tables and routes alongside the existing
raw-observation layer, which is precisely the ingest foundation the platform needs. A
greenfield would rewrite the hard 20% to win cleanliness on the 80% that is new code either
way. SparkyFitness was rejected: foreign stack (React+Node vs our FastAPI+SvelteKit), no
recommendation engine, and Fitbod-style strength planning would still be custom work in
someone else's codebase — it stays a UX reference for nutrition features.

## Consequences

- A renovation backlog rides along with the feature work: sessions move out of process
  memory (today every deploy logs everyone out), the DB connection moves off the legacy
  `postgresql.dbaas` Service (pinned to a CNPG pod IP; failover behavior unverified) to
  `pg-cluster-rw.dbaas`, the stale TimescaleDB claim in CLAUDE.md gets corrected (prod is
  plain Postgres), and the frontend gets PWA treatment for phone use in the gym.
- The Feb 2026 → present data gap closes with one fresh full Apple Health export per user
  (export.zip always carries full history; the dedup layer makes re-import safe).
