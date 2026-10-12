"""Subidas con URL firmada (PUT directo al bucket) y estado de trabajos.

Flujo: `POST /uploads` -> el cliente hace PUT de cada archivo a su URL ->
`POST /uploads/{id}/completar` encola el trabajo -> `GET /trabajos/{id}`.
El id de la subida ES el id del trabajo. Idempotencia por sha256 del
contenido (ver `jobs.upload_digest`).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from app.config import get_settings
from app.db import jobs_collection
from app.ratelimit import limit_write
from app.security import require_editor
from app.services import jobs
from app.services import storage as storage_service
from app.services.naming import slugify
from app.services.storage import safe_filename

router = APIRouter(tags=["subidas"])

PUT_EXPIRY = 900  # seconds a presigned PUT stays valid


class ArchivoSubida(BaseModel):
    nombre: str = Field(min_length=1, max_length=255)
    tipo_contenido: str
    tamano: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SubidaRequest(BaseModel):
    archivos: list[ArchivoSubida] = Field(min_length=1, max_length=500)
    metadatos: dict | None = None


def _validate(archivos: list[ArchivoSubida]) -> None:
    settings = get_settings()
    for archivo in archivos:
        if archivo.tipo_contenido not in jobs.CONTENT_TYPES:
            raise HTTPException(422, f"Tipo no soportado: {archivo.tipo_contenido} "
                                     f"(admitidos: {', '.join(jobs.CONTENT_TYPES)}).")
        if archivo.tamano > settings.max_file_bytes:
            raise HTTPException(413, f"{archivo.nombre} supera el límite de {settings.max_file_bytes} bytes.")
    if sum(a.tamano for a in archivos) > settings.max_upload_bytes:
        raise HTTPException(413, f"La subida supera el límite de {settings.max_upload_bytes} bytes.")
    if len({jobs.CONTENT_TYPES[a.tipo_contenido][0] for a in archivos}) > 1:
        raise HTTPException(422, "Todos los archivos de un libro deben ser del mismo tipo "
                                 "(un PDF o varios, imágenes, o texto).")


def _presigned(job: dict, storage) -> dict:
    try:
        urls = [storage.presign_put(a["clave"], a["tipo_contenido"], PUT_EXPIRY) for a in job["archivos"]]
    except NotImplementedError as exc:
        raise HTTPException(501, str(exc)) from exc
    return {
        "id": str(job["_id"]),
        "estado": job["estado"],
        "libro_id": job["libro_id"],
        "existente": False,
        "expira_en": (datetime.now(timezone.utc) + timedelta(seconds=PUT_EXPIRY)).isoformat(),
        "archivos": [
            {"nombre": a["nombre"], "clave": a["clave"], "url": url, "metodo": "PUT",
             "encabezados": {"Content-Type": a["tipo_contenido"]}}
            for a, url in zip(job["archivos"], urls)
        ],
    }


@router.post("/uploads", status_code=201, dependencies=[Depends(limit_write)])
def create_upload(payload: SubidaRequest, response: Response, editor: dict = Depends(require_editor)) -> dict:
    """Devuelve URLs PUT firmadas, o el trabajo/libro existente si el contenido ya se subió."""
    _validate(payload.archivos)
    storage = storage_service.get_storage()
    digest = jobs.upload_digest([a.sha256 for a in payload.archivos])
    existing = jobs_collection().find_one({"sha256": digest})

    if existing is None:
        stem = (payload.metadatos or {}).get("titulo") or Path(payload.archivos[0].nombre).stem
        libro_id = f"{slugify(str(stem)) or 'libro'}-{digest[:8]}"
        archivos = [
            {**a.model_dump(),
             "clave": f"{libro_id}/{i:03d}-{safe_filename(Path(a.nombre).stem)}{jobs.CONTENT_TYPES[a.tipo_contenido][1]}"}
            for i, a in enumerate(payload.archivos)
        ]
        try:
            job_id = jobs.create_job(libro_id=libro_id, archivos=archivos, metadatos=payload.metadatos,
                                     creado_por=editor["email"])
        except DuplicateKeyError:  # concurrent identical upload won the race
            existing = jobs_collection().find_one({"sha256": digest})
        else:
            return _presigned(jobs.get_job(job_id), storage)

    if existing["estado"] == "fallido":
        # Same bytes again: retry from scratch (checkpoints stay valid, same sha256).
        jobs_collection().update_one({"_id": existing["_id"]}, {"$set": {
            "estado": "esperando_subida", "intentos": 0, "error": None,
            "metadatos": payload.metadatos or existing.get("metadatos") or {},
            "creado_en": datetime.now(timezone.utc)}})
        existing["estado"] = "esperando_subida"
    if existing["estado"] == "esperando_subida":
        return _presigned(existing, storage)

    response.status_code = status.HTTP_200_OK
    return {"id": str(existing["_id"]), "estado": existing["estado"], "libro_id": existing["libro_id"],
            "existente": True, "expira_en": None, "archivos": []}


@router.post("/uploads/{upload_id}/completar", status_code=202, dependencies=[Depends(limit_write), Depends(require_editor)])
def complete_upload(upload_id: str) -> dict:
    """Verifica (HEAD) que cada objeto exista con el tamaño declarado y encola el trabajo."""
    job = jobs.get_job(upload_id)
    if job is None:
        raise HTTPException(404, f"Subida no encontrada: {upload_id}")
    if job["estado"] == "esperando_subida":
        storage = storage_service.get_storage()
        for archivo in job["archivos"]:
            size = storage.size(archivo["clave"])
            if size is None:
                raise HTTPException(409, f"Falta subir {archivo['nombre']}.")
            if size != archivo["tamano"]:
                raise HTTPException(409, f"El tamaño de {archivo['nombre']} ({size}) no coincide "
                                         f"con el declarado ({archivo['tamano']}).")
        jobs_collection().update_one(
            {"_id": job["_id"], "estado": "esperando_subida"},
            {"$set": {"estado": "pendiente", "disponible_desde": datetime.now(timezone.utc)}},
        )
        job = jobs.get_job(upload_id)
    return {"trabajo_id": str(job["_id"]), "estado": job["estado"]}


@router.get("/trabajos/{job_id}")
def get_job_status(job_id: str) -> dict:
    """Estado público del trabajo (sin detalles internos)."""
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, f"Trabajo no encontrado: {job_id}")
    return {
        "id": str(job["_id"]),
        "estado": job["estado"],
        "progreso": job.get("progreso"),
        "intentos": job.get("intentos", 0),
        "error": job.get("error"),
        "libro_id": job["libro_id"] if job["estado"] == "completado" else None,
        "creado_en": job.get("creado_en"),
        "actualizado_en": job.get("actualizado_en"),
    }
