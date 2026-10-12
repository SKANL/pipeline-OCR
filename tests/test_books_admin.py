"""Editor book management: PATCH metadata, DELETE book, reprocess via the job queue."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services import jobs
from tests.test_jobs import _txt_job, needs_mongo, queue, s3  # noqa: F401 - fixtures

client = TestClient(app)


def _book(s3, libro_id: str = "libro-cola") -> str:
    job_id = _txt_job(s3, "Gracia uno.\fGracia dos.".encode(), libro_id=libro_id)
    assert jobs.run_once("w-books") is True
    return job_id


@needs_mongo
def test_patch_updates_book_and_page_projection(queue, s3) -> None:
    from app.db import pages_collection

    _book(s3)
    response = client.patch("/api/v1/books/libro-cola", json={
        "titulo": "Nuevo título", "autor": "Juan Calvino", "genero": "teología", "anio_publicacion": 1559})
    assert response.status_code == 200, response.text
    meta = response.json()["metadatos"]
    assert (meta["titulo"], meta["autor"], meta["anio_publicacion"]) == ("Nuevo título", "Juan Calvino", 1559)
    page = pages_collection().find_one({"libro_id": "libro-cola"})
    assert (page["titulo"], page["autor"], page["genero"]) == ("Nuevo título", "Juan Calvino", "teología")

    assert client.patch("/api/v1/books/libro-cola", json={"desconocido": 1}).status_code == 422
    assert client.patch("/api/v1/books/libro-cola", json={"titulo": None}).status_code == 422
    assert client.patch("/api/v1/books/libro-cola", json={"anio_publicacion": "x"}).status_code == 422
    assert client.patch("/api/v1/books/no-existe", json={"titulo": "x"}).status_code == 404


@needs_mongo
def test_delete_removes_book_pages_jobs_and_media_idempotently(queue, s3) -> None:
    from app.db import books_collection, job_pages_collection, pages_collection

    job_id = _book(s3)
    job_pages_collection().insert_one({"trabajo_id": jobs.get_job(job_id)["_id"], "numero": 9})
    assert client.delete("/api/v1/books/libro-cola").status_code == 204
    assert books_collection().find_one({"libro_id": "libro-cola"}) is None
    assert pages_collection().count_documents({"libro_id": "libro-cola"}) == 0
    assert jobs.get_job(job_id) is None
    assert job_pages_collection().count_documents({}) == 0
    assert s3.size("libro-cola/000-texto.txt") is None
    assert client.delete("/api/v1/books/libro-cola").status_code == 204
    assert client.delete("/api/v1/books/..%2F..").status_code in (400, 404)


@needs_mongo
def test_reprocess_requeues_with_edited_metadata_and_409_when_active(queue, s3) -> None:
    from app.db import books_collection

    job_id = _book(s3)
    client.patch("/api/v1/books/libro-cola", json={"titulo": "Editado"})
    response = client.post("/api/v1/books/libro-cola/reprocesar")
    assert response.status_code == 202, response.text
    assert response.json() == {"trabajo_id": job_id, "estado": "pendiente"}
    assert jobs.get_job(job_id).get("ocr_proveedor") is None
    assert client.post("/api/v1/books/libro-cola/reprocesar").status_code == 409
    assert jobs.run_once("w-books") is True
    assert jobs.get_job(job_id)["estado"] == "completado"
    assert books_collection().find_one({"libro_id": "libro-cola"})["metadatos"]["titulo"] == "Editado"
    assert client.post("/api/v1/books/no-existe/reprocesar").status_code == 404
    response = client.post("/api/v1/books/libro-cola/reprocesar", json={"ocr_proveedor": "glm"})
    assert response.status_code == 202, response.text
    assert jobs.get_job(job_id)["ocr_proveedor"] == "glm"
    assert client.post("/api/v1/books/libro-cola/reprocesar", json={"ocr_proveedor": "nope"}).status_code == 422


@needs_mongo
def test_delete_during_active_job_leaves_nothing_behind(queue, s3, monkeypatch) -> None:
    from app.db import books_collection, job_pages_collection, pages_collection

    job_id = _txt_job(s3, "Uno.\fDos.".encode(), libro_id="libro-borrado")
    real = jobs._extract_page

    def extract_then_delete(kind, path, local, numero, libro_id, storage, **kwargs):
        result = real(kind, path, local, numero, libro_id, storage, **kwargs)
        if numero == 1:  # the editor deletes the book while page 1 is in flight
            assert client.delete(f"/api/v1/books/{libro_id}").status_code == 204
            s3.put(f"{libro_id}/paginas/1.png", b"png", "image/png")  # media written after the delete
        return result

    monkeypatch.setattr(jobs, "_extract_page", extract_then_delete)
    assert jobs.run_once("w-del") is True
    assert jobs.get_job(job_id) is None
    assert books_collection().find_one({"libro_id": "libro-borrado"}) is None
    assert pages_collection().count_documents({"libro_id": "libro-borrado"}) == 0
    assert job_pages_collection().count_documents({}) == 0
    assert s3.size("libro-borrado/paginas/1.png") is None
