# Stage 1: Build frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ .
RUN npm run build

# Stage 2: Final image
FROM python:3.12-slim

# Install Node.js, Caddy, and build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2-dev libxslt1-dev gcc \
    curl debian-keyring debian-archive-keyring apt-transport-https gpg && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | \
      gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg && \
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | \
      tee /etc/apt/sources.list.d/caddy-stable.list && \
    apt-get update && apt-get install -y --no-install-recommends caddy && \
    apt-get purge -y --auto-remove curl gpg debian-keyring debian-archive-keyring apt-transport-https && \
    rm -rf /var/lib/apt/lists/*

# Install backend Python dependencies
WORKDIR /app/backend
COPY backend/pyproject.toml .
RUN pip install --no-cache-dir .

# Copy backend source
COPY backend/alembic.ini .
COPY backend/alembic/ alembic/
COPY backend/app/ app/

# Copy frontend build
COPY --from=frontend-builder /app/build /app/frontend/build
COPY --from=frontend-builder /app/package.json /app/frontend/
COPY --from=frontend-builder /app/node_modules /app/frontend/node_modules

# Copy Caddyfile for container (uses localhost)
COPY Caddyfile.container /etc/caddy/Caddyfile

# Copy entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80

CMD ["/entrypoint.sh"]
