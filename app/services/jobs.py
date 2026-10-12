"""Mongo-backed ingest job queue with an in-process worker.

Render free has no separate workers and sleeps after 15 min without inbound
HTTP, so the queue lives in Mongo (`trabajos`) and one background thread per
API instance drains it:

- claim: atomic `find_one_and_update` of a `pendiente` job whose backoff has
  elapsed, or a `procesando` job whose lease (`bloqueado_hasta`) expired
  because the instance slept or crashed. Each claim counts one attempt.
- heartbeat: after every page the lease is extended and `progreso` updated;
  a worker that lost its lease stops (`LeaseLost`).
- retries: transient errors go back to `pendiente` with exponential backoff
  plus jitter; only `PermanentJobError`/`OcrPermanentError` are permanent; after
  `max_intentos` the job is `fallido` with a public-safe `error`.
- checkpoints: every finished page is stored in `trabajo_paginas`, so a retry
  skips pages already done; the book is assembled and persisted at the end.
  One page is processed at a time (a one-page PDF is cut per page).
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import socket
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument

from app.db import books_collection, job_pages_collection, jobs_collection
from app.services import ingest, pdf_classify, render, structure
from app.services import storage as storage_service
from app.services.extract import FUENTE_PDF_ESCANEADO, FUENTE_TEXTO
from app.services import ocr
from app.services.ocr import OcrNotConfiguredError, OcrPermanentError

logger = logging.getLogger(__name__)

LEASE = timedelta(minutes=5)  # ponytail: per-page heartbeat; a single page must finish within it
MAX_INTENTOS = 5
BACKOFF_BASE = 30.0  # seconds
BACKOFF_CAP = 3600.0
POLL_MIN, POLL_MAX = 2.0, 60.0  # idle polling backoff (seconds)

# tipo_contenido -> (kind, extension used for the stored key)
CONTENT_TYPES = {
    "application/pdf": ("pdf", ".pdf"),
    "image/jpeg": ("image", ".jpg"),
    "image/png": ("image", ".png"),
    "image/webp": ("image", ".webp"),
    "text/plain": ("txt", ".txt"),
}

_INTERNAL_ERROR = "Error interno al procesar el libro."


class LeaseLost(Exception):
    """Another worker owns the job now (our lease expired)."""


class PermanentJobError(Exception):
    """Retrying cannot help (bad input); the message is shown to the user."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def backoff_seconds(intentos: int) -> float:
    """Exponential backoff with jitter: base * 2^(n-1) * [1, 2), capped."""
    return min(BACKOFF_BASE * 2 ** (intentos - 1) * (1 + random.random()), BACKOFF_CAP)


def upload_digest(sha256s: list[str]) -> str:
    """Idempotency key: the file's sha256, or sha256 of the ordered file hashes."""
    if len(sha256s) == 1:
        return sha256s[0]
    return hashlib.sha256("\n".join(sha256s).encode()).hexdigest()


def create_job(*, libro_id: str, archivos: list[dict], metadatos: dict | None,
               estado: str = "esperando_subida", creado_por: str | None = None,
               ocr_proveedor: str | None = None) -> str:
    """Insert a job; `archivos` carry nombre/tipo_contenido/tamano/sha256/clave."""
    now = _now()
    result = jobs_collection().insert_one({
        "tipo": "ingesta",
        "estado": estado,
        "libro_id": libro_id,
        "archivos": archivos,
        "metadatos": metadatos or {},
        "ocr_proveedor": ocr_proveedor,
        "sha256": upload_digest([a["sha256"] for a in archivos]),
        "intentos": 0,
        "max_intentos": MAX_INTENTOS,
        "disponible_desde": now,
        "bloqueado_hasta": None,
        "worker_id": None,
        "progreso": {"paginas_hechas": 0, "paginas_total": None},
        "error": None,
        "creado_por": creado_por,
        "creado_en": now,
        "actualizado_en": now,
    })
    return str(result.inserted_id)


