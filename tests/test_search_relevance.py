"""Search relevance on `$text`: title weighting, phrases and stable ordering."""

from __future__ import annotations

import pytest

from app.services.ingest import build_page_projection
from tests.test_mongo import _mongo_available

needs_mongo = pytest.mark.skipif(not _mongo_available(), reason="MongoDB no está accesible en MONGODB_URI")


def test_projection_has_folded_title() -> None:
    doc = build_page_projection("l", {"ref": "l/pagina/1", "numero": 1, "texto": "x"}, {"titulo": "Catecismo de la Doctrina Cristiána"})
    assert doc["titulo_busqueda"] == "catecismo de la doctrina cristiana"


def _seed(rows: list[tuple[str, int, str, str]]) -> None:
    from app.db import ensure_indexes, pages_collection

    ensure_indexes()
    pages = pages_collection()
    pages.delete_many({"libro_id": {"$regex": "^rel-"}})
    for libro_id, numero, titulo, texto in rows:
        pages.insert_one(build_page_projection(libro_id, {"ref": f"{libro_id}/pagina/{numero}", "numero": numero, "texto": texto}, {"titulo": titulo}))


@needs_mongo
def test_title_match_outranks_a_passing_mention() -> None:
    from app.services.search import search_pages

    _seed([("rel-otro", 1, "Sermones varios", "se cita el catecismo una vez entre muchas otras palabras del sermón"),
           ("rel-catecismo", 1, "Catecismo de Astete", "Todo fiel cristiano es muy obligado a tener devoción")])
    _, hits = search_pages("catecismo", limit=5)
    assert [h.libro_id for h in hits if h.libro_id.startswith("rel-")][:2] == ["rel-catecismo", "rel-otro"]


@needs_mongo
def test_quoted_phrase_requires_the_phrase() -> None:
    from app.services.search import search_pages

    _seed([("rel-a", 1, "A", "la fe sin obras está muerta"), ("rel-b", 1, "B", "las obras de la fe y sin embargo")])
    _, hits = search_pages('"fe sin obras"', limit=10)
    assert {h.libro_id for h in hits if h.libro_id.startswith("rel-")} == {"rel-a"}


@needs_mongo
def test_ties_are_ordered_by_book_and_page() -> None:
    from app.services.search import search_pages

    _seed([("rel-z", 2, "T", "gracia"), ("rel-z", 1, "T", "gracia"), ("rel-y", 3, "T", "gracia")])
    _, hits = search_pages("gracia", limit=10)
    assert [(h.libro_id, h.numero) for h in hits if h.libro_id.startswith("rel-")] == [("rel-y", 3), ("rel-z", 1), ("rel-z", 2)]
