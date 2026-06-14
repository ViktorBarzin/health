from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    UPLOAD_DIR: str = "/data/uploads"
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000", "http://localhost:8080"]

    # Identity (ADR-0003): Authentik forward-auth injects the trusted identity
    # header at the ingress; the app trusts it verbatim. Forward-auth overwrites
    # any client-supplied X-authentik-* header, so the header is only trustworthy
    # behind that ingress.
    AUTH_EMAIL_HEADER: str = "X-authentik-email"
    # Local-dev override: when set and no AUTH_EMAIL_HEADER is present, this email
    # is used as the identity. Lets docker-compose run with no Authentik in front.
    # MUST be unset in production, where only the proxy header is trusted.
    DEV_AUTH_EMAIL: str | None = None

    # Conversational adjust provider (#14, ADR-0002 "the LLM proposes; it never
    # decides"). The default is the DETERMINISTIC, rules-based provider so the
    # "make it shorter / no barbell / I'm tired" feature works with **no external
    # service** (no ship-dark dependency). Set ADJUST_PROVIDER="claude-agent" to
    # route through the in-cluster claude-agent-service instead — the live LLM
    # path is gated OFF by default and still only PROPOSES (its output is
    # validated against Principle bounds before it's applied).
    ADJUST_PROVIDER: str = "deterministic"
    # The in-cluster claude-agent-service base URL + bearer token (Vault
    # secret/claude-agent-service), read only when ADJUST_PROVIDER="claude-agent".
    CLAUDE_AGENT_URL: str = "http://claude-agent-service.claude-agent.svc.cluster.local:8080"
    CLAUDE_AGENT_TOKEN: str | None = None
    # Hard ceiling (seconds) on a single claude-agent call so a stuck LLM never
    # blocks the gym-door request — on timeout we fall back to the deterministic
    # proposal.
    CLAUDE_AGENT_TIMEOUT_SECONDS: float = 20.0

    # Master key for encrypting per-user Connection credentials at rest (BYOT
    # integrations — connections). A user's pasted API token (e.g. an Oura
    # Personal Access Token) is NEVER stored in plaintext: it is Fernet-encrypted
    # with this key before insert and only ever decrypted in-memory at pull time.
    # The value is a URL-safe base64-encoded 32-byte key — generate one with
    # ``python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"``.
    # In production it MUST be supplied from the secret store (Vault
    # secret/health-connection-key), exactly like CLAUDE_AGENT_TOKEN — never
    # committed. To rotate, prepend a fresh key to a comma-separated list: the
    # first key encrypts new tokens, the rest still decrypt old ones (MultiFernet
    # rotation — see app.services.crypto). When unset, the Connection feature is
    # simply disabled (the API returns a clear 503) rather than storing tokens
    # unprotected — fail closed, never plaintext.
    CONNECTION_ENCRYPTION_KEY: str | None = None

    # Observability (perf-telemetry). Logs go to stdout in a logfmt-style
    # key=value format and are scraped by the cluster's Loki — so structured,
    # LogQL-parseable lines, no HTTP log shipper.
    #
    # Root log level for the app's own loggers (uvicorn's loggers are left
    # untouched). One of CRITICAL/ERROR/WARNING/INFO/DEBUG.
    LOG_LEVEL: str = "INFO"
    # Any SQL statement whose execution exceeds this many milliseconds is logged
    # once (on the ``app.slow_query`` logger) with its elapsed time and the
    # (truncated) statement, so a slow query is visible in prod without turning
    # on full SQL echo. Set <= 0 to log every statement (useful when debugging).
    SLOW_QUERY_MS: int = 200

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()  # type: ignore[call-arg]
