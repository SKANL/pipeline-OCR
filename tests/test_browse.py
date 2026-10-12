"""Tests de la API de lectura/navegación (Pass 2b). Requieren MongoDB.

Cubren: índice de páginas (+404), facetas, filtros de `/books` y poda de
páginas obsoletas al re-ingerir. Se omiten si Mongo no está accesible.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

from app.config import get_settings
from app.db import ensure_indexes, pages_collection
from app.main import app

API = "/api/v1"


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


@pytest.fixture(autouse=True)
def _indexes() -> None:
    ensure_indexes()


def _seed_book(
    book_dir: Path,
    libro_id: str,
    *,
    genero: str,
    autor_normalizado: str,
    pages: int,
) -> None:
    """Crea e ingesta un libro de texto (sin OCR) en `book_dir`."""
    from app.services.ingest import ingest_book_dir

    pages_dir = book_dir / "paginas"
    pages_dir.mkdir(parents=True)
    (book_dir / "metadatos.json").write_text(
        json.dumps(
            {
                "libro_id": libro_id,
                "titulo": libro_id,
                "autor": autor_normalizado,
                "autor_normalizado": autor_normalizado,
                "genero": genero,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    for i in range(1, pages + 1):
        (pages_dir / f"{i:03d}.txt").write_text(
            f"Contenido de prueba pagina {i}.", encoding="utf-8"
        )
    ingest_book_dir(book_dir, libro_id=libro_id)


def test_page_index_shape_and_404(tmp_path: Path) -> None:
    libro_id = "browse-index"
    _seed_book(tmp_path / "idx", libro_id, genero="teologia", autor_normalizado="Autor, Uno", pages=3)
    client = TestClient(app)

    response = client.get(f"{API}/books/{libro_id}/paginas")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert len(body["resultados"]) == 3

    first = body["resultados"][0]
    assert set(first) == {
        "numero",
        "ref",
        "capitulo_numero",
        "conteo_palabras",
        "imagen_url",
    }
    assert first["numero"] == 1
    assert first["ref"] == f"{libro_id}/pagina/1"
    assert first["conteo_palabras"] == 5

    page = client.get(
        f"{API}/books/{libro_id}/paginas", params={"limit": 1, "offset": 1}
    ).json()
    assert page["total"] == 3
    assert len(page["resultados"]) == 1
    assert page["resultados"][0]["numero"] == 2

    missing = client.get(f"{API}/books/no-existe/paginas")
    assert missing.status_code == 404


def test_facets_aggregation_counts(tmp_path: Path) -> None:
    _seed_book(tmp_path / "fa", "browse-fac-a", genero="facet-gen-x", autor_normalizado="Facet Autor A", pages=1)
    _seed_book(tmp_path / "fb", "browse-fac-b", genero="facet-gen-x", autor_normalizado="Facet Autor A", pages=1)
    _seed_book(tmp_path / "fc", "browse-fac-c", genero="facet-gen-y", autor_normalizado="Facet Autor B", pages=1)
    client = TestClient(app)

    body = client.get(f"{API}/facets").json()
    generos = {g["valor"]: g["count"] for g in body["generos"]}
    autores = {a["valor"]: a["count"] for a in body["autores"]}

    assert generos["facet-gen-x"] == 2
    assert generos["facet-gen-y"] == 1
    assert autores["Facet Autor A"] == 2
    assert autores["Facet Autor B"] == 1

    counts = [g["count"] for g in body["generos"]]
    assert counts == sorted(counts, reverse=True)


def test_books_filters_by_genero_and_autor(tmp_path: Path) -> None:
    _seed_book(tmp_path / "f1", "browse-filter-a", genero="filtro-gen-1", autor_normalizado="López, Ana", pages=1)
    _seed_book(tmp_path / "f2", "browse-filter-b", genero="filtro-gen-2", autor_normalizado="García, Beto", pages=1)
    client = TestClient(app)

    by_genero = client.get(f"{API}/books", params={"genero": "filtro-gen-1"}).json()
    ids = {b["libro_id"] for b in by_genero["resultados"]}
    assert "browse-filter-a" in ids
    assert "browse-filter-b" not in ids

    by_autor = client.get(f"{API}/books", params={"autor": "lopez"}).json()
    ids = {b["libro_id"] for b in by_autor["resultados"]}
    assert "browse-filter-a" in ids
    assert "browse-filter-b" not in ids

    by_autor_upper = client.get(f"{API}/books", params={"autor": "GARCIA"}).json()
    ids = {b["libro_id"] for b in by_autor_upper["resultados"]}
    assert "browse-filter-b" in ids


def test_reingest_prunes_stale_pages(tmp_path: Path) -> None:
    libro_id = "browse-shrink"
    _seed_book(tmp_path / "v1", libro_id, genero="poda", autor_normalizado="Poda Autor", pages=5)
    _seed_book(tmp_path / "v2", libro_id, genero="poda", autor_normalizado="Poda Autor", pages=2)

    docs = list(pages_collection().find({"libro_id": libro_id}).sort("numero", 1))
    assert [d["numero"] for d in docs] == [1, 2]

    body = TestClient(app).get(f"{API}/books/{libro_id}/paginas").json()
    assert body["total"] == 2
