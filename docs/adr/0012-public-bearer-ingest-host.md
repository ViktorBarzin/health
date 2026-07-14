# A public, auth-free host serves push ingest, secured by per-user hashed tokens

Status: accepted (Viktor, 2026-07-14)

## Context

Continuous Apple Health import (after every workout, no manual steps) has exactly one free
path: iOS Shortcut automations reading HealthKit and POSTing to us (ADR-0006's push-receiver
kind — Apple offers no cloud API to pull from, and Health Auto Export is a paid app). But a
Shortcut's `Get Contents of URL` cannot complete the Authentik forward-auth dance, and the
app's identity model trusts an `X-authentik-email` header injected at the ingress — an
auth-free public route into the same app would let anyone spoof that header.

## Decision

A dedicated public host, `health-api.viktorbarzin.me`, auth `none`, with the hole closed
twice at the ingress and once in the app:

1. **Path allowlist**: the host routes ONLY `/api/ingest` — every other route 404s at
   Traefik, so the forward-auth-trusting API surface is unreachable through it.
2. **Header stripping**: the shared `strip-auth-headers` middleware removes every inbound
   `X-authentik-*`, so even the routed path can never carry a spoofed identity.
3. **The route authenticates itself**: `POST /api/ingest/apple` accepts only a per-user
   bearer token minted in Settings — 32-byte urlsafe secrets, stored as SHA-256 hashes
   (plaintext shown once), revocable, `last_used_at` as the pipeline's liveness signal.
   It never consults the forward-auth identity.

Sablier uses the `blocking` strategy on this host: a programmatic POST is held while the
scaled-to-zero pod wakes, never answered with the HTML wake page.

## Consequences

- The Shortcut setup is one paste of the token; everything after is automatic. Re-sends are
  free (the ingest lands through the same idempotent dedup + rollup recompute as every
  other Import), so overlapping automations and locked-phone retries self-heal.
- A leaked DB row reveals no usable credential (hash only); a leaked token is revocable and
  scoped to ingest-only — it cannot read anything.
- The tripit-api precedent (public auth=none host + stripped headers for a client that
  can't SSO) is now a shared pattern; future push Connectors (Whoop webhooks) ride the same
  host.
- Rejected: LAN-only host (the phone syncs from anywhere, not just home wifi); embedding
  the session cookie in the Shortcut (expires, unrevocable, full-account scope); a paid
  sync app (zero-cost rule; also rejected by Viktor 2026-06-12).
