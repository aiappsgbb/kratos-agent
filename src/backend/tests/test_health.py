"""Tests for health endpoints."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client without lifespan (no Azure dependencies)."""
    from unittest.mock import MagicMock

    from app.main import app

    # Mock the lifespan dependencies
    app.state.cosmos_service = MagicMock()
    app.state.skill_registry = MagicMock()
    app.state.copilot_agent = MagicMock()

    return TestClient(app, raise_server_exceptions=False)


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "kratos-agent-service"


def test_readiness_check(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
