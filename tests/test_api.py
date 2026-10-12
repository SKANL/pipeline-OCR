"""Tests de la API que no requieren MongoDB."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_lists_endpoints() -> None:
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/api/v1/ingest" in paths
    assert "/api/v1/ingest/upload" in paths
    assert "/api/v1/search" in paths
    assert "/api/v1/books" in paths
    assert "/api/v1/facets" in paths
    assert "/api/v1/books/{libro_id}" in paths
    assert "/api/v1/books/{libro_id}/paginas" in paths
    assert "/api/v1/ref/{libro_id}/pagina/{numero}" in paths
    assert "/api/v1/pages/{libro_id}/pagina/{numero}/imagen" in paths
    assert "/api/v1/cite/{libro_id}/pagina/{numero}" in paths
