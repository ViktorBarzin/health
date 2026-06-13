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

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()  # type: ignore[call-arg]
