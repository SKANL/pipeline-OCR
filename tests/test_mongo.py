"""Tests dependientes de MongoDB. Se omiten si Mongo no está accesible."""

from __future__ import annotations

from pathlib import Path

import pytest
from pymongo import MongoClient

from app.config import get_settings


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


@pytest.fixture()
def seeded_book(tmp_path: Path) -> str:
    from app.services.ingest import ingest_root

    book = tmp_path / "libro_prueba"
    pages = book / "paginas"
    pages.mkdir(parents=True)
    import json

    (book / "metadatos.json").write_text(
        json.dumps(
            {
                "titulo": "Prueba MongoDB",
                "autor": "Test Autor",
                "autor_normalizado": "Autor, Test",
                "genero": "teologia",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    for i in range(1, 4):
        (pages / f"{i:03d}.txt").write_text(
            f"Señor, esta página {i} habla de la gracia y de la fe.", encoding="utf-8"
        )

    from app.db import ensure_indexes

    ensure_indexes()
    ingest_root(tmp_path)
    return "libro-prueba"


def test_search_returns_hits(seeded_book: str) -> None:
    from app.services.search import search_pages

    total, hits = search_pages("gracia", limit=10)
    assert total >= 1
    assert hits
    assert "<mark>" in hits[0].snippet
    assert seeded_book in {h.libro_id for h in hits}
