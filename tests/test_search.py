"""Tests puros del snippet y construcción de hits (sin MongoDB)."""

from __future__ import annotations

from app.services.search import _hit_from_doc, make_snippet


def test_snippet_marks_first_match() -> None:
    texto = "El Señor es bueno; la gracia y la fe sostienen al creyente."
    snippet = make_snippet(texto, "gracia")
    assert "<mark>gracia</mark>" in snippet


def test_snippet_no_match_returns_prefix() -> None:
    texto = "a" * 500
    snippet = make_snippet(texto, "inexistente")
    assert snippet == texto[:200]
    assert "<mark>" not in snippet


def test_snippet_case_insensitive() -> None:
    snippet = make_snippet("habla de la Gracia divina", "gracia")
    assert "<mark>Gracia</mark>" in snippet


def test_snippet_diacritic_insensitive() -> None:
    snippet = make_snippet("la justificación por la fe", "justificacion")
    assert "<mark>justificación</mark>" in snippet


def test_snippet_marks_multiple_terms() -> None:
    snippet = make_snippet("la gracia y la fe sostienen", "gracia fe")
    assert "<mark>gracia</mark>" in snippet
    assert "<mark>fe</mark>" in snippet


def test_hit_from_doc_maps_fields() -> None:
    doc = {
        "libro_id": "libro-x",
        "titulo": "Título X",
        "autor": "Autor X",
        "ref": "libro-x/pagina/7",
        "numero": 7,
        "capitulo_numero": 1,
        "texto": "gracia sobreabundante",
    }
    hit = _hit_from_doc(doc, "gracia", 1.5)
    assert hit.libro_id == "libro-x"
    assert hit.ref == "libro-x/pagina/7"
    assert hit.numero == 7
    assert hit.capitulo_numero == 1
    assert "<mark>gracia</mark>" in hit.snippet
    assert hit.score == 1.5
    assert hit.imagen_url is None
    assert hit.bbox is None
    assert hit.bloque_idx is None
    assert hit.bbox_norm is None


def test_hit_includes_imagen_url_and_bbox_from_blocks() -> None:
    doc = {
        "libro_id": "libro-x",
        "ref": "libro-x/pagina/1",
        "numero": 1,
        "texto": "la gracia soberana",
        "imagen_url": "/media/libro-x/paginas/1.png",
        "bloques": [
            {"bbox": [1.0, 2.0, 3.0, 4.0], "texto": "otra cosa"},
            {"bbox": [5.0, 6.0, 7.0, 8.0], "texto": "la Gracia soberana"},
        ],
    }
    hit = _hit_from_doc(doc, "gracia", None)
    assert hit.imagen_url == "/media/libro-x/paginas/1.png"
    assert hit.bbox == [5.0, 6.0, 7.0, 8.0]
    assert hit.bloque_idx == 1


def test_hit_includes_bloque_idx_and_bbox_norm() -> None:
    doc = {
        "libro_id": "libro-x",
        "ref": "libro-x/pagina/1",
        "numero": 1,
        "texto": "la gracia soberana",
        "imagen_url": "/media/libro-x/paginas/1.png",
        "bloques": [
            {"bbox": [1.0, 2.0, 3.0, 4.0], "texto": "otra cosa"},
            {
                "bbox": [5.0, 6.0, 7.0, 8.0],
                "bbox_norm": [0.1, 0.2, 0.3, 0.4],
                "texto": "la Gracia soberana",
            },
        ],
    }
    hit = _hit_from_doc(doc, "gracia", None)
    assert hit.bloque_idx == 1
    assert hit.bbox == [5.0, 6.0, 7.0, 8.0]
    assert hit.bbox_norm == [0.1, 0.2, 0.3, 0.4]


def test_hit_bbox_none_when_term_not_in_blocks() -> None:
    doc = {
        "libro_id": "libro-x",
        "ref": "libro-x/pagina/1",
        "numero": 1,
        "texto": "gracia",
        "bloques": [{"bbox": [1.0, 2.0, 3.0, 4.0], "texto": "sin coincidencias"}],
    }
    hit = _hit_from_doc(doc, "gracia", None)
    assert hit.bbox is None
    assert hit.bloque_idx is None
    assert hit.bbox_norm is None


def test_hit_builds_url_from_stored_key() -> None:
    hit = _hit_from_doc({"ref": "libro-x/pagina/1", "imagen_url": "libro-x/paginas/1.png"}, "x", None)
    assert hit.imagen_url == "/media/libro-x/paginas/1.png"
