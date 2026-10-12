"""Presigned upload flow: POST /uploads -> PUT -> completar -> job -> GET /trabajos."""

from __future__ import annotations

import hashlib
import json
import urllib.request
import uuid

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app.main import app
from app.services import jobs
from app.services.extract import ExtractionResult, PageExtraction
from app.services.storage import S3Storage
from tests.test_jobs import _pdf_bytes, needs_mongo

client = TestClient(app)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _png(label: str) -> bytes:
    from io import BytesIO

    from PIL import Image, ImageDraw

    image = Image.new("RGB", (200, 100), "white")
    ImageDraw.Draw(image).text((10, 40), label, fill="black")
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _file(nombre: str, data: bytes, tipo: str) -> dict:
    return {"nombre": nombre, "tipo_contenido": tipo, "tamano": len(data), "sha256": _sha(data)}


@pytest.fixture
def s3(monkeypatch):
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="biblioteca")
        storage = S3Storage(endpoint_url=None, access_key_id="x", secret_access_key="x",
                            bucket="biblioteca", region="us-east-1")
        monkeypatch.setattr("app.services.storage.get_storage", lambda: storage)
        yield storage


@pytest.fixture
def queue():
    from app.db import ensure_indexes, get_db

    ensure_indexes()
    get_db()["trabajos"].delete_many({})
    yield


@pytest.mark.parametrize(("archivos", "status"), [
    ([{"nombre": "a.exe", "tipo_contenido": "application/x-msdownload", "tamano": 3, "sha256": "a" * 64}], 422),
    ([{"nombre": "a.pdf", "tipo_contenido": "application/pdf", "tamano": 10**12, "sha256": "a" * 64}], 413),
    ([{"nombre": f"{i}.pdf", "tipo_contenido": "application/pdf", "tamano": 50_000_000, "sha256": "a" * 64}
      for i in range(3)], 413),
    ([{"nombre": "a.pdf", "tipo_contenido": "application/pdf", "tamano": 3, "sha256": "a" * 64},
      {"nombre": "b.png", "tipo_contenido": "image/png", "tamano": 3, "sha256": "b" * 64}], 422),
    ([{"nombre": "a.pdf", "tipo_contenido": "application/pdf", "tamano": 3, "sha256": "nope"}], 422),
    ([], 422),
])
def test_create_upload_validates_types_and_sizes(archivos, status) -> None:
    response = client.post("/api/v1/uploads", json={"archivos": archivos})
    assert response.status_code == status, response.text


def test_unknown_job_is_404() -> None:
    assert client.get("/api/v1/trabajos/no-es-un-id").status_code == 404


@needs_mongo
def test_text_upload_full_flow_and_idempotency(queue, s3) -> None:
    data = "Página uno.\fPágina dos.".encode()
    body = {"archivos": [_file("sermon.txt", data, "text/plain")], "metadatos": {"titulo": "Sermón"}}
    created = client.post("/api/v1/uploads", json=body)
    assert created.status_code == 201, created.text
    upload = created.json()
    assert upload["existente"] is False and upload["expira_en"]
    target = upload["archivos"][0]
    assert target["metodo"] == "PUT" and "X-Amz-Signature" in target["url"]
    assert target["encabezados"] == {"Content-Type": "text/plain"}
    assert target["clave"].startswith(upload["libro_id"] + "/")
    assert upload["libro_id"].startswith("sermon-")

    # Same bytes before completing: same upload id, fresh URLs (no duplicate).
    again = client.post("/api/v1/uploads", json=body).json()
    assert again["id"] == upload["id"] and again["archivos"]

    missing = client.post(f"/api/v1/uploads/{upload['id']}/completar")
    assert missing.status_code == 409

    s3.put(target["clave"], data, "text/plain")
    done = client.post(f"/api/v1/uploads/{upload['id']}/completar")
    assert done.status_code == 202, done.text
    assert done.json() == {"trabajo_id": upload["id"], "estado": "pendiente"}
    assert client.post(f"/api/v1/uploads/{upload['id']}/completar").json()["trabajo_id"] == upload["id"]

    status = client.get(f"/api/v1/trabajos/{upload['id']}").json()
    assert status["estado"] == "pendiente" and status["libro_id"] is None

    assert jobs.run_once("w-test") is True
    status = client.get(f"/api/v1/trabajos/{upload['id']}").json()
    assert status["estado"] == "completado"
    assert status["libro_id"] == upload["libro_id"]
    assert status["progreso"] == {"paginas_hechas": 2, "paginas_total": 2}
    assert "error_interno" not in status and "worker_id" not in status

    dup = client.post("/api/v1/uploads", json=body)
    assert dup.status_code == 200
    assert dup.json()["existente"] is True and dup.json()["libro_id"] == upload["libro_id"]
    assert dup.json()["archivos"] == []


