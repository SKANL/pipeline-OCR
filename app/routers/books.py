"""Router de libros y páginas."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import get_settings
from app.db import books_collection, pages_collection
from app.models import (
    BookListResponse,
    FacetValue,
    FacetsResponse,
    PageListResponse,
    PageResponse,
    PageSummary,
)
from app.services.storage import get_storage
from app.services.text import make_diacritic_insensitive_pattern
from app.services.locator import locate_matches

router = APIRouter(tags=["books"])

# Un `libro_id` nunca debe poder salir del media root ni resolver a otra ruta.
_SAFE_LIBRO_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _facet_pipeline(field: str) -> list[dict]:
    """Etapas de agregación que cuentan libros por un campo de metadatos."""
    return [
        {"$match": {field: {"$exists": True, "$nin": [None, ""]}}},
        {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
    ]


@router.get("/books", response_model=BookListResponse)
def list_books(
    genero: str | None = Query(None, description="Filtra por género (match exacto)."),
    autor: str | None = Query(
        None, description="Filtra por autor (contiene, insensible a mayúsculas/diacríticos)."
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> BookListResponse:
    """Lista los metadatos de los libros (sin texto de páginas)."""
    books = books_collection()
    filters: dict = {}
    if genero:
        filters["metadatos.genero"] = genero
    if autor:
        filters["metadatos.autor_normalizado"] = {
            "$regex": make_diacritic_insensitive_pattern(autor),
            "$options": "i",
        }
    total = books.count_documents(filters)
    projection = {"paginas": 0}
    cursor = books.find(filters, projection).skip(offset).limit(limit)
    resultados = []
    for doc in cursor:
        doc.pop("_id", None)
        resultados.append(doc)
    return BookListResponse(total=total, resultados=resultados)


@router.get("/facets", response_model=FacetsResponse)
def facets() -> FacetsResponse:
    """Facetas de género y autor (conteo de libros) para los filtros de la UI."""
    pipeline = [
        {
            "$facet": {
                "generos": _facet_pipeline("metadatos.genero"),
                "autores": _facet_pipeline("metadatos.autor_normalizado"),
            }
        }
    ]
    block = next(iter(books_collection().aggregate(pipeline)), {})
    return FacetsResponse(
        generos=[
            FacetValue(valor=doc["_id"], count=doc["count"])
            for doc in block.get("generos", [])
        ],
        autores=[
            FacetValue(valor=doc["_id"], count=doc["count"])
            for doc in block.get("autores", [])
        ],
    )


@router.get("/books/{libro_id}/paginas", response_model=PageListResponse)
def list_pages(
    libro_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> PageListResponse:
    """Índice de páginas del libro (sin texto), para armar el lector."""
    if not books_collection().find_one({"libro_id": libro_id}, {"_id": 1}):
        raise HTTPException(status_code=404, detail=f"Libro no encontrado: {libro_id}")

    pages = pages_collection()
    filtro = {"libro_id": libro_id}
    total = pages.count_documents(filtro)
    projection = {
        "_id": 0,
        "numero": 1,
        "ref": 1,
        "capitulo_numero": 1,
        "conteo_palabras": 1,
        "imagen_url": 1,
    }
    cursor = pages.find(filtro, projection).sort("numero", 1).skip(offset).limit(limit)
    return PageListResponse(
        total=total, resultados=[PageSummary(**doc) for doc in cursor]
    )


@router.get("/books/{libro_id}")
def get_book(libro_id: str) -> dict:
    """Devuelve metadatos y capítulos de un libro (sin texto de páginas)."""
    doc = books_collection().find_one({"libro_id": libro_id}, {"paginas": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Libro no encontrado: {libro_id}")
    doc.pop("_id", None)
    return doc


@router.get("/ref/{libro_id}/pagina/{numero}", response_model=PageResponse)
def get_page(libro_id: str, numero: int, q: str | None = Query(None, max_length=500, description="Localización literal: términos independientes o frases entre comillas dobles.")) -> PageResponse:
    """Devuelve el texto de una página y las refs anterior/siguiente."""
    pages = pages_collection()
    ref = f"{libro_id}/pagina/{numero}"
    doc = pages.find_one({"ref": ref})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Página no encontrada: {ref}")

    anterior = f"{libro_id}/pagina/{numero - 1}"
    siguiente = f"{libro_id}/pagina/{numero + 1}"
    ref_anterior = anterior if pages.find_one({"ref": anterior}, {"ref": 1}) else None
    ref_siguiente = siguiente if pages.find_one({"ref": siguiente}, {"ref": 1}) else None
    matches, truncated = locate_matches(doc, q) if isinstance(q, str) and q else ([], False)

    return PageResponse(
        libro_id=libro_id,
        ref=ref,
        numero=doc.get("numero", numero),
        capitulo_numero=doc.get("capitulo_numero"),
        texto=doc.get("texto", ""),
        conteo_palabras=doc.get("conteo_palabras", 0),
        conteo_caracteres=doc.get("conteo_caracteres", 0),
        imagen_url=doc.get("imagen_url"),
        imagen_ancho=doc.get("imagen_ancho"),
        imagen_alto=doc.get("imagen_alto"),
        bloques=doc.get("bloques") or [],
        figuras=doc.get("figuras") or [],
        lectura=doc.get("lectura") or [],
        ref_anterior=ref_anterior,
        ref_siguiente=ref_siguiente,
        motor=doc.get("motor"),
        coincidencias=matches,
        coincidencias_truncadas=truncated,
        advertencia_localizacion=doc.get("advertencia_localizacion"),
    )


@router.get("/pages/{libro_id}/pagina/{numero}/imagen")
def get_page_image(libro_id: str, numero: int) -> FileResponse:
    """Devuelve la imagen (PNG) de la página o 404 si no existe."""
    if not _SAFE_LIBRO_ID.match(libro_id):
        raise HTTPException(status_code=400, detail=f"libro_id inválido: {libro_id}")
    if numero < 1:
        raise HTTPException(status_code=400, detail=f"numero inválido: {numero}")

    ref = f"{libro_id}/pagina/{numero}"
    doc = pages_collection().find_one({"ref": ref}, {"imagen_url": 1})
    imagen_url = doc.get("imagen_url") if doc else None
    if not imagen_url:
        raise HTTPException(status_code=404, detail=f"Imagen no encontrada: {ref}")

    relative = imagen_url.removeprefix("/media/").lstrip("/")

    # Defensa en profundidad: resolver contra MEDIA_ROOT y exigir contención.
    root = Path(get_settings().media_root).resolve()
    resolved = (root / relative).resolve()
    if resolved != root and not resolved.is_relative_to(root):
        raise HTTPException(status_code=404, detail=f"Imagen no encontrada: {ref}")

    try:
        path = get_storage().path(relative)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"Imagen no encontrada: {ref}") from exc

    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Imagen no encontrada en disco: {relative}")

    return FileResponse(path, media_type="image/png", filename=f"{numero}.png")