def get_job(job_id: str) -> dict | None:
    try:
        return jobs_collection().find_one({"_id": ObjectId(job_id)})
    except (InvalidId, TypeError):
        return None


def claim(worker_id: str) -> dict | None:
    """Atomically take the next runnable job (or one whose lease expired)."""
    now = _now()
    return jobs_collection().find_one_and_update(
        {
            "$or": [
                {"estado": "pendiente", "disponible_desde": {"$lte": now}},
                {"estado": "procesando", "bloqueado_hasta": {"$lt": now}},
            ],
            "$expr": {"$lt": ["$intentos", "$max_intentos"]},
        },
        {
            "$set": {"estado": "procesando", "worker_id": worker_id,
                     "bloqueado_hasta": now + LEASE, "actualizado_en": now},
            "$inc": {"intentos": 1},
        },
        sort=[("disponible_desde", 1)],
        return_document=ReturnDocument.AFTER,
    )


def _owned(job: dict) -> dict:
    return {"_id": job["_id"], "worker_id": job["worker_id"], "estado": "procesando"}


def heartbeat(job: dict, *, paginas_hechas: int, paginas_total: int) -> None:
    """Extend the lease and record progress; raise `LeaseLost` if not ours."""
    now = _now()
    result = jobs_collection().update_one(_owned(job), {"$set": {
        "bloqueado_hasta": now + LEASE, "actualizado_en": now,
        "progreso": {"paginas_hechas": paginas_hechas, "paginas_total": paginas_total},
    }})
    if result.matched_count == 0:
        raise LeaseLost(str(job["_id"]))


def is_permanent(exc: Exception) -> bool:
    """Bad input or unusable OCR provider: retrying cannot help."""
    return isinstance(exc, (PermanentJobError, OcrPermanentError))


def fail(job: dict, exc: Exception) -> None:
    """Record a failure: retry later with backoff, or `fallido` when exhausted/permanent."""
    now = _now()
    permanent = is_permanent(exc)
    if isinstance(exc, PermanentJobError):
        public = str(exc)
    elif isinstance(exc, OcrNotConfiguredError):
        public = "El libro requiere OCR y el OCR no está disponible en este servidor."
    elif isinstance(exc, OcrPermanentError):
        public = f"Fallo permanente del OCR: {exc}"
    else:
        public = _INTERNAL_ERROR
    update = {"error": public, "error_interno": repr(exc)[:2000], "actualizado_en": now,
              "bloqueado_hasta": None}
    if permanent or job["intentos"] >= job["max_intentos"]:
        update["estado"] = "fallido"
    else:
        update["estado"] = "pendiente"
        update["disponible_desde"] = now + timedelta(seconds=backoff_seconds(job["intentos"]))
    jobs_collection().update_one(_owned(job), {"$set": update})


def complete(job: dict, *, paginas: int) -> None:
    result = jobs_collection().update_one(_owned(job), {"$set": {
        "estado": "completado", "error": None, "bloqueado_hasta": None, "actualizado_en": _now(),
        "progreso": {"paginas_hechas": paginas, "paginas_total": paginas},
    }})
    if result.matched_count == 0:
        raise LeaseLost(str(job["_id"]))


def _sweep_exhausted() -> None:
    """Jobs whose lease expired with no attempts left (crash loop) become `fallido`."""
    now = _now()
    jobs_collection().update_many(
        {"estado": "procesando", "bloqueado_hasta": {"$lt": now},
         "$expr": {"$gte": ["$intentos", "$max_intentos"]}},
        {"$set": {"estado": "fallido", "bloqueado_hasta": None, "actualizado_en": now,
                  "error": "El procesamiento se interrumpió demasiadas veces."}},
    )


