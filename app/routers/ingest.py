"""Router de ingesta."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.ratelimit import limit_write
from app.security import require_admin
from app.services.ingest import ingest_root

router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestRequest(BaseModel):
    """Cuerpo de la petición de ingesta."""

    root: str


def _confined(raw: str) -> Path:
    """Resolve symlinks and require the path inside an INGEST_ALLOWED_ROOTS entry (else 403).

    No allowed roots configured => server-path ingest is disabled (safe default).
    """
    allowed = [Path(r.strip()).resolve() for r in get_settings().ingest_allowed_roots.split(",")
               if r.strip() and Path(r.strip()).is_absolute()]
    if not allowed:
        raise HTTPException(403, "La ingesta por ruta del servidor está deshabilitada (INGEST_ALLOWED_ROOTS).")
    target = Path(raw).resolve()
    if not any(target == root or target.is_relative_to(root) for root in allowed):
        raise HTTPException(403, "Ruta fuera de las raíces permitidas (INGEST_ALLOWED_ROOTS).")
    return target


@router.post("", dependencies=[Depends(limit_write), Depends(require_admin)])
def ingest(payload: IngestRequest) -> dict:
    """Ingesta un directorio raíz del servidor (solo admin u ops `X-API-Key`)."""
    root = _confined(payload.root)
    try:
        return ingest_root(root)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
