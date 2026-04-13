import os


os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://health:test@localhost:5432/apple_health")
os.environ.setdefault("SECRET_KEY", "test-secret")
