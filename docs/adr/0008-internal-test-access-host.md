# Internal test-access host bypasses Authentik

Status: accepted (Viktor, 2026-06-13)

The deployed app is gated by Authentik forward-auth at the ingress (`auth="required"`, ADR-0003),
which 302-redirects every request to SSO. That makes the live instance unreachable by
automated tests (Playwright/E2E), by agents diagnosing it, and for quick manual
screenshots — there is no non-interactive way in. We need testability against the *real*
deployment without weakening the public posture.

Decided: a **second ingress on the internal domain** (e.g. `health-test.viktorbarzin.lan`,
`auth="none"`, anti-AI/Anubis off) pointing at the **same** `health` deployment, plus
`DEV_AUTH_EMAIL=vbarzin@gmail.com` on the deployment. The public `health.viktorbarzin.me`
host stays Authentik-gated and unchanged.

Mechanism (why it's safe): `get_current_user` reads `X-authentik-email`, falling back to
`DEV_AUTH_EMAIL` only when the header is absent. Forward-auth **fails closed** — a request
reaching the app via the public ingress has already passed Authentik and *always* carries
the header, so the `DEV_AUTH_EMAIL` fallback is unreachable through the public host. It is
reached only via the test host (which injects no header) → that host acts as
`vbarzin@gmail.com`. The test identity is deliberately Viktor's real account so the live
data (6.6M records) is what's tested — essential for reproducing the data-volume-driven
slow load and for "seeing what we have."

## Consequences

- The test host is **unauthenticated** and serves real data. It is mitigated by being
  **internal-only** (`.lan`, not public DNS / not internet-exposed) — anyone on the LAN can
  reach it. Accepted for a homelab.
- A direct in-cluster request to the `health` Service (bypassing both ingresses) would also
  hit the `DEV_AUTH_EMAIL` identity; in-cluster traffic is trusted (NetworkPolicy can
  restrict if ever needed).
- Write-heavy automated tests should later use a **dedicated test user** (not Viktor's
  account) to keep test data out of the real dataset; read-heavy testing on real data is fine.
- Revisit if the app is ever shared beyond the household or the test host needs public reach
  (then a scoped bearer/OIDC path per TripIt ADR-0017, not an open host).
