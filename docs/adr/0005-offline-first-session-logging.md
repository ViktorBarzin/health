# Session logging is offline-first

Status: accepted (Viktor, 2026-06-13)

The app is a PWA with no native/watch tier (ADR-0001 stack, ADR-0004 scope), and gyms are
connectivity dead zones — a logger that loses sets gets deleted (Boostcamp added offline
mode in 2024 specifically after data-loss complaints; competitive research
2026-06-13). Decided: the Session-logging surface is built **offline-first from M1**, not
retrofitted later. A service worker caches the logging shell; Sets/Sessions written at the
gym land in an IndexedDB write queue and sync to the API when connectivity returns.
Conflict policy is last-write-wins per record — acceptable because accounts are isolated
(ADR-0003) and a user logs from one device at a time; the queue is single-device, no CRDT.
The Recommendation for the visit is prefetched when the Session starts so targets, plate
math, rest timers, and PR detection all work with zero signal.

## Consequences

- The logging UX is designed around the queue from day one (optimistic UI, sync-state
  indicator); read-heavy surfaces (dashboards, history, nutrition) stay online-only.
- PR detection must run client-side against a cached per-exercise history snapshot to fire
  offline; the server re-validates on sync.
- Retrofit cost avoided, but M1 carries the service-worker + queue infrastructure up front
  (estimated M–L).
