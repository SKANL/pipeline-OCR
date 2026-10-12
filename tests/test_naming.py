"""Tests puros de nombres: orden natural de imágenes y slug/ref."""

from __future__ import annotations

from app.services.naming import natural_key, slugify


def test_natural_sort_image_filenames() -> None:
    names = ["pagina10.jpg", "pagina2.png", "pagina1.jpeg", "pagina20.webp"]
    ordered = sorted(names, key=natural_key)
    assert ordered == ["pagina1.jpeg", "pagina2.png", "pagina10.jpg", "pagina20.webp"]


def test_natural_sort_mixed_prefix() -> None:
    names = ["scan_100.png", "scan_9.png", "scan_10.png"]
    assert sorted(names, key=natural_key) == ["scan_9.png", "scan_10.png", "scan_100.png"]


def test_slugify_book_folder() -> None:
    assert slugify("Comentario Evangelio Juan") == "comentario-evangelio-juan"


def test_slugify_accents_and_symbols() -> None:
    assert slugify("  Ñandú & Cañón  ") == "nandu-canon"


def test_slugify_from_pdf_filename() -> None:
    assert slugify("Libro Escaneado 2024.pdf".removesuffix(".pdf")) == "libro-escaneado-2024"


def test_ref_shape() -> None:
    libro_id = slugify("Libro de Prueba")
    assert f"{libro_id}/pagina/{3}" == "libro-de-prueba/pagina/3"
