#!/bin/sh
set -e

# Run database migrations
cd /app/backend
alembic upgrade head

# Seed the shared Exercise library from the vendored free-exercise-db dataset.
# Idempotent (upsert by natural key), so it is safe to run on every boot and
# dataset updates flow through. Best-effort: a seed failure must not stop the
# app from serving, so it does not run under `set -e`.
python -m app.services.seed_exercises || echo "WARN: exercise library seed failed; continuing"

# Seed the Principles knowledge base (cited exercise-science rules, ADR-0004).
# Idempotent (upsert by key), so it is safe to run on every boot and authoring
# edits flow through. Best-effort: a seed failure must not stop the app serving.
python -m app.services.seed_principles || echo "WARN: principles KB seed failed; continuing"

# Seed the generic whole-foods Food catalog (the nutrition starter set, #21).
# Idempotent (upsert by slug among shared rows), so it is safe to run on every
# boot and corrections flow through. Best-effort: a seed failure must not block.
python -m app.services.seed_foods || echo "WARN: generic foods seed failed; continuing"

# Populate the daily metric rollups the dashboard/metrics read path uses (ADR-0009).
# GATED: this skips immediately when metric_daily is already populated, so a normal
# pod restart does NOT re-scan the ~6.6M-row health_records table — only the first
# deploy after the migration pays the one-time GROUP BY. Force a full rebuild for
# recovery with `python -m app.services.rollup --rebuild`. Best-effort: a failure
# must not block boot (the read path degrades, it doesn't break).
python -m app.services.rollup || echo "WARN: metric rollup backfill failed; continuing"

# Start backend in background
# 0.0.0.0 (not loopback): the public ingest host (ADR-0012) routes /api/ingest
# STRAIGHT to this port via the Service — the SvelteKit hop would eat the
# Shortcut's text/plain POST with its global CSRF guard. In-pod, the node
# proxy still reaches it via 127.0.0.1.
uvicorn app.main:app --host 0.0.0.0 --port 8000 &

# Start frontend as PID 1
cd /app/frontend
exec node build
