"""Tests for the /api/workouts endpoints."""

import pytest


async def test_list_workouts_empty_db(authenticated_client):
    """Listing workouts with no data returns an empty list."""
    resp = await authenticated_client.get("/api/workouts/")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_workouts_without_auth_returns_401(client):
    """Listing workouts without authentication returns 401."""
    resp = await client.get("/api/workouts/")
    assert resp.status_code == 401
