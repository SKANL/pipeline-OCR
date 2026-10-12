"""Subidas con URL firmada (PUT directo al bucket) y estado de trabajos.

Flujo: `POST /uploads` -> el cliente hace PUT de cada archivo a su URL ->
`POST /uploads/{id}/completar` encola el trabajo -> `GET /trabajos/{id}`.
El id de la subida ES el id del trabajo. Idempotencia por sha256 del
contenido (ver `jobs.upload_digest`).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from pymongo.errors import DuplicateKeyError

from app.config import get_settings
from app.db import jobs_collection
from app.ratelimit import limit_write
from app.security import require_editor
from app.services import jobs, ocr
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
    titulo: str | None = Field(default=None, max_length=300)  # PDF/TXT: title of its own book


class SubidaRequest(BaseModel):
    archivos: list[ArchivoSubida] = Field(min_length=1, max_length=500)
    metadatos: dict | None = None
    ocr_proveedor: str | None = None  # None => OCR_PROVIDER

    @field_validator("ocr_proveedor")
    @classmethod
    def _known_provider(cls, value: str | None) -> str | None:
        return ocr.validate_provider(value)


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
        raise HTTPException(422, "No se pueden mezclar imágenes con documentos (PDF o texto) "
                                 "en una misma subida.")


def _presigned(job: dict, storage) -> dict:
    try:
        urls = [storage.presign_put(a["clave"], a["tipo_contenido"], PUT_EXPIRY) for a in job["archivos"]]
    except NotImplementedError as exc:
        raise HTTPException(501, str(exc)) from exc
    return {
        **_entry(job, existente=False),
        "expira_en": (datetime.now(timezone.utc) + timedelta(seconds=PUT_EXPIRY)).isoformat(),
        "archivos": [
            {"nombre": a["nombre"], "clave": a["clave"], "url": url, "metodo": "PUT",
             "encabezados": {"Content-Type": a["tipo_contenido"]}}
            for a, url in zip(job["archivos"], urls)
        ],
    }


def _entry(job: dict, *, existente: bool) -> dict:
    return {"id": str(job["_id"]), "titulo": jobs.public_status(job)["titulo"], "estado": job["estado"],
            "etapa": jobs.etapa_of(job), "libro_id": job["libro_id"], "existente": existente,
            "expira_en": None, "archivos": []}


def _clean_title(nombre: str) -> str:
    return " ".join(Path(nombre).stem.replace("_", " ").replace("-", " ").split()) or "libro"


def _upload_job(archivos_in: list[ArchivoSubida], titulo: str, metadatos: dict, editor: dict,
                ocr_proveedor: str | None, storage) -> dict:
    """Create (or reuse, by content sha256) one job = one book, and its presigned PUTs."""
    digest = jobs.upload_digest([a.sha256 for a in archivos_in])
    existing = jobs_collection().find_one({"sha256": digest})

    if existing is None:
        libro_id = f"{slugify(titulo) or 'libro'}-{digest[:8]}"
        archivos = [
            {**a.model_dump(exclude={"titulo"}),
             "clave": f"{libro_id}/{i:03d}-{safe_filename(Path(a.nombre).stem)}{jobs.CONTENT_TYPES[a.tipo_contenido][1]}"}
            for i, a in enumerate(archivos_in)
        ]
        try:
            job_id = jobs.create_job(libro_id=libro_id, archivos=archivos, metadatos=metadatos, titulo=titulo,
                                     creado_por=editor["email"], ocr_proveedor=ocr_proveedor)
        except DuplicateKeyError:  # concurrent identical upload won the race
            existing = jobs_collection().find_one({"sha256": digest})
        else:
            return _presigned(jobs.get_job(job_id), storage)

    if existing["estado"] == "fallido":
        # Same bytes again: retry from scratch (checkpoints stay valid, same sha256).
        reset = {"estado": "esperando_subida", "etapa": "subiendo", "intentos": 0, "error": None,
                 "metadatos": metadatos or existing.get("metadatos") or {}, "titulo": titulo,
                 "ocr_proveedor": ocr_proveedor, "creado_en": datetime.now(timezone.utc)}
        jobs_collection().update_one({"_id": existing["_id"]}, {"$set": reset})
        existing.update(reset)
    if existing["estado"] == "esperando_subida":
        return _presigned(existing, storage)
    return _entry(existing, existente=True)


@router.post("/uploads", status_code=201, dependencies=[Depends(limit_write)])
def create_upload(payload: SubidaRequest, response: Response, editor: dict = Depends(require_editor)) -> dict:
    """PDF/TXT: un trabajo (libro) por archivo; imágenes: un libro con las páginas en orden.

    Devuelve `trabajos` (cada uno con sus URLs PUT firmadas, o `existente` si ese
    contenido ya se subió); `id`/`archivos`/... de nivel superior = el primer trabajo.
    """
    _validate(payload.archivos)
    storage = storage_service.get_storage()
    if isinstance(storage, storage_service.LocalStorage):  # cannot presign: fail before creating a job
        raise HTTPException(501, "Presigned uploads require the S3 backend (S3_ENDPOINT_URL).")
    metadatos = dict(payload.metadatos or {})
    single = len(payload.archivos) == 1
    if jobs.CONTENT_TYPES[payload.archivos[0].tipo_contenido][0] == "image":
        titulo = str(metadatos.get("titulo") or _clean_title(payload.archivos[0].nombre))
        groups = [(payload.archivos, titulo)]
    else:
        groups = [([a], a.titulo or (single and metadatos.get("titulo")) or _clean_title(a.nombre))
                  for a in payload.archivos]
    trabajos = [_upload_job(archivos, str(titulo), {**metadatos, "titulo": str(titulo)}, editor,
                            payload.ocr_proveedor, storage)
                for archivos, titulo in groups]
    if all(t["existente"] for t in trabajos):
        response.status_code = status.HTTP_200_OK
    return {**trabajos[0], "trabajos": trabajos}


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
            {"$set": {"estado": "pendiente", "etapa": "en_espera", "disponible_desde": datetime.now(timezone.utc)}},
        )
        job = jobs.get_job(upload_id)
    return {"trabajo_id": str(job["_id"]), "estado": job["estado"]}


@router.get("/trabajos")
def list_jobs(limit: int = Query(20, ge=1, le=100), editor: dict = Depends(require_editor)) -> list[dict]:
    """Trabajos recientes del editor (admin: todos), del más nuevo al más viejo."""
    query = {} if editor["rol"] == "admin" else {"creado_por": editor["email"]}
    cursor = jobs_collection().find(query).sort([("creado_en", -1), ("_id", -1)]).limit(limit)
    return [jobs.public_status(job) for job in cursor]


@router.get("/trabajos/{job_id}")
def get_job_status(job_id: str) -> dict:
    """Estado público del trabajo (sin detalles internos)."""
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, f"Trabajo no encontrado: {job_id}")
    return jobs.public_status(job)
