"""Test de la subida multipart: PDF de texto -> libro indexado y buscable."""

from __future__ import annotations

import json
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

from app.config import get_settings
from app.main import app


def _mongo_available() -> bool:
    try:
        client = MongoClient(get_settings().mongodb_uri, serverSelectionTimeoutMS=1000)
        client.admin.command("ping")
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(
    not _mongo_available(), reason="MongoDB no está accesible en MONGODB_URI"
)


def _text_pdf_bytes() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    for index in range(1, 4):
        c.setFont("Helvetica", 13)
        c.drawString(72, 750, f"Pagina {index}: la gracia soberana sostiene al creyente.")
        c.showPage()
    c.save()
    return buffer.getvalue()


def test_upload_text_pdf_indexes_and_searches() -> None:
    from app.db import books_collection, ensure_indexes, pages_collection

    ensure_indexes()
    client = TestClient(app)

    response = client.post(
        "/api/v1/ingest/upload",
        files=[("files", ("manual.pdf", _text_pdf_bytes(), "application/pdf"))],
        data={
            "libro_id": "subida-digital",
            "metadatos": json.dumps({"titulo": "Manual de Prueba", "autor": "Autor X", "genero": "teologia"}),
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["libro_id"] == "subida-digital"
    assert body["books"] == 1
    assert body["pages"] == 3
    assert body["fuente"] == "pdf_digital"

    book = books_collection().find_one({"libro_id": "subida-digital"})
    assert book is not None
    assert book["procedencia"]["fuente"] == "pdf_digital"
    assert book["procedencia"]["ocr"]["motor"] is None
    assert book["origen"] == ["manual.pdf"]
    assert book["conteo_paginas"] == 3
    assert book["estado_ingesta"] == "indexed"

    pages = list(pages_collection().find({"libro_id": "subida-digital"}).sort("numero", 1))
    assert len(pages) == 3
    assert all(p["ocr_confianza"] is None for p in pages)
    assert all(p["motor"] == "pypdfium2" for p in pages)
    assert all(p["posiciones"] for p in pages)
    assert all(p["imagen_url"] for p in pages)
    assert all(p["imagen_url"] == f"/media/subida-digital/paginas/{p['numero']}.png" for p in pages)

    search = client.get("/api/v1/search", params={"q": "gracia"}).json()
    assert search["total"] >= 1
    hits = [h for h in search["resultados"] if h["libro_id"] == "subida-digital"]
    assert hits
    assert all(h["imagen_url"] for h in hits)
    if any(p.get("bloques") for p in pages):
        assert any(h["bbox"] for h in hits)


def test_page_image_endpoint_returns_png() -> None:
    from app.db import ensure_indexes

    ensure_indexes()
    client = TestClient(app)

    response = client.post(
        "/api/v1/ingest/upload",
        files=[("files", ("manual_img.pdf", _text_pdf_bytes(), "application/pdf"))],
        data={"libro_id": "subida-imagen", "metadatos": json.dumps({"titulo": "Con Imagen"})},
    )
    assert response.status_code == 200, response.text

    image = client.get("/api/v1/pages/subida-imagen/pagina/1/imagen")
    assert image.status_code == 200, image.text
    assert image.headers["content-type"] == "image/png"
    assert image.content[:8] == b"\x89PNG\r\n\x1a\n"

    missing = client.get("/api/v1/pages/subida-imagen/pagina/99/imagen")
    assert missing.status_code == 404


def test_upload_rejects_unsupported_files() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/ingest/upload",
        files=[("files", ("nota.txt", b"hola", "text/plain"))],
    )
    assert response.status_code == 400
