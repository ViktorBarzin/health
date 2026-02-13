"""Tests for the /api/dashboard endpoints."""

import pytest


async def test_summary_empty_db_returns_all_nulls(authenticated_client):
    """Dashboard summary with no data returns all-null metric values."""
    resp = await authenticated_client.get("/api/dashboard/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["steps_today"] is None
    assert body["active_energy_today"] is None
    assert body["exercise_minutes_today"] is None
    assert body["stand_hours_today"] is None
    assert body["resting_hr"] is None
    assert body["hrv"] is None
    assert body["spo2"] is None
    assert body["sleep_hours_last_night"] is None


async def test_summary_without_auth_returns_401(client):
    """Dashboard summary without authentication returns 401."""
    resp = await client.get("/api/dashboard/summary")
    assert resp.status_code == 401