# --------------------------------------------------------------------------
# Processing (reuses the ingest builders one page at a time)
# --------------------------------------------------------------------------
def _page_count(kind: str, path: Path) -> int:
    if kind == "pdf":
        return render.pdf_page_count(path)
    if kind == "txt":
        return len(path.read_text(encoding="utf-8").split("\f"))
    return 1


def _structure(path: Path, cache: dict) -> dict:
    """opendataloader output for a whole original PDF, computed once (one JVM).

    ponytail: kept in memory for the job; a huge PDF's JSON is the ceiling
    (batch by page ranges if that ever matters on 512 MB).
    """
    if path not in cache:
        cache[path] = structure.extract_structure(path)
    return cache[path]


def _extract_page(kind: str, path: Path, local: int, numero: int, libro_id: str, storage,
                  odl_cache: dict | None = None) -> dict:
    """Extract page `local` of `path` as book page `numero` via the shared builders.

    With `odl_cache`, opendataloader runs once per original PDF and each page
    reuses its slice; without it, the one-page PDF is analysed on its own.
    """
    if kind == "txt":
        texto = path.read_text(encoding="utf-8").split("\f")[local]
        return {"pages": [{"texto": texto, "motor": FUENTE_TEXTO}], "fuente": FUENTE_TEXTO,
                "motor": None, "modelo": None}
    if kind == "image":
        ingest._require_ocr_if_needed(needs_ocr=True)
        source = ingest._ImageSource(path=path, data=path.read_bytes(), suffix=path.suffix.lower())
        return ingest._extract_image_source([source], libro_id, [], storage, first_page=numero)

    import pypdfium2 as pdfium

    with tempfile.TemporaryDirectory() as tmp:
        one = Path(tmp) / "pagina.pdf"
        src, dst = pdfium.PdfDocument(str(path)), pdfium.PdfDocument.new()
        try:
            dst.import_pages(src, [local])
            dst.save(str(one))
        finally:
            dst.close()
            src.close()
        text_based = pdf_classify.is_text_based(pdf_classify.classify_pdf_file(one))
        ingest._require_ocr_if_needed(needs_ocr=not text_based)
        structures = None
        if odl_cache is not None:
            arch = _structure(path, odl_cache)
            structures = {one: {key: {1: arch[key].get(local + 1, [])} for key in ("bloques", "figuras")}}
        return ingest._extract_pdf_source([one], libro_id, [], storage, first_page=numero, structures=structures)


def process(job: dict) -> int:
    """Process a claimed job under its OCR provider (`ocr_proveedor`, else OCR_PROVIDER)."""
    with ocr.use_provider(job.get("ocr_proveedor")):
        return _process_pages(job)


