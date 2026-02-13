"""Tests for the /api/health endpoint."""

import pytest


async def test_health_check_returns_ok(client):
    """GET /api/health returns 200 with {"status": "ok"}."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
