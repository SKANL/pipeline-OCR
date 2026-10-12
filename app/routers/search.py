"""Router de búsqueda full-text."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.ratelimit import limit_search
from app.models import SearchResponse
from app.services.search import search_pages

router = APIRouter(tags=["search"], dependencies=[Depends(limit_search)])


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, description="Término de búsqueda"),
    genero: str | None = None,
    autor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> SearchResponse:
    """Busca pasajes y devuelve hits rankeados con snippet."""
    total, resultados = search_pages(
        q, genero=genero, autor=autor, limit=limit, offset=offset
    )
    return SearchResponse(total=total, resultados=resultados)
