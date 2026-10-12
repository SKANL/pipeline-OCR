"""Mongo job queue: claim/lease, retries with backoff, checkpoints, worker."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from moto import mock_aws
from pymongo import MongoClient

from app.config import get_settings
from app.services import jobs
from app.services.storage import S3Storage


def _mongo_available() -> bool:
    try:
        client = MongoClient(get_settings().mongodb_uri, serverSelectionTimeoutMS=1000)
        client.admin.command("ping")
        return True
    except Exception:  # noqa: BLE001
        return False


needs_mongo = pytest.mark.skipif(not _mongo_available(), reason="MongoDB no está accesible en MONGODB_URI")


def test_backoff_grows_with_jitter_and_is_capped() -> None:
    first = [jobs.backoff_seconds(1) for _ in range(50)]
    assert all(jobs.BACKOFF_BASE <= s <= 2 * jobs.BACKOFF_BASE for s in first)
    assert len(set(first)) > 1  # jitter
    assert all(jobs.backoff_seconds(3) >= 4 * jobs.BACKOFF_BASE for _ in range(10))
    assert all(jobs.backoff_seconds(30) <= jobs.BACKOFF_CAP for _ in range(10))


def test_upload_digest_depends_on_content_and_order() -> None:
    a, b = "a" * 64, "b" * 64
    assert jobs.upload_digest([a, b]) == jobs.upload_digest([a, b])
    assert jobs.upload_digest([a, b]) != jobs.upload_digest([b, a])
    assert jobs.upload_digest([a]) == a  # single file: its own sha256


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def queue():
    from app.db import ensure_indexes, get_db

    ensure_indexes()
    get_db()["trabajos"].delete_many({})
    get_db()["trabajo_paginas"].delete_many({})
    yield get_db()["trabajos"]
    get_db()["trabajos"].delete_many({})


@pytest.fixture
def s3(monkeypatch):
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="biblioteca")
        storage = S3Storage(endpoint_url=None, access_key_id="x", secret_access_key="x",
                            bucket="biblioteca", region="us-east-1")
        monkeypatch.setattr("app.services.storage.get_storage", lambda: storage)
        yield storage


def _txt_job(storage, text: bytes, libro_id: str = "libro-cola") -> str:
    key = f"{libro_id}/000-texto.txt"
    storage.put(key, text, "text/plain")
    archivo = {"nombre": "texto.txt", "tipo_contenido": "text/plain", "tamano": len(text),
               "sha256": _sha(text), "clave": key}
    return jobs.create_job(libro_id=libro_id, archivos=[archivo], metadatos={"titulo": "Cola"},
                           estado="pendiente")


@needs_mongo
def test_claim_is_atomic_and_sets_lease(queue, s3) -> None:
    job_id = _txt_job(s3, b"uno")
    job = jobs.claim("w1")
    assert job["_id"] == job_id or str(job["_id"]) == job_id
    assert job["estado"] == "procesando" and job["intentos"] == 1 and job["worker_id"] == "w1"
    assert job["bloqueado_hasta"] > datetime.now(timezone.utc).replace(tzinfo=None)
    assert jobs.claim("w2") is None  # leased


@needs_mongo
def test_expired_lease_is_reclaimed_by_another_worker(queue, s3) -> None:
    _txt_job(s3, b"uno")
    job = jobs.claim("w1")
    queue.update_one({"_id": job["_id"]}, {"$set": {"bloqueado_hasta": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    again = jobs.claim("w2")
    assert again["_id"] == job["_id"] and again["worker_id"] == "w2" and again["intentos"] == 2
    with pytest.raises(jobs.LeaseLost):
        jobs.heartbeat(job, paginas_hechas=1, paginas_total=1)  # w1 lost it


@needs_mongo
def test_failure_backs_off_then_fails_after_max_attempts(queue, s3) -> None:
    _txt_job(s3, b"uno")
    job = jobs.claim("w1")
    jobs.fail(job, RuntimeError("boom secreto"))
    doc = queue.find_one({"_id": job["_id"]})
    assert doc["estado"] == "pendiente"
    assert doc["disponible_desde"] > datetime.now(timezone.utc).replace(tzinfo=None)
    assert jobs.claim("w1") is None  # backing off
    queue.update_one({"_id": job["_id"]}, {"$set": {"intentos": doc["max_intentos"] - 1, "disponible_desde": datetime.now(timezone.utc)}})
    job = jobs.claim("w1")
    jobs.fail(job, RuntimeError("boom secreto"))
    doc = queue.find_one({"_id": job["_id"]})
    assert doc["estado"] == "fallido"
    assert "secreto" not in doc["error"]  # public message hides internals
    assert "boom secreto" in doc["error_interno"]


@needs_mongo
def test_permanent_error_fails_immediately(queue, s3) -> None:
    _txt_job(s3, b"uno")
    job = jobs.claim("w1")
    jobs.fail(job, jobs.PermanentJobError("Tipo no soportado."))
    doc = queue.find_one({"_id": job["_id"]})
    assert doc["estado"] == "fallido" and doc["error"] == "Tipo no soportado."


@needs_mongo
def test_plain_value_error_is_retried_not_permanent(queue, s3) -> None:
    _txt_job(s3, b"uno")
    job = jobs.claim("w1")
    jobs.fail(job, ValueError("glitch en una libreria"))
    doc = queue.find_one({"_id": job["_id"]})
    assert doc["estado"] == "pendiente" and "glitch" not in doc["error"]


@needs_mongo
def test_lease_lost_before_finalize_does_not_persist(queue, s3, monkeypatch) -> None:
    from app.db import books_collection
    from app.services import ingest

    books_collection().delete_many({"libro_id": "libro-cola"})
    job_id = _txt_job(s3, b"uno")
    real = ingest._assemble_libro

    def steal(**kwargs):
        queue.update_one({}, {"$set": {"worker_id": "w-otro"}})
        return real(**kwargs)

    monkeypatch.setattr(ingest, "_assemble_libro", steal)
    jobs.run_once("w1")
    assert books_collection().find_one({"libro_id": "libro-cola"}) is None
    assert jobs.get_job(job_id)["worker_id"] == "w-otro"


@needs_mongo
def test_complete_raises_when_lease_lost(queue, s3) -> None:
    _txt_job(s3, b"uno")
    job = jobs.claim("w1")
    queue.update_one({"_id": job["_id"]}, {"$set": {"worker_id": "w2"}})
    with pytest.raises(jobs.LeaseLost):
        jobs.complete(job, paginas=1)


@needs_mongo
def test_crashed_job_with_no_attempts_left_is_swept_to_failed(queue, s3) -> None:
    _txt_job(s3, b"uno")
    job = jobs.claim("w1")
    queue.update_one({"_id": job["_id"]}, {"$set": {
        "intentos": job["max_intentos"], "bloqueado_hasta": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    assert jobs.run_once("w2") is False
    assert queue.find_one({"_id": job["_id"]})["estado"] == "fallido"


@needs_mongo
def test_run_once_processes_text_job_into_book(queue, s3) -> None:
    from app.db import books_collection, pages_collection

    job_id = _txt_job(s3, "Primera página de gracia.\fSegunda página de fe.".encode())
    assert jobs.run_once("w1") is True
    doc = jobs.get_job(job_id)
    assert doc["estado"] == "completado"
    assert doc["progreso"] == {"paginas_hechas": 2, "paginas_total": 2}
    book = books_collection().find_one({"libro_id": "libro-cola"})
    assert book["conteo_paginas"] == 2 and book["procedencia"]["fuente"] == "texto"
    assert pages_collection().count_documents({"libro_id": "libro-cola"}) == 2
    assert s3.get("libro-cola/000-texto.txt")  # original survives pruning


@needs_mongo
def test_sha_mismatch_fails_permanently(queue, s3) -> None:
    job_id = _txt_job(s3, b"uno")
    s3.put("libro-cola/000-texto.txt", b"otro contenido", "text/plain")
    jobs.run_once("w1")
    doc = jobs.get_job(job_id)
    assert doc["estado"] == "fallido" and "sha256" in doc["error"]


def _pdf_bytes(pages: int) -> bytes:
    from io import BytesIO

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    for index in range(1, pages + 1):
        c.setFont("Helvetica", 13)
        c.drawString(72, 750, f"Pagina {index}: la gracia soberana sostiene al creyente.")
        c.showPage()
    c.save()
    return buffer.getvalue()


@needs_mongo
def test_pdf_job_resumes_from_checkpoint_without_redoing_pages(queue, s3, monkeypatch) -> None:
    from app.db import pages_collection
    from app.services import ingest

    data = _pdf_bytes(3)
    key = "libro-pdf/000-libro.pdf"
    s3.put(key, data, "application/pdf")
    job_id = jobs.create_job(libro_id="libro-pdf", metadatos={}, estado="pendiente", archivos=[
        {"nombre": "libro.pdf", "tipo_contenido": "application/pdf", "tamano": len(data),
         "sha256": _sha(data), "clave": key}])

    real = ingest._extract_pdf_source
    calls: list[int] = []

    def flaky(paths, libro_id, capitulos, storage, first_page=1):
        calls.append(first_page)
        if first_page == 2 and calls.count(2) == 1:
            raise RuntimeError("render crashed")
        return real(paths, libro_id, capitulos, storage, first_page=first_page)

    monkeypatch.setattr(ingest, "_extract_pdf_source", flaky)
    jobs.run_once("w1")
    doc = jobs.get_job(job_id)
    assert doc["estado"] == "pendiente" and doc["progreso"]["paginas_hechas"] == 1
    queue.update_one({"_id": doc["_id"]}, {"$set": {"disponible_desde": datetime.now(timezone.utc)}})
    jobs.run_once("w1")
    assert jobs.get_job(job_id)["estado"] == "completado"
    assert calls == [1, 2, 2, 3]  # page 1 was not redone
    pages = list(pages_collection().find({"libro_id": "libro-pdf"}).sort("numero", 1))
    assert [p["numero"] for p in pages] == [1, 2, 3]
    assert [p["imagen_url"] for p in pages] == [f"libro-pdf/paginas/{n}.png" for n in (1, 2, 3)]
    assert "Pagina 3" in pages[2]["texto"]


def test_worker_stops_cleanly(monkeypatch) -> None:
    monkeypatch.setattr(jobs, "run_once", lambda worker_id: False)
    worker = jobs.Worker()
    worker.start()
    worker.stop()
    assert not worker.thread.is_alive()
