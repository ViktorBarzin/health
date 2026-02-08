#!/bin/sh
set -e

# Run database migrations
cd /app/backend
alembic upgrade head

# Start frontend
cd /app/frontend
node build &

# Start backend
cd /app/backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 &

# Start Caddy (foreground — PID 1 signal handling)
exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
