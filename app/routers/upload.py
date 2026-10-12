"""Router de ingesta por subida de archivos (multipart).

Acepta uno o más PDF (se elige el libro PDF) o solo imágenes. Guarda los
originales vía `storage`, corre el router de extracción y persiste el libro.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.config import get_settings
from app.db import books_collection
from app.security import require_editor
from app.services.ingest import UploadedFileData, ingest_uploaded_files
from app.services.ocr import OcrNotConfiguredError

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/upload")
def ingest_upload(
    files: list[UploadFile] = File(..., description="Uno o más PDF, o solo imágenes."),
    libro_id: str | None = Form(None),
    metadatos: str | None = Form(None, description="JSON con metadatos del libro."),
    editor: dict = Depends(require_editor),
) -> dict:
    """Ingesta archivos subidos y devuelve el resumen (igual que `/ingest`).

    `def` síncrono: FastAPI lo corre en el threadpool y no bloquea el event loop.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No se recibió ningún archivo.")

    max_bytes = get_settings().max_upload_bytes
    uploads: list[UploadedFileData] = []
    total = 0
    for upload in files:
        data = upload.file.read()
        total += len(data)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"La subida supera el límite de {max_bytes} bytes.",
            )
        uploads.append(UploadedFileData(filename=upload.filename or "archivo", data=data))

    override: dict | None = None
    if metadatos:
        try:
            parsed = json.loads(metadatos)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"metadatos no es JSON válido: {exc}") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="metadatos debe ser un objeto JSON.")
        override = parsed

    try:
        summary = ingest_uploaded_files(
            uploads, libro_id=libro_id, metadatos_override=override
        )
    except OcrNotConfiguredError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if editor["email"]:
        books_collection().update_one({"libro_id": summary["libro_id"]}, {"$set": {"creado_por": editor["email"]}})
    return summary
