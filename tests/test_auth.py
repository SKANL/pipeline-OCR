"""Editor auth: PWA-minted HS256 bearer token, editores collection, API key for ops."""

from __future__ import annotations

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.test_jobs import needs_mongo, s3  # noqa: F401 - fixture

client = TestClient(app)
SECRET = "s" * 40


def token(email: str = "ana@example.com", *, secret: str = SECRET, ttl: int = 300, **overrides) -> str:
    now = int(time.time())
    claims = {"sub": email, "email": email, "iat": now, "exp": now + ttl,
              "iss": "biblioteca-web", "aud": "biblioteca-api", **overrides}
    return jwt.encode(claims, secret, algorithm="HS256")


def bearer(value: str) -> dict:
    return {"Authorization": f"Bearer {value}"}


@pytest.fixture
def auth(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", SECRET)
    monkeypatch.setenv("ADMIN_EMAILS", "Boss@Example.com")
    monkeypatch.setenv("API_KEY", "ops-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def editores():
    from app.db import get_db

    get_db()["editores"].delete_many({})
    yield get_db()["editores"]
    get_db()["editores"].delete_many({})


def test_yo_requires_bearer(auth) -> None:
    assert client.get("/api/v1/yo").status_code == 401
    assert client.get("/api/v1/yo", headers={"X-API-Key": "ops-key"}).status_code == 401


@pytest.mark.parametrize("bad", [
    token(secret="otro" * 10),
    token(ttl=-120),  # expired beyond leeway
    token(iss="otro"),
    token(aud="otra-api"),
    token(ttl=3600),  # lifetime above 10 minutes
    "no-es-un-jwt",
])
def test_invalid_tokens_are_401(auth, bad) -> None:
    assert client.get("/api/v1/yo", headers=bearer(bad)).status_code == 401


def test_bootstrap_admin_case_insensitive_without_db(auth) -> None:
    response = client.get("/api/v1/yo", headers=bearer(token("boss@example.COM")))
    assert response.status_code == 200
    assert response.json() == {"email": "boss@example.com", "rol": "admin"}


@needs_mongo
def test_non_editor_token_is_403_on_writes(auth, editores) -> None:
    assert client.get("/api/v1/yo", headers=bearer(token())).json() == {"email": "ana@example.com", "rol": None}
    response = client.post("/api/v1/uploads", json={"archivos": []}, headers=bearer(token()))
    assert response.status_code == 403


def test_writes_need_credentials_when_configured(auth) -> None:
    assert client.post("/api/v1/uploads", json={"archivos": []}).status_code == 401
    # Ops key still works (422 = got past auth into validation).
    assert client.post("/api/v1/uploads", json={"archivos": []}, headers={"X-API-Key": "ops-key"}).status_code == 422
    admin = bearer(token("boss@example.com"))
    assert client.post("/api/v1/uploads", json={"archivos": []}, headers=admin).status_code == 422


@needs_mongo
def test_admin_manages_editors(auth, editores) -> None:
    admin = bearer(token("boss@example.com"))
    ana = bearer(token("ana@example.com"))
    assert client.get("/api/v1/editores", headers=ana).status_code == 403

    created = client.post("/api/v1/editores", json={"email": "Ana@Example.com", "rol": "editor"}, headers=admin)
    assert created.status_code == 201, created.text
    assert client.get("/api/v1/yo", headers=ana).json()["rol"] == "editor"
    listed = client.get("/api/v1/editores", headers=admin).json()
    assert [(e["email"], e["rol"]) for e in listed] == [("ana@example.com", "editor")]
    # Editors can write but cannot manage editors.
    assert client.post("/api/v1/uploads", json={"archivos": []}, headers=ana).status_code == 422
    assert client.get("/api/v1/editores", headers=ana).status_code == 403

    assert client.post("/api/v1/editores", json={"email": "x", "rol": "editor"}, headers=admin).status_code == 422
    assert client.post("/api/v1/editores", json={"email": "a@b.c", "rol": "dios"}, headers=admin).status_code == 422

    assert client.delete("/api/v1/editores/ANA@example.com", headers=admin).status_code == 204
    assert client.delete("/api/v1/editores/ana@example.com", headers=admin).status_code == 204
    assert client.get("/api/v1/yo", headers=ana).json()["rol"] is None


@needs_mongo
def test_upload_records_creado_por_on_job_and_book(auth, editores, s3) -> None:
    import hashlib

    from app.db import books_collection, jobs_collection
    from app.services import jobs

    data = b"creado por test"
    sha = hashlib.sha256(data).hexdigest()
    jobs_collection().delete_many({"sha256": sha})
    archivo = {"nombre": "c.txt", "tipo_contenido": "text/plain", "tamano": len(data), "sha256": sha}
    admin = bearer(token("boss@example.com"))
    upload = client.post("/api/v1/uploads", json={"archivos": [archivo]}, headers=admin).json()
    s3.put(upload["archivos"][0]["clave"], data, "text/plain")
    assert client.post(f"/api/v1/uploads/{upload['id']}/completar", headers=admin).status_code == 202
    assert jobs.get_job(upload["id"])["creado_por"] == "boss@example.com"
    jobs.run_once("w-auth")
    assert books_collection().find_one({"libro_id": upload["libro_id"]})["creado_por"] == "boss@example.com"


def test_dev_mode_open_when_nothing_configured(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_SECRET", "")
    monkeypatch.setenv("API_KEY", "")
    get_settings.cache_clear()
    try:
        assert client.post("/api/v1/uploads", json={"archivos": []}).status_code == 422
    finally:
        get_settings.cache_clear()


@needs_mongo
def test_server_path_ingest_is_admin_or_ops_only(auth, editores) -> None:
    editores.insert_one({"email": "ana@example.com", "rol": "editor"})
    body = {"root": "no/existe"}
    assert client.post("/api/v1/ingest", json=body, headers=bearer(token())).status_code == 403