@needs_mongo
def test_complete_rejects_size_mismatch(queue, s3) -> None:
    data = b"contenido"
    upload = client.post("/api/v1/uploads", json={"archivos": [_file("x.txt", data, "text/plain")]}).json()
    s3.put(upload["archivos"][0]["clave"], data + b"extra", "text/plain")
    response = client.post(f"/api/v1/uploads/{upload['id']}/completar")
    assert response.status_code == 409 and "tamaño" in response.json()["detail"]


@needs_mongo
def test_multi_image_upload_is_one_book_in_given_order(queue, s3, monkeypatch) -> None:
    from app.db import pages_collection
    from app.services import ingest

    monkeypatch.setattr(ingest, "_require_ocr_if_needed", lambda *, needs_ocr: None)
    monkeypatch.setattr(ingest, "extract_from_images", lambda paths: ExtractionResult(
        fuente="imagenes", motor="mistral", modelo="fake",
        paginas=[PageExtraction(numero=1, texto=f"texto de {paths[0].name}", ocr_confianza=0.9, motor="mistral")]))

    images = {name: _png(name) for name in ("z-portada.png", "a-capitulo.png")}
    body = {"archivos": [_file(n, d, "image/png") for n, d in images.items()]}
    upload = client.post("/api/v1/uploads", json=body).json()
    for target, data in zip(upload["archivos"], images.values()):
        s3.put(target["clave"], data, "image/png")
    assert client.post(f"/api/v1/uploads/{upload['id']}/completar").status_code == 202
    jobs.run_once("w-test")
    assert jobs.get_job(upload["id"])["estado"] == "completado"
    pages = list(pages_collection().find({"libro_id": upload["libro_id"]}).sort("numero", 1))
    assert ["z-portada" in pages[0]["texto"], "a-capitulo" in pages[1]["texto"]] == [True, True]
    assert pages[0]["ocr_confianza"] == 0.9


def _seaweed_up() -> bool:
    try:
        urllib.request.urlopen("http://localhost:9000", timeout=1)
    except urllib.error.HTTPError:
        return True
    except Exception:  # noqa: BLE001
        return False
    return True


@needs_mongo
@pytest.mark.skipif(not _seaweed_up(), reason="local S3 (SeaweedFS) not reachable on :9000")
def test_pdf_end_to_end_against_local_mongo_and_seaweedfs(queue, monkeypatch) -> None:
    """Real presigned PUT to SeaweedFS, real job run, digital PDF (no Mistral)."""
    from app.db import books_collection, pages_collection

    storage = S3Storage(endpoint_url="http://localhost:9000", access_key_id="any",
                        secret_access_key="any", bucket="biblioteca", region="auto")
    monkeypatch.setattr("app.services.storage.get_storage", lambda: storage)
    data = _pdf_bytes(2)
    titulo = f"e2e {uuid.uuid4().hex[:6]}"
    upload = client.post("/api/v1/uploads", json={
        "archivos": [_file("e2e.pdf", data, "application/pdf")], "metadatos": {"titulo": titulo}}).json()
    try:
        target = upload["archivos"][0]
        put = urllib.request.Request(target["url"], data=data, method="PUT", headers=target["encabezados"])
        urllib.request.urlopen(put, timeout=10)
        assert client.post(f"/api/v1/uploads/{upload['id']}/completar").status_code == 202
        assert jobs.run_once("w-e2e") is True
        status = client.get(f"/api/v1/trabajos/{upload['id']}").json()
        assert status["estado"] == "completado", status
        book = books_collection().find_one({"libro_id": upload["libro_id"]})
        assert book["metadatos"]["titulo"] == titulo and book["conteo_paginas"] == 2
        pages = list(pages_collection().find({"libro_id": upload["libro_id"]}).sort("numero", 1))
        assert all(storage.get(p["imagen_url"])[:4] == b"\x89PNG" for p in pages)
        assert storage.get(target["clave"]) == data  # original kept
    finally:
        storage.delete_prefix(f"{upload['libro_id']}/")


