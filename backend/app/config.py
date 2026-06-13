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

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()  # type: ignore[call-arg]
