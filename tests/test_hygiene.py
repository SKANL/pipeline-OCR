"""Tests de higiene: API key en escrituras, path traversal y CORS.

No requieren tocar la lógica de ingesta: la API key se resuelve en la
dependencia y el path traversal se valida antes de leer de disco.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.storage import get_storage


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _mongo_available() -> bool:
    from pymongo import MongoClient

    try:
        client = MongoClient(get_settings().mongodb_uri, serverSelectionTimeoutMS=1000)
        client.admin.command("ping")
        return True
    except Exception:  # noqa: BLE001
        return False


def _set_api_key(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Fija `API_KEY` en el entorno y limpia la cache de settings."""
    monkeypatch.setenv("API_KEY", value)
    get_settings.cache_clear()


def test_upload_requires_api_key_when_configured(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    _set_api_key(monkeypatch, "secreto-123")
    try:
        sin_clave = client.post(
            "/api/v1/ingest/upload",
            files={"files": ("nota.txt", b"hola", "text/plain")},
        )
        assert sin_clave.status_code == 401
        assert "X-API-Key" in sin_clave.json()["detail"]

        con_clave = client.post(
            "/api/v1/ingest/upload",
            files={"files": ("nota.txt", b"hola", "text/plain")},
            headers={"X-API-Key": "secreto-123"},
        )
        assert con_clave.status_code != 401
    finally:
        get_settings.cache_clear()


def test_ingest_requires_api_key_when_configured(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    _set_api_key(monkeypatch, "secreto-123")
    try:
        response = client.post("/api/v1/ingest", json={"root": "tests/fixtures/generated-pdfs"})
        assert response.status_code == 401
    finally:
        get_settings.cache_clear()


def test_writes_open_when_api_key_empty(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    _set_api_key(monkeypatch, "")
    try:
        response = client.post(
            "/api/v1/ingest/upload",
            files={"files": ("nota.txt", b"hola", "text/plain")},
        )
        assert response.status_code != 401
    finally:
        get_settings.cache_clear()


def test_storage_path_refuses_escape() -> None:
    storage = get_storage()
    with pytest.raises(ValueError):
        storage.path("../../etc/passwd")
    with pytest.raises(ValueError):
        storage.path("../fuera.png")
    # Un camino normal sigue funcionando.
    assert storage.path("libro-x/paginas/1.png").name == "1.png"


def test_page_image_rejects_bad_libro_id(client: TestClient) -> None:
    assert client.get("/api/v1/pages/Bad_ID/pagina/1/imagen").status_code == 400


def test_page_image_rejects_bad_numero(client: TestClient) -> None:
    assert client.get("/api/v1/pages/libro-x/pagina/0/imagen").status_code == 400


@pytest.mark.skipif(not _mongo_available(), reason="MongoDB no accesible en MONGODB_URI")
def test_page_image_blocks_traversal(client: TestClient) -> None:
    from app.db import pages_collection

    pages = pages_collection()
    ref = "traversal/pagina/1"
    pages.delete_one({"ref": ref})
    pages.insert_one(
        {
            "ref": ref,
            "libro_id": "traversal",
            "numero": 1,
            "imagen_url": "/media/../../../../etc/passwd",
        }
    )
    try:
        response = client.get("/api/v1/pages/traversal/pagina/1/imagen")
        assert response.status_code == 404
    finally:
        pages.delete_one({"ref": ref})


def test_cors_preflight_allows_configured_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/search",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_default_allows_pwa_port(client: TestClient) -> None:
    response = client.options(
        "/api/v1/search",
        headers={
            "Origin": "http://localhost:3010",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3010"


@pytest.mark.parametrize("root", ["no/existe/jamas", "pyproject.toml"])
def test_ingest_rejects_bad_root(client: TestClient, root: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INGEST_ALLOWED_ROOTS", str(Path.cwd().resolve()))
    get_settings.cache_clear()
    response = client.post("/api/v1/ingest", json={"root": root})
    assert response.status_code == 400
    get_settings.cache_clear()
    assert "raíz" in response.json()["detail"]


def test_empty_env_values_fall_back_to_defaults(monkeypatch) -> None:
    from app.config import Settings

    monkeypatch.setenv("MAX_FILE_BYTES", "")
    monkeypatch.setenv("PAGE_IMAGE_DPI", "")
    settings = Settings()
    assert settings.max_file_bytes > 0 and settings.page_image_dpi > 0
