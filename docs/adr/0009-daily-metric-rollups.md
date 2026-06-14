# Daily metric rollups for dashboard/metrics reads

Status: accepted (Viktor, 2026-06-13)

The dashboard/metrics endpoints aggregate raw `health_records` on every wide-window load.
Measured on prod: a `GROUP BY date_trunc('day', time)` over HeartRate (one user) scans
**~1.05M rows** and spills the sort to disk → **1.6 s** (≈790 ms even with a HashAggregate
on a large `work_mem`). Several such queries fire per load, so a 1y/all view is multi-second
on the backend. Raw scans grow with history and worsen as more users/metrics arrive.

Decided: maintain a **daily rollup table** (`metric_daily`: `user_id, metric_type, day` →
`count, sum, min, max`, avg derived as `sum/count`). The dashboard and the metrics
time-series endpoint read rollups for **day-and-coarser** resolutions (week/month re-bucket
the ~per-day rows — at most ~1,900/metric — cheaply), turning a 1M-row scan+sort into a
~1,900-row read (<10 ms). `raw` resolution still reads `health_records` directly (capped).

Rollups are kept correct by **recomputing the affected `(user, metric, day)` buckets after
each ingest batch** (Apple Health import, Fitbod import, Connector sync) — ingest is already
batch-oriented, so a post-batch recompute of the touched days is simple and idempotent — plus
a **one-time backfill** of the existing 6.6M rows (a single `GROUP BY`, run once at deploy).

## Considered & rejected

- **Query-time only + bigger `work_mem`**: ~2× (avoids the disk spill) but still scans ~1M
  rows per heavy metric every load; doesn't scale.
- **TimescaleDB continuous aggregates**: the natural fit, but prod is plain Postgres on the
  shared CNPG cluster (ADR direction; not TimescaleDB) — so we build the equivalent by hand.
- **Expression index on `date_trunc('day', time)`**: `date_trunc` over `timestamptz` is
  STABLE not IMMUTABLE, so it can't be indexed without a generated column, and it still
  wouldn't avoid scanning every row in the window. Rollups dominate.

## Consequences

- Write path gains a post-ingest rollup step; a new table + migration + a one-time backfill.
- Rollups are derived data: if ever suspected stale, a full rebuild is a single `GROUP BY`.
  The backfill/rebuild is the recovery path.
- category_records (sleep, etc.) are lower-volume and stay query-time for now; revisit only
  if they show up in telemetry.
