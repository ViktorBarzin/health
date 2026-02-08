#!/bin/sh
set -e

# Run database migrations
cd /app/backend
alembic upgrade head

# Start backend in background
uvicorn app.main:app --host 127.0.0.1 --port 8000 &

# Start frontend as PID 1
cd /app/frontend
exec node build
