# Authentik is the identity provider; in-app WebAuthn retired

Status: accepted (Viktor, 2026-06-12)

The app shipped with its own WebAuthn passkey registration/login plus an in-memory session
dict — while ALSO sitting behind Authentik forward-auth: a double login that logged everyone
out on every deploy. Decided: the TripIt pattern. Authentik forward-auth at the edge injects
`X-authentik-email`; the app trusts it (forward-auth overwrites any client-supplied
`X-authentik-*` header) and auto-provisions/maps user rows by email. The WebAuthn routes,
credentials table, registration UI, and app-session machinery are deleted. Programmatic
clients — the one-tap export-upload Shortcut — authenticate with a per-user API token on a
bearer-auth ingest route instead, since they cannot follow a 302-to-login.

## Consequences

- New users = Authentik users; there is no in-app registration. Sharing the app with someone
  means creating them an Authentik identity.
- Existing user rows are reconciled to Authentik emails once: ancaelena98@yahoo.com → her
  gmail Authentik identity; the me@viktorbarzin.me row is merged into vbarzin@gmail.com or
  retired after checking what data it owns.
- The ingest route must be reachable by bearer token without the Authentik cookie dance —
  a forward-auth-excluded scoped path/host (TripIt ADR-0017 precedent).