def test_upload_body_is_json_only() -> None:
    response = client.post("/api/v1/uploads", content=json.dumps({"archivos": "x"}),
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 422


@needs_mongo
def test_local_storage_501_leaves_no_orphan_job(queue) -> None:
    from app.db import jobs_collection

    data = b"sin s3"
    response = client.post("/api/v1/uploads", json={"archivos": [_file("l.txt", data, "text/plain")]})
    assert response.status_code == 501
    assert jobs_collection().count_documents({"sha256": _sha(data)}) == 0


@needs_mongo
def test_failed_upload_is_reopened_for_the_same_bytes(queue, s3) -> None:
    from app.db import jobs_collection

    body = {"archivos": [_file("f.txt", b"fallo", "text/plain")], "metadatos": {"titulo": "Nuevo"}}
    upload = client.post("/api/v1/uploads", json=body).json()
    jobs_collection().update_one({}, {"$set": {"estado": "fallido", "intentos": 5, "error": "x"}})
    again = client.post("/api/v1/uploads", json=body)
    assert again.status_code == 201
    assert again.json()["id"] == upload["id"] and again.json()["archivos"]
    doc = jobs.get_job(upload["id"])
    assert (doc["estado"], doc["intentos"], doc["error"], doc["metadatos"]) == ("esperando_subida", 0, None, {"titulo": "Nuevo"})


def _status(job_id: str) -> dict:
    return client.get(f"/api/v1/trabajos/{job_id}").json()


@needs_mongo
def test_multi_document_upload_creates_one_job_per_file(queue, s3) -> None:
    a, b = _pdf_bytes(1), _pdf_bytes(2)
    body = {"archivos": [{**_file("mi_libro-uno.pdf", a, "application/pdf")},
                         {**_file("dos.pdf", b, "application/pdf"), "titulo": "Libro Dos"}],
            "metadatos": {"autor": "Agustín"}}
    created = client.post("/api/v1/uploads", json=body)
    assert created.status_code == 201, created.text
    upload = created.json()
    trabajos = upload["trabajos"]
    assert [t["titulo"] for t in trabajos] == ["mi libro uno", "Libro Dos"]
    assert len({t["id"] for t in trabajos}) == 2 and len({t["libro_id"] for t in trabajos}) == 2
    assert all(t["existente"] is False and len(t["archivos"]) == 1 for t in trabajos)
    assert upload["id"] == trabajos[0]["id"] and upload["archivos"] == trabajos[0]["archivos"]
    status = _status(trabajos[1]["id"])
    assert (status["etapa"], status["titulo"]) == ("subiendo", "Libro Dos")
    assert jobs.get_job(trabajos[1]["id"])["metadatos"] == {"autor": "Agustín", "titulo": "Libro Dos"}

    again = client.post("/api/v1/uploads", json=body).json()
    assert [t["id"] for t in again["trabajos"]] == [t["id"] for t in trabajos]


def test_mixed_images_and_documents_are_rejected() -> None:
    body = {"archivos": [_file("a.pdf", b"x", "application/pdf"), _file("b.png", b"y", "image/png")]}
    response = client.post("/api/v1/uploads", json=body)
    assert response.status_code == 422 and "imágenes" in response.json()["detail"]


@needs_mongo
def test_job_etapa_follows_the_worker(queue, s3, monkeypatch) -> None:
    from app.services import ingest

    data = "uno\fdos".encode()
    upload = client.post("/api/v1/uploads", json={"archivos": [_file("e.txt", data, "text/plain")]}).json()
    assert _status(upload["id"])["etapa"] == "subiendo"
    s3.put(upload["archivos"][0]["clave"], data, "text/plain")
    client.post(f"/api/v1/uploads/{upload['id']}/completar")
    assert _status(upload["id"])["etapa"] == "en_espera"

    seen = []
    persist = ingest._persist
    monkeypatch.setattr(ingest, "_persist", lambda *a, **k: (seen.append(_status(upload["id"])["etapa"]),
                                                               persist(*a, **k)))
    jobs.run_once("w-etapa")
    assert seen == ["preparando_busqueda"]
    status = _status(upload["id"])
    assert (status["etapa"], status["libro_id"], status["titulo"]) == ("disponible", upload["libro_id"], "e")


@needs_mongo
def test_etapa_for_failures_and_old_jobs(queue, s3) -> None:
    from app.db import jobs_collection

    upload = client.post("/api/v1/uploads", json={"archivos": [_file("v.txt", b"v", "text/plain")]}).json()
    job = jobs_collection().find_one_and_update({}, {"$set": {"estado": "procesando", "worker_id": "w", "intentos": 1}},
                                                return_document=True)
    jobs.fail(job, ValueError("boom"))
    assert _status(upload["id"])["etapa"] == "en_espera"
    jobs_collection().update_one({}, {"$set": {"estado": "procesando"}})
    jobs.fail({**job, "intentos": 5}, jobs.PermanentJobError("Archivo dañado."))
    assert (_status(upload["id"])["etapa"], _status(upload["id"])["error"]) == ("fallido", "Archivo dañado.")
    jobs_collection().update_one({}, {"$unset": {"etapa": ""}, "$set": {"estado": "procesando"}})
    assert _status(upload["id"])["etapa"] == "leyendo_paginas"


@needs_mongo
def test_list_recent_jobs_by_owner(queue, s3) -> None:
    from app.security import require_editor

    for i in range(3):
        client.post("/api/v1/uploads", json={"archivos": [_file(f"l{i}.txt", f"t{i}".encode(), "text/plain")]})
    listed = client.get("/api/v1/trabajos?limit=2")
    assert listed.status_code == 200
    assert [t["titulo"] for t in listed.json()] == ["l2", "l1"]
    assert set(listed.json()[0]) >= {"id", "etapa", "titulo", "creado_en"} and "archivos" not in listed.json()[0]

    app.dependency_overrides[require_editor] = lambda: {"email": "otra@x.org", "rol": "editor"}
    try:
        assert client.get("/api/v1/trabajos").json() == []
    finally:
        app.dependency_overrides.clear()