def _process_pages(job: dict) -> int:
    """Process a claimed job page by page with checkpoints; return the page count."""
    storage = storage_service.get_storage()
    archivos = job["archivos"]
    kinds = {CONTENT_TYPES[a["tipo_contenido"]][0] for a in archivos}
    if len(kinds) != 1:
        raise PermanentJobError("Todos los archivos de un libro deben ser del mismo tipo.")
    kind = kinds.pop()

    paths = []
    for archivo in archivos:
        path = storage.path(archivo["clave"])
        with path.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != archivo["sha256"]:
                raise PermanentJobError(f"El archivo {archivo['nombre']} no coincide con su sha256 declarado.")
        paths.append(path)

    counts = [_page_count(kind, path) for path in paths]
    total = sum(counts)
    if total == 0:
        raise PermanentJobError("Los archivos no contienen páginas.")

    checkpoints = job_pages_collection()
    done = {c["numero"] for c in checkpoints.find({"trabajo_id": job["_id"]}, {"numero": 1})}
    heartbeat(job, paginas_hechas=len(done), paginas_total=total)
    numero = 0
    odl_cache: dict = {}
    for path, count in zip(paths, counts):
        for local in range(count):
            numero += 1
            if numero in done:
                continue
            result = _extract_page(kind, path, local, numero, job["libro_id"], storage, odl_cache=odl_cache)
            pagina = result["pages"][0]
            pagina["numero"] = numero
            # Still ours (not deleted/stolen) before writing the checkpoint.
            heartbeat(job, paginas_hechas=len(done), paginas_total=total)
            checkpoints.update_one(
                {"trabajo_id": job["_id"], "numero": numero},
                {"$set": {"pagina": pagina, "fuente": result["fuente"],
                          "motor": result["motor"], "modelo": result["modelo"]}},
                upsert=True,
            )
            done.add(numero)
            heartbeat(job, paginas_hechas=len(done), paginas_total=total)

    cps = list(checkpoints.find({"trabajo_id": job["_id"]}).sort("numero", 1))
    pages = ingest._pages_from_extraction([c["pagina"] for c in cps], [])
    fuentes = [c["fuente"] for c in cps]
    metadatos = {"titulo": Path(archivos[0]["nombre"]).stem, **(job.get("metadatos") or {})}
    libro = ingest._assemble_libro(
        libro_id=job["libro_id"],
        metadatos=ingest._metadatos_from(metadatos),
        capitulos=[],
        pages=pages,
        fuente=FUENTE_PDF_ESCANEADO if FUENTE_PDF_ESCANEADO in fuentes else fuentes[0],
        motor=next((c["motor"] for c in reversed(cps) if c.get("motor")), None),
        modelo=next((c["modelo"] for c in reversed(cps) if c.get("modelo")), None),
        confianza_media=ingest._average([p["ocr_confianza"] for p in pages if p.get("ocr_confianza") is not None]),
        origen=[a["nombre"] for a in archivos],
    )
    if job.get("creado_por"):
        libro["creado_por"] = job["creado_por"]
    # ponytail: re-check the lease right before writing; a steal inside _persist itself still races.
    heartbeat(job, paginas_hechas=total, paginas_total=total)
    ingest._persist(libro, storage, originals=[a["clave"] for a in archivos])
    checkpoints.delete_many({"trabajo_id": job["_id"]})
    return total


def _discard_deleted(job: dict) -> None:
    """The book was deleted mid-job: drop checkpoints and media written since."""
    logger.warning("Job %s was deleted while processing; discarding its output", job["_id"])
    job_pages_collection().delete_many({"trabajo_id": job["_id"]})
    if books_collection().find_one({"libro_id": job["libro_id"]}, {"_id": 1}) is None:
        storage_service.get_storage().delete_prefix(f"{job['libro_id']}/")


def run_once(worker_id: str) -> bool:
    """Claim and process one job. Returns False when there was nothing to do."""
    _sweep_exhausted()
    job = claim(worker_id)
    if job is None:
        return False
    try:
        complete(job, paginas=process(job))
    except LeaseLost:
        if jobs_collection().find_one({"_id": job["_id"]}, {"_id": 1}) is None:
            _discard_deleted(job)
        else:
            logger.warning("Lease lost for job %s; another worker continues it", job["_id"])
    except Exception as exc:  # noqa: BLE001 - recorded on the job
        logger.exception("Job %s failed (attempt %s)", job["_id"], job["intentos"])
        fail(job, exc)
    return True


class Worker:
    """One polling thread per API instance (ponytail: the throughput ceiling).

    Idle polling backs off from POLL_MIN to POLL_MAX. `stop()` ends the loop
    between jobs; a job interrupted by shutdown resumes after its lease expires.
    """

    def __init__(self) -> None:
        self.worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="job-worker", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self.thread.join(timeout)

    def _loop(self) -> None:
        idle = POLL_MIN
        while not self._stop.is_set():
            try:
                worked = run_once(self.worker_id)
            except Exception:  # noqa: BLE001 - e.g. Mongo unreachable; keep polling
                logger.exception("Job worker iteration failed")
                worked = False
            if worked:
                idle = POLL_MIN
                continue
            self._stop.wait(idle)
            idle = min(idle * 2, POLL_MAX)
