"""Test del parseo de ingesta sobre un directorio temporal (sin MongoDB)."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.ingest import parse_book_directory


def _write_book(root: Path) -> Path:
    book_dir = root / "Mi Libro Ñandú"
    pages_dir = book_dir / "paginas"
    pages_dir.mkdir(parents=True)

    metadatos = {
        "titulo": "Libro de Prueba",
        "autor": "Ana López",
        "autor_normalizado": "López, Ana",
        "genero": "teologia",
        "capitulos": [
            {"numero": 1, "titulo": "Uno", "pagina_inicio": 1, "pagina_fin": 2},
            {"numero": 2, "titulo": "Dos", "pagina_inicio": 3, "pagina_fin": 10},
        ],
    }
    (book_dir / "metadatos.json").write_text(
        json.dumps(metadatos, ensure_ascii=False), encoding="utf-8"
    )

    textos = {
        "pagina1.txt": "Señor gracia",  # 2 palabras
        "pagina10.txt": "fe",  # 1 palabra
        "pagina2.txt": "Espíritu Santo y añoranza",  # 4 palabras
    }
    for name, texto in textos.items():
        (pages_dir / name).write_text(texto, encoding="utf-8")

    return book_dir


def test_parse_book_directory(tmp_path: Path) -> None:
    book_dir = _write_book(tmp_path)
    libro = parse_book_directory(book_dir)

    assert libro["libro_id"] == "mi-libro-nandu"
    assert libro["estado_ingesta"] == "pending"
    assert libro["conteo_paginas"] == 3

    numeros = [p["numero"] for p in libro["paginas"]]
    assert numeros == [1, 2, 10]

    assert libro["paginas"][0]["ref"] == "mi-libro-nandu/pagina/1"
    assert libro["paginas"][0]["capitulo_numero"] == 1
    assert libro["paginas"][1]["capitulo_numero"] == 1
    assert libro["paginas"][2]["capitulo_numero"] == 2

    assert libro["paginas"][0]["conteo_palabras"] == 2
    assert libro["paginas"][1]["conteo_palabras"] == 4
    assert libro["paginas"][2]["conteo_palabras"] == 1

    assert libro["conteo_palabras_total"] == 7
    assert libro["caracteres_totales"] == sum(p["conteo_caracteres"] for p in libro["paginas"])


def test_parse_uses_explicit_libro_id(tmp_path: Path) -> None:
    book_dir = tmp_path / "carpeta"
    (book_dir / "paginas").mkdir(parents=True)
    (book_dir / "metadatos.json").write_text(
        json.dumps({"libro_id": "id-fijo", "titulo": "T", "metadatos": {"titulo": "T"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    libro = parse_book_directory(book_dir)
    assert libro["libro_id"] == "id-fijo"
    assert libro["conteo_paginas"] == 0


def test_persist_prunes_media_not_referenced_by_the_new_book(monkeypatch, tmp_path) -> None:
    from unittest.mock import MagicMock

    from app.services import ingest
    from app.services.storage import LocalStorage

    monkeypatch.setattr(ingest, "books_collection", MagicMock())
    monkeypatch.setattr(ingest, "pages_collection", MagicMock())
    storage = LocalStorage(tmp_path)
    for key in ("b/manual.pdf", "b/viejo.pdf", "b/paginas/1.png", "b/paginas/2.png",
                "b/figuras/1-0.png", "b/figuras/1-1.png", "b-2/paginas/1.png"):
        storage.put(key, b"x", "image/png")
    libro = {
        "libro_id": "b", "origen": ["manual.pdf"], "metadatos": {},
        "paginas": [{"ref": "b/pagina/1", "numero": 1, "texto": "",
                     "imagen_url": "b/paginas/1.png",
                     "figuras": [{"imagen_url": "b/figuras/1-0.png"}, {"imagen_url": None}]}],
    }
    ingest._persist(libro, storage)
    left = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert left == ["b-2/paginas/1.png", "b/figuras/1-0.png", "b/manual.pdf", "b/paginas/1.png"]
