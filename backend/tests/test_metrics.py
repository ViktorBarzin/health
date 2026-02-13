"""Tests for the /api/metrics endpoints."""

import pytest


async def test_available_metrics_empty_db(authenticated_client):
    """Available metrics returns empty list when the DB has no data."""
    resp = await authenticated_client.get("/api/metrics/available")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_available_metrics_without_auth_returns_401(client):
    """Available metrics without authentication returns 401."""
    resp = await client.get("/api/metrics/available")
    assert resp.status_code == 401
