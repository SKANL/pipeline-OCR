"""Aplicación FastAPI de la Biblioteca Virtual Eclesiástica."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db import ensure_indexes
from app.routers import books, citations, editors, ingest, jobs, search, upload
from app.services.jobs import Worker
from app.services.storage import LocalStorage, get_storage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Crea los índices y arranca el worker de la cola (si `WORKER_ENABLED`).

    Si Mongo no responde, el arranque sigue (el worker reintenta solo).
    """
    try:
        ensure_indexes()
    except Exception as exc:  # noqa: BLE001 - el boot no debe fallar sin Mongo
        logger.warning("No se pudieron crear los índices al arrancar: %s", exc)
    settings = get_settings()
    if not settings.api_key and not settings.auth_secret:
        logger.warning("Neither API_KEY nor AUTH_SECRET is set: write endpoints are OPEN (dev mode).")
    worker = Worker() if get_settings().worker_enabled else None
    if worker:
        worker.start()
    yield
    if worker:
        worker.stop()


app = FastAPI(
    lifespan=lifespan,
    title="Biblioteca Virtual Eclesiástica",
    description="BUSCAR -> LEER -> CITAR: API de ingesta, búsqueda y citación.",
    version="0.1.0",
)

# CORS mínimo para la PWA en Vercel: solo los orígenes configurados pueden
# llamar a la API desde el navegador. Sin credenciales (no usamos cookies) y
# solo los métodos/cabeceras que la app necesita; `Authorization` (token del
# editor) o `X-API-Key` (scripts de operación) habilitan las escrituras.
_settings = get_settings()
_origins = [origin.strip() for origin in _settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
    allow_credentials=False,
)

API_PREFIX = "/api/v1"

app.include_router(ingest.router, prefix=API_PREFIX)
app.include_router(upload.router, prefix=API_PREFIX)
app.include_router(jobs.router, prefix=API_PREFIX)
app.include_router(search.router, prefix=API_PREFIX)
app.include_router(books.router, prefix=API_PREFIX)
app.include_router(citations.router, prefix=API_PREFIX)
app.include_router(editors.router, prefix=API_PREFIX)

# `/media` solo existe con el backend local; con S3 las URLs apuntan al bucket.
if isinstance(get_storage(), LocalStorage):
    _media_root = Path(get_settings().media_root)
    _media_root.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(_media_root)), name="media")


@app.get("/health", tags=["health"])
def health() -> dict:
    """Chequeo de salud simple."""
    return {"status": "ok"}
