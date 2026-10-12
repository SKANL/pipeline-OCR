"""Router de extracción: PDF (digital/escaneado) o imágenes -> texto por página.

Decide la ruta según la clasificación de `pdf-inspector`:
- PDF con capa de texto -> extracción local (sin OCR), procedencia `pdf_digital`.
- PDF escaneado/imagen -> OCR con Mistral, procedencia `pdf_escaneado`.
- Conjunto de imágenes -> OCR con Mistral, procedencia `imagenes`.

Cada página conserva su procedencia real: motor que la produjo y, cuando
aplica, la confianza de OCR (nula cuando el texto se extrajo localmente).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.services import ocr as ocr_service
from app.services import pdf_classify
from app.services.naming import natural_key
from app.services.ocr import IMAGE_SUFFIXES
from app.services.text import clean_markdown_text

FUENTE_PDF_DIGITAL = "pdf_digital"
FUENTE_PDF_ESCANEADO = "pdf_escaneado"
FUENTE_IMAGENES = "imagenes"
FUENTE_TEXTO = "texto"

MOTOR_LOCAL = "pdf-inspector"
MOTOR_OCR = "mistral"


@dataclass
class PageExtraction:
    """Texto de una página con su procedencia."""

    numero: int
    texto: str
    ocr_confianza: float | None = None
    motor: str | None = None
    imagen_url: str | None = None


@dataclass
class ExtractionResult:
    """Resultado de extraer un libro completo (PDF o imágenes)."""

    fuente: str
    paginas: list[PageExtraction] = field(default_factory=list)
    motor: str | None = None
    modelo: str | None = None
    confianza_media: float | None = None

    @property
    def textos(self) -> list[str]:
        """Lista de textos de página (compatibilidad con `-> list[str]`)."""
        return [p.texto for p in self.paginas]


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def list_image_paths(paths) -> list[Path]:
    """Filtra y ordena naturalmente las rutas que son imágenes soportadas."""
    images = [Path(p) for p in paths if Path(p).suffix.lower() in IMAGE_SUFFIXES]
    return sorted(images, key=lambda p: natural_key(p.name))


def _extract_pdf_local(path: Path) -> list[PageExtraction]:
    """Extrae texto localmente página a página (PDF con capa de texto).

    El Markdown de `pdf-inspector` se limpia de marcadores para no filtrar
    `#`/`**`/`*` hacia el texto almacenado (solo ruta `pdf_digital`).
    """
    import pdf_inspector

    result = pdf_inspector.extract_pages_markdown(str(path))
    paginas: list[PageExtraction] = []
    for position, page in enumerate(result.pages, start=1):
        numero = page.page + 1 if isinstance(page.page, int) else position
        paginas.append(
            PageExtraction(
                numero=numero,
                texto=clean_markdown_text(page.markdown or ""),
                ocr_confianza=None,
                motor=MOTOR_LOCAL,
            )
        )
    return paginas


def extract_local_pdf_texts(path: str | Path) -> list[str]:
    """Texto por página de un PDF digital (extracción local con pdf-inspector)."""
    return [page.texto for page in _extract_pdf_local(Path(path))]


def extract_from_pdf(path: str | Path) -> ExtractionResult:
    """Extrae las páginas de un PDF eligiendo la ruta digital u OCR."""
    path = Path(path)
    info = pdf_classify.classify_pdf_file(path)

    if pdf_classify.is_text_based(info):
        paginas = _extract_pdf_local(path)
        return ExtractionResult(
            fuente=FUENTE_PDF_DIGITAL,
            paginas=paginas,
            motor=MOTOR_LOCAL,
            modelo=None,
        )

    result = ocr_service.ocr_pdf_file(path)
    paginas = [
        PageExtraction(
            numero=page.numero or index,
            texto=page.texto,
            ocr_confianza=page.confianza,
            motor=page.motor,
        )
        for index, page in enumerate(result.paginas, start=1)
    ]
    confianzas = [p.ocr_confianza for p in paginas if p.ocr_confianza is not None]
    return ExtractionResult(
        fuente=FUENTE_PDF_ESCANEADO,
        paginas=paginas,
        motor=result.motor,
        modelo=result.modelo,
        confianza_media=_average(confianzas),
    )


def extract_from_images(paths) -> ExtractionResult:
    """Ejecuta OCR sobre un conjunto de imágenes (orden natural)."""
    images = list_image_paths(paths)
    if not images:
        raise RuntimeError("No se encontraron imágenes válidas para OCR.")

    result = ocr_service.ocr_images(images)
    paginas = [
        PageExtraction(
            numero=index,
            texto=page.texto,
            ocr_confianza=page.confianza,
            motor=page.motor,
        )
        for index, page in enumerate(result.paginas, start=1)
    ]
    confianzas = [p.ocr_confianza for p in paginas if p.ocr_confianza is not None]
    return ExtractionResult(
        fuente=FUENTE_IMAGENES,
        paginas=paginas,
        motor=result.motor,
        modelo=result.modelo,
        confianza_media=_average(confianzas),
    )
