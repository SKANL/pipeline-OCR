"""Cliente de OCR sobre Mistral Document AI.

Usa el SDK `mistralai` (`client.ocr.process`). Soporta:

- una imagen en bytes o base64 (data URI);
- una lista de imágenes (una operación por imagen);
- un PDF (subida -> URL firmada -> `document_url`).

Devuelve, por página, el texto (markdown), la confianza si la API la
expone y el motor/modelo usados. Todo el acceso a red es defensivo: ante un
fallo se lanza `RuntimeError` (o `OcrNotConfiguredError` si falta la API
key) con contexto para que la ingesta lo registre en `errors[]`.
"""

from __future__ import annotations

import base64
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
MOTOR = "mistral"


class OcrNotConfiguredError(RuntimeError):
    """No hay API key de Mistral pero la fuente exige OCR."""


@dataclass
class OcrPage:
    """Una página devuelta por OCR."""

    numero: int | None
    texto: str
    confianza: float | None = None
    motor: str = MOTOR
    modelo: str | None = None


@dataclass
class OcrResult:
    """Resultado completo de una corrida de OCR."""

    paginas: list[OcrPage] = field(default_factory=list)
    motor: str = MOTOR
    modelo: str | None = None

    @property
    def confianza_media(self) -> float | None:
        values = [p.confianza for p in self.paginas if p.confianza is not None]
        return sum(values) / len(values) if values else None


def is_configured() -> bool:
    """True si hay API key de Mistral configurada."""
    return bool(get_settings().mistral_api_key)


def _client():
    """Construye un cliente Mistral, validando la API key."""
    settings = get_settings()
    if not settings.mistral_api_key:
        raise OcrNotConfiguredError(
            "MISTRAL_API_KEY no está configurada; no se puede ejecutar OCR."
        )
    try:  # mistralai >= 2 expone el cliente bajo `mistralai.client`
        from mistralai.client import Mistral
    except ImportError:  # mistralai 1.x lo exponía en la raíz
        from mistralai import Mistral

    return Mistral(api_key=settings.mistral_api_key)


def _page_confidence(page) -> float | None:
    """Lee la confianza de la página si la API la provee."""
    for attr in ("confidence", "ocr_confidence", "score"):
        value = getattr(page, attr, None)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _to_pages(response, modelo: str) -> list[OcrPage]:
    """Extrae las páginas (texto/confianza) de una respuesta OCR."""
    pages = getattr(response, "pages", None) or []
    result: list[OcrPage] = []
    for position, page in enumerate(pages, start=1):
        texto = getattr(page, "markdown", None)
        if not texto:
            texto = getattr(page, "text", "") or ""
        index = getattr(page, "index", None)
        numero = index + 1 if isinstance(index, int) else position
        result.append(
            OcrPage(
                numero=numero,
                texto=texto,
                confianza=_page_confidence(page),
                motor=MOTOR,
                modelo=modelo,
            )
        )
    return result


def ocr_image_bytes(data: bytes, mime: str = "image/png") -> OcrResult:
    """Ejecuta OCR sobre una imagen en bytes (data URI base64)."""
    settings = get_settings()
    client = _client()
    encoded = base64.b64encode(data).decode("ascii")
    document = {"type": "image_url", "image_url": f"data:{mime};base64,{encoded}"}
    try:
        response = client.ocr.process(model=settings.mistral_ocr_model, document=document)
    except Exception as exc:  # defensivo ante errores de red o API
        raise RuntimeError(f"Error de OCR (imagen): {exc}") from exc
    return OcrResult(paginas=_to_pages(response, settings.mistral_ocr_model), modelo=settings.mistral_ocr_model)


def ocr_image_base64(data_b64: str, mime: str = "image/png") -> OcrResult:
    """Ejecuta OCR sobre una imagen codificada en base64."""
    return ocr_image_bytes(base64.b64decode(data_b64), mime=mime)


def ocr_image_file(path: str | Path) -> OcrResult:
    """Ejecuta OCR sobre un archivo de imagen en disco."""
    path = Path(path)
    mime = IMAGE_SUFFIXES.get(path.suffix.lower())
    if not mime:
        raise RuntimeError(f"Extensión de imagen no soportada: {path.name}")
    return ocr_image_bytes(path.read_bytes(), mime=mime)


def ocr_images(paths) -> OcrResult:
    """Ejecuta OCR sobre varias imágenes en orden natural."""
    ordered = sorted((Path(p) for p in paths), key=lambda p: natural_key(p.name))
    paginas: list[OcrPage] = []
    modelo: str | None = None
    for path in ordered:
        result = ocr_image_file(path)
        modelo = result.modelo
        for page in result.paginas:
            page.numero = len(paginas) + 1
            paginas.append(page)
    return OcrResult(paginas=paginas, modelo=modelo)


def ocr_pdf_bytes(data: bytes, filename: str = "documento.pdf") -> OcrResult:
    """Sube un PDF y ejecuta OCR sobre su URL firmada."""
    settings = get_settings()
    client = _client()
    try:
        uploaded = client.files.upload(
            file={"file_name": filename, "content": data}, purpose="ocr"
        )
        signed = client.files.get_signed_url(file_id=uploaded.id)
        document = {"type": "document_url", "document_url": signed.url}
        response = client.ocr.process(model=settings.mistral_ocr_model, document=document)
    except Exception as exc:  # defensivo ante errores de red o API
        raise RuntimeError(f"Error de OCR (PDF): {exc}") from exc
    return OcrResult(paginas=_to_pages(response, settings.mistral_ocr_model), modelo=settings.mistral_ocr_model)


def ocr_pdf_file(path: str | Path) -> OcrResult:
    """Ejecuta OCR sobre un PDF en disco."""
    path = Path(path)
    return ocr_pdf_bytes(path.read_bytes(), filename=path.name)


def run_ocr_for_book(book_dir: Path) -> list[str]:
    """Compatibilidad: OCR sobre `imagenes/` (orden natural) o `documento.pdf`.

    Devuelve la lista de textos de página. Lanza `RuntimeError` si no hay
    fuente OCR o si la API falla.
    """
    book_dir = Path(book_dir)
    imagenes_dir = book_dir / "imagenes"
    pdf_path = book_dir / "documento.pdf"

    if pdf_path.exists():
        return [p.texto for p in ocr_pdf_file(pdf_path).paginas]

    if imagenes_dir.exists():
        image_paths = [
            p for p in imagenes_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES
        ]
        result = ocr_images(image_paths)
        if result.paginas:
            return [p.texto for p in result.paginas]
        raise RuntimeError(f"No se encontraron imágenes válidas en {imagenes_dir}")

    raise RuntimeError(
        f"OCR solicitado pero el libro no tiene 'imagenes/' ni 'documento.pdf': {book_dir}"
    )
