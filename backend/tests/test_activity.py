"""Tests for the /api/activity endpoints."""

import pytest


async def test_activity_rings_empty_db(authenticated_client):
    """Activity rings endpoint returns empty list when the DB has no data."""
    resp = await authenticated_client.get("/api/activity/rings")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_activity_rings_without_auth_returns_401(client):
    """Activity rings without authentication returns 401."""
    resp = await client.get("/api/activity/rings")
    assert resp.status_code == 401
