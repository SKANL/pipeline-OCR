"""OCR facade: one small provider contract + a registry (Tesseract, Mistral, GLM-OCR).

Provider contract (a module or any object exposing):

- `NAME: str` — stored as the page `motor`;
- `missing_config() -> str | None` — why it cannot run here (None = ready);
- `ocr_image(data: bytes, mime: str) -> OcrPage` — one page image;
- optional `ocr_pdf(path) -> list[OcrPage]` — native PDF path (Mistral);
  without it the facade renders each PDF page to PNG and calls `ocr_image`.

Adding a provider: write `app/services/ocr_<name>.py` with that contract,
add one line to `PROVIDERS`, add its settings to `config.py`.

The active provider is `OCR_PROVIDER`, overridable per job with
`use_provider(name)` (the job's `ocr_proveedor`).
"""

from __future__ import annotations

import base64
import importlib
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

from app.config import get_settings
from app.services.naming import natural_key

IMAGE_SUFFIXES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class OcrPermanentError(RuntimeError):
    """Retrying cannot help (bad key, plan without OCR, rejected input)."""


class OcrNotConfiguredError(OcrPermanentError):
    """The active provider is not usable on this server but the source needs OCR."""


class OcrRetryableError(RuntimeError):
    """Transient provider failure (rate limit, 5xx, network)."""


@dataclass
class OcrPage:
    """One OCR'd page. `bloques` carry `bbox_norm` = [nx, ny, nw, nh], top-left origin."""

    numero: int | None
    texto: str
    confianza: float | None = None
    motor: str = ""
    modelo: str | None = None
    bloques: list[dict] = field(default_factory=list)


@dataclass
class OcrResult:
    paginas: list[OcrPage] = field(default_factory=list)
    motor: str | None = None
    modelo: str | None = None

    @property
    def confianza_media(self) -> float | None:
        values = [p.confianza for p in self.paginas if p.confianza is not None]
        return sum(values) / len(values) if values else None


def _lazy(module: str):
    return lambda: importlib.import_module(f"app.services.{module}")


# Registry: name -> factory returning the provider.
PROVIDERS = {
    "tesseract": _lazy("ocr_tesseract"),
    "mistral": _lazy("ocr_mistral"),
    "glm": _lazy("ocr_glm"),
}

_override: ContextVar[str | None] = ContextVar("ocr_provider_override", default=None)


def validate_provider(name: str | None) -> str | None:
    """Normalize an optional provider name; ValueError if not registered."""
    if name is None or name == "":
        return None
    if name not in PROVIDERS:
        raise ValueError(f"Proveedor de OCR desconocido: {name} (admitidos: {', '.join(PROVIDERS)}).")
    return name


def provider_name() -> str:
    return _override.get() or get_settings().ocr_provider


@contextmanager
def use_provider(name: str | None):
    """Run a block with another provider (None keeps the configured one)."""
    token = _override.set(validate_provider(name))
    try:
        yield
    finally:
        _override.reset(token)


def get_provider():
    name = provider_name()
    if name not in PROVIDERS:
        raise OcrNotConfiguredError(f"OCR_PROVIDER desconocido: {name}")
    return PROVIDERS[name]()


def is_configured() -> bool:
    try:
        return get_provider().missing_config() is None
    except OcrNotConfiguredError:
        return False


def require_configured():
    provider = get_provider()
    reason = provider.missing_config()
    if reason:
        raise OcrNotConfiguredError(f"OCR '{provider.NAME}' no disponible: {reason}")
    return provider


def raise_for_http(provider: str, status: int | None, headers, detail: str) -> None:
    """Map an HTTP failure to permanent vs retryable (shared by HTTP providers)."""
    headers = {str(k).lower(): str(v) for k, v in dict(headers or {}).items()}
    if status == 429 and headers.get("x-ratelimit-limit-req-minute") == "0":
        raise OcrPermanentError(f"{provider}: plan sin OCR habilitado (límite 0 req/min). {detail}")
    if status in (400, 401, 403, 404, 413, 422):
        raise OcrPermanentError(f"{provider}: HTTP {status}: {detail}")
    raise OcrRetryableError(f"{provider}: HTTP {status}: {detail}")


def _result(pages: list[OcrPage]) -> OcrResult:
    first = pages[0] if pages else None
    return OcrResult(paginas=pages, motor=first.motor if first else None, modelo=first.modelo if first else None)


def ocr_image_bytes(data: bytes, mime: str = "image/png") -> OcrResult:
    return _result([require_configured().ocr_image(data, mime)])


def ocr_image_base64(data_b64: str, mime: str = "image/png") -> OcrResult:
    return ocr_image_bytes(base64.b64decode(data_b64), mime=mime)


def ocr_image_file(path: str | Path) -> OcrResult:
    path = Path(path)
    mime = IMAGE_SUFFIXES.get(path.suffix.lower())
    if not mime:
        raise OcrPermanentError(f"Extensión de imagen no soportada: {path.name}")
    return ocr_image_bytes(path.read_bytes(), mime=mime)


def ocr_images(paths) -> OcrResult:
    """OCR several images in natural order (pages renumbered 1..n)."""
    ordered = sorted((Path(p) for p in paths), key=lambda p: natural_key(p.name))
    pages: list[OcrPage] = []
    for path in ordered:
        for page in ocr_image_file(path).paginas:
            page.numero = len(pages) + 1
            pages.append(page)
    return _result(pages)


def ocr_pdf_file(path: str | Path) -> OcrResult:
    """OCR a scanned PDF: native provider path, else render each page to PNG."""
    from app.services import render

    path = Path(path)
    provider = require_configured()
    if hasattr(provider, "ocr_pdf"):
        return _result(provider.ocr_pdf(path))
    dpi = get_settings().ocr_dpi
    pages = []
    for index in range(render.pdf_page_count(path)):
        page = provider.ocr_image(render.render_pdf_page(path, index, dpi=dpi), "image/png")
        page.numero = index + 1
        pages.append(page)
    return _result(pages)


def run_ocr_for_book(book_dir: Path) -> list[str]:
    """Compatibility: OCR `documento.pdf` or `imagenes/` (natural order)."""
    book_dir = Path(book_dir)
    pdf_path, imagenes_dir = book_dir / "documento.pdf", book_dir / "imagenes"
    if pdf_path.exists():
        return [p.texto for p in ocr_pdf_file(pdf_path).paginas]
    if imagenes_dir.exists():
        result = ocr_images([p for p in imagenes_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES])
        if result.paginas:
            return [p.texto for p in result.paginas]
        raise RuntimeError(f"No se encontraron imágenes válidas en {imagenes_dir}")
    raise RuntimeError(f"OCR solicitado pero el libro no tiene 'imagenes/' ni 'documento.pdf': {book_dir}")
