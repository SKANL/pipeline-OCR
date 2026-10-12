"""Búsqueda full-text sobre el índice `$text` de `pages.texto_busqueda`.

Ranking con `$meta: textScore` y filtros por `genero` / `autor_normalizado`.
Devuelve `SearchHit` con snippet calculado en Python (ventana alrededor del
primer match, resaltado con `<mark>`).
"""

from __future__ import annotations

from html import escape

from app.db import pages_collection
from app.models import SearchHit
from app.services.storage import media_url
from app.services.text import fold_text, make_diacritic_insensitive_pattern
from app.services.locator import locate_matches, match_ranges, query_units

SNIPPET_WINDOW = 200


def _query_terms(query: str) -> list[str]:
    """Separa la query en términos no vacíos."""
    return query_units(query)


def make_snippet(texto: str, query: str, window: int = SNIPPET_WINDOW) -> str:
    """Snippet HTML: texto escapado y TODAS las apariciones envueltas en `<mark>`.

    El match es insensible a mayúsculas y a diacríticos: buscar
    "justificacion" resalta "justificación".
    """
    texto = texto or ""
    ranges, _ = match_ranges(texto, query)
    if not ranges:
        return escape(texto[:window])
    first = ranges[0][0]
    start = max(0, first - window // 2)
    end = min(len(texto), start + window)
    parts: list[str] = []
    cursor = start
    for left, right in ranges:
        left, right = max(left, start), min(right, end)
        if left >= right:
            continue
        parts.extend([escape(texto[cursor:left]), "<mark>", escape(texto[left:right]), "</mark>"])
        cursor = right
    parts.append(escape(texto[cursor:end]))

    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(texto) else ""
    return f"{prefix}{''.join(parts)}{suffix}"


def _match_block_for_query(
    doc: dict, query: str
) -> tuple[int | None, list[float] | None, list[float] | None]:
    """Localiza el bloque que mejor contiene el término buscado (best-effort).

    Devuelve `(bloque_idx, bbox, bbox_norm)` del bloque con MÁS términos
    coincidentes (desempate: el primero). `bbox`/`bbox_norm` quedan en `None`
    si el bloque no trae la caja, o si la página no tiene bloques o ninguno
    coincide. Nota: el texto de la página y los bloques pueden venir de
    extractores distintos; cuando no coinciden no hay caja y el front cae al
    resaltado del término en el texto.
    """
    bloques = doc.get("bloques") or []
    terms = [fold_text(term) for term in _query_terms(query) if fold_text(term)]
    if not terms:
        return None, None, None

    best_index: int | None = None
    best_block: dict | None = None
    best_score = 0
    for index, bloque in enumerate(bloques):
        if not isinstance(bloque, dict):
            continue
        texto = fold_text(str(bloque.get("texto", "")))
        score = sum(1 for term in terms if term in texto)
        if score > best_score:
            best_index, best_block, best_score = index, bloque, score

    if best_block is None:
        return None, None, None

    bbox = best_block.get("bbox")
    bbox = bbox if isinstance(bbox, list) and len(bbox) == 4 else None
    bbox_norm = best_block.get("bbox_norm")
    bbox_norm = (
        bbox_norm if isinstance(bbox_norm, list) and len(bbox_norm) == 4 else None
    )
    return best_index, bbox, bbox_norm


def _hit_from_doc(doc: dict, query: str, score: float | None) -> SearchHit:
    bloque_idx, bbox, bbox_norm = _match_block_for_query(doc, query)
    matches, truncated = locate_matches(doc, query, limit=8)
    return SearchHit(
        libro_id=doc.get("libro_id", ""),
        titulo=doc.get("titulo"),
        autor=doc.get("autor"),
        ref=doc.get("ref", ""),
        numero=doc.get("numero", 0),
        capitulo_numero=doc.get("capitulo_numero"),
        snippet=make_snippet(doc.get("texto", ""), query),
        score=score,
        imagen_url=media_url(doc.get("imagen_url")),
        bbox=bbox,
        bloque_idx=bloque_idx,
        bbox_norm=bbox_norm,
        coincidencias=matches,
        coincidencias_truncadas=truncated,
    )


def search_pages(
    query: str,
    genero: str | None = None,
    autor: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[int, list[SearchHit]]:
    """Busca páginas por texto (índice `$text`) con filtros de género/autor.

    La query se pliega igual que el campo indexado `texto_busqueda`, de modo
    que un término sin acentos ("justificacion") haga match. Devuelve
    `(total, resultados)`.
    """
    pages = pages_collection()

    filters: dict = {"$text": {"$search": fold_text(query)}}
    if genero:
        filters["genero"] = genero
    if autor:
        filters["autor_normalizado"] = {
            "$regex": make_diacritic_insensitive_pattern(autor),
            "$options": "i",
        }

    total = pages.count_documents(filters)
    cursor = (
        pages.find(filters, {"score": {"$meta": "textScore"}})
        .sort([("score", {"$meta": "textScore"})])
        .skip(offset)
        .limit(limit)
    )
    results = [_hit_from_doc(doc, query, doc.get("score")) for doc in cursor]
    return total, results
