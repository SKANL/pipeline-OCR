"""Router de libros y páginas."""

from __future__ import annotations

import re
from pathlib import Path

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.db import books_collection, job_pages_collection, jobs_collection, pages_collection
from app.models import (
    BookListResponse,
    FacetValue,
    FacetsResponse,
    PageListResponse,
    PageResponse,
    PageSummary,
)
from app.security import require_editor
from app.services import storage as storage_service
from app.services.storage import LocalStorage, get_storage, media_url
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
        total=total,
        resultados=[PageSummary(**{**doc, "imagen_url": media_url(doc.get("imagen_url"))}) for doc in cursor],
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
        imagen_url=media_url(doc.get("imagen_url")),
        imagen_ancho=doc.get("imagen_ancho"),
        imagen_alto=doc.get("imagen_alto"),
        bloques=doc.get("bloques") or [],
        figuras=[{**f, "imagen_url": media_url(f.get("imagen_url"))} for f in doc.get("figuras") or []],
        lectura=doc.get("lectura") or [],
        ref_anterior=ref_anterior,
        ref_siguiente=ref_siguiente,
        motor=doc.get("motor"),
        coincidencias=matches,
        coincidencias_truncadas=truncated,
        advertencia_localizacion=doc.get("advertencia_localizacion"),
    )


@router.get("/pages/{libro_id}/pagina/{numero}/imagen")
def get_page_image(libro_id: str, numero: int) -> Response:
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
    storage = get_storage()
    if not isinstance(storage, LocalStorage):
        return RedirectResponse(storage.url(relative))

    # Defensa en profundidad: resolver contra MEDIA_ROOT y exigir contención.
    root = Path(get_settings().media_root).resolve()
    resolved = (root / relative).resolve()
    if resolved != root and not resolved.is_relative_to(root):
        raise HTTPException(status_code=404, detail=f"Imagen no encontrada: {ref}")

    try:
        path = storage.path(relative)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"Imagen no encontrada: {ref}") from exc

    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Imagen no encontrada en disco: {relative}")

    return FileResponse(path, media_type="image/png", filename=f"{numero}.png")


# --------------------------------------------------------------------------
# Editor management (PATCH / DELETE / reprocesar)
# --------------------------------------------------------------------------
class LibroPatch(BaseModel):
    """Editable `metadatos` fields; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    titulo: str = Field(None, min_length=1, max_length=500)
    subtitulo: Optional[str] = Field(None, max_length=500)
    autor: Optional[str] = Field(None, max_length=300)
    autor_normalizado: Optional[str] = Field(None, max_length=300)
    editorial: Optional[str] = Field(None, max_length=300)
    anio_publicacion: Optional[int] = Field(None, ge=0, le=3000)
    idioma: str = Field(None, min_length=2, max_length=10)
    genero: Optional[str] = Field(None, max_length=100)
    tradicion: Optional[str] = Field(None, max_length=100)
    isbn: Optional[str] = Field(None, max_length=20)
    temas: list[str] = Field(None, max_length=50)
    descripcion: Optional[str] = Field(None, max_length=5000)


# Fields denormalized onto every `pages` row (see `ingest.build_page_projection`).
_PAGE_FIELDS = ("titulo", "autor", "genero", "autor_normalizado")
_ACTIVE = ("esperando_subida", "pendiente", "procesando")


def _safe_id(libro_id: str) -> str:
    if not _SAFE_LIBRO_ID.match(libro_id):
        raise HTTPException(status_code=400, detail=f"libro_id inválido: {libro_id}")
    return libro_id


@router.patch("/books/{libro_id}", dependencies=[Depends(require_editor)])
def update_book(libro_id: str, payload: LibroPatch) -> dict:
    """Edit metadata; `titulo`/`idioma`/`temas` cannot be null."""
    changes = payload.model_dump(exclude_unset=True)
    for required in ("titulo", "idioma", "temas"):
        if required in changes and changes[required] is None:
            raise HTTPException(status_code=422, detail=f"{required} no puede ser null.")
    if not books_collection().find_one({"libro_id": libro_id}, {"_id": 1}):
        raise HTTPException(status_code=404, detail=f"Libro no encontrado: {libro_id}")
    if changes:
        books_collection().update_one({"libro_id": libro_id}, {"$set": {
            **{f"metadatos.{k}": v for k, v in changes.items()}, "actualizado_en": datetime.now(timezone.utc)}})
        page_changes = {k: v for k, v in changes.items() if k in _PAGE_FIELDS}
        if page_changes:
            pages_collection().update_many({"libro_id": libro_id}, {"$set": page_changes})
    return get_book(libro_id)


@router.delete("/books/{libro_id}", status_code=204, dependencies=[Depends(require_editor)])
def delete_book(libro_id: str) -> Response:
    """Delete the book, its pages, its jobs + checkpoints and its media prefix. Idempotent."""
    _safe_id(libro_id)
    job_ids = [j["_id"] for j in jobs_collection().find({"libro_id": libro_id}, {"_id": 1})]
    job_pages_collection().delete_many({"trabajo_id": {"$in": job_ids}})
    jobs_collection().delete_many({"_id": {"$in": job_ids}})
    pages_collection().delete_many({"libro_id": libro_id})
    books_collection().delete_one({"libro_id": libro_id})
    storage_service.get_storage().delete_prefix(f"{libro_id}/")
    return Response(status_code=204)


@router.post("/books/{libro_id}/reprocesar", status_code=202, dependencies=[Depends(require_editor)])
def reprocess_book(libro_id: str) -> dict:
    """Requeue the book's ingest job from its stored originals, keeping edited metadata."""
    book = books_collection().find_one({"libro_id": libro_id}, {"metadatos": 1})
    if not book:
        raise HTTPException(status_code=404, detail=f"Libro no encontrado: {libro_id}")
    job = jobs_collection().find_one({"libro_id": libro_id}, sort=[("creado_en", -1)])
    if job is None:
        # ponytail: books ingested before the job queue have no job; re-upload them instead.
        raise HTTPException(status_code=409, detail="El libro no tiene originales en la cola; vuelve a subirlo.")
    now = datetime.now(timezone.utc)
    result = jobs_collection().update_one(
        {"_id": job["_id"], "estado": {"$nin": list(_ACTIVE)}},
        {"$set": {"estado": "pendiente", "intentos": 0, "error": None, "worker_id": None,
                  "bloqueado_hasta": None, "disponible_desde": now, "actualizado_en": now,
                  "metadatos": book.get("metadatos") or {},
                  "progreso": {"paginas_hechas": 0, "paginas_total": None}}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=409, detail="Ya hay un procesamiento activo para este libro.")
    job_pages_collection().delete_many({"trabajo_id": job["_id"]})
    return {"trabajo_id": str(job["_id"]), "estado": "pendiente"}
