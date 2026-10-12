"""Router de citación."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.db import books_collection, pages_collection
from app.models import CitationResponse
from app.services.citation import build_citation

router = APIRouter(tags=["citations"])


@router.get("/cite/{libro_id}/pagina/{numero}", response_model=CitationResponse)
def cite(
    libro_id: str,
    numero: int,
    estilo: str = Query("apa", description="apa | chicago | mla"),
) -> CitationResponse:
    """Genera una cita formateada para una página."""
    book = books_collection().find_one({"libro_id": libro_id}, {"metadatos": 1})
    if not book:
        raise HTTPException(status_code=404, detail=f"Libro no encontrado: {libro_id}")

    ref = f"{libro_id}/pagina/{numero}"
    if not pages_collection().find_one({"ref": ref}, {"ref": 1}):
        raise HTTPException(status_code=404, detail=f"Página no encontrada: {ref}")

    try:
        result = build_citation(libro_id, book.get("metadatos", {}), numero, estilo=estilo)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CitationResponse(**result)
