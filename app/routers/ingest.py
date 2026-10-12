"""Router de ingesta."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.security import require_api_key
from app.services.ingest import ingest_root

router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestRequest(BaseModel):
    """Cuerpo de la petición de ingesta."""

    root: str


@router.post("", dependencies=[Depends(require_api_key)])
def ingest(payload: IngestRequest) -> dict:
    """Ingesta un directorio raíz y devuelve el resumen."""
    try:
        return ingest_root(payload.root)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
