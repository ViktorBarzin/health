"""Tests for the /api/import endpoints."""

import io

import pytest


async def test_upload_bad_extension_returns_400(authenticated_client):
    """Uploading a file with an unsupported extension returns 400."""
    resp = await authenticated_client.post(
        "/api/import/upload",
        files={"file": ("data.csv", io.BytesIO(b"col1,col2\n1,2"), "text/csv")},
    )
    assert resp.status_code == 400
    assert "Unsupported file type" in resp.json()["detail"]


async def test_upload_without_auth_returns_401(client):
    """Uploading without authentication returns 401."""
    resp = await client.post(
        "/api/import/upload",
        files={"file": ("export.xml", io.BytesIO(b"<HealthData/>"), "text/xml")},
    )
    assert resp.status_code == 401
