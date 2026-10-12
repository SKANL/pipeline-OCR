"""Renderizado de páginas de PDF a PNG con `pypdfium2`.

`pypdfium2` empaqueta PDFium (sin dependencias del sistema) y permite
renderizar una página a un bitmap que se guarda como PNG. Se usa para que
cada página almacenada cargue su imagen y así poder verificar el texto
contra el escaneo original.

API usada:
- `pypdfium2.PdfDocument(path)` -> documento; `len(doc)` cuenta páginas.
- `doc[page_index].render(scale=dpi/72)` -> bitmap; `.to_pil()` lo convierte.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import math

from app.services.structure import _valid_bbox

DEFAULT_DPI = 150


def pdf_page_geometry(pdf_path: str | Path, page_index: int) -> tuple[float, float]:
    """Guard converter coordinates: only unrotated, zero-origin page boxes.

    PDFium renders rotation/crop correctly, but converter coordinate transforms
    are not established for those cases. Keep the original image, skip crops and
    overlays explicitly rather than guessing a transform.
    """
    import pypdfium2 as pdfium

    with pdfium.PdfDocument(str(pdf_path)) as document:
        page = document[page_index]
        try:
            width, height = page.get_size()
            box = page.get_bbox()
            if page.get_rotation() != 0 or any(
                not math.isclose(actual, expected, abs_tol=0.01)
                for actual, expected in zip(box, (0, 0, width, height))
            ):
                raise ValueError("Unsupported rotated or shifted crop/media box; use original page")
            return float(width), float(height)
        finally:
            page.close()


def crop_page_png(data: bytes, bbox_pt: list[float], width_pt: float, height_pt: float) -> bytes:
    """Crop a previously rendered page using actual pixel dimensions."""
    from PIL import Image

    if not _valid_bbox(bbox_pt) or not all(math.isfinite(v) and v > 0 for v in (width_pt, height_pt)):
        raise ValueError("Invalid figure or page dimensions")
    left, bottom, right, top = bbox_pt
    if left < 0 or bottom < 0 or right > width_pt or top > height_pt:
        raise ValueError("Figure box outside rendered page; use original page")
    with Image.open(BytesIO(data)) as image:
        bounds = (math.floor(left / width_pt * image.width),
                  math.floor((height_pt - top) / height_pt * image.height),
                  math.ceil(right / width_pt * image.width),
                  math.ceil((height_pt - bottom) / height_pt * image.height))
        cropped = image.crop(bounds)
        buffer = BytesIO()
        cropped.save(buffer, format="PNG")
        return buffer.getvalue()


def pdf_page_count(pdf_path: str | Path) -> int:
    """Cantidad de páginas del PDF."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(pdf_path))
    try:
        return len(document)
    finally:
        document.close()


def pdf_page_size(pdf_path: str | Path, page_index: int) -> tuple[float, float]:
    """Devuelve `(width_pt, height_pt)` de una página (0-indexada).

    Las medidas están en puntos PDF (1/72 pulgada) e incluyen el page box
    completo, que es exactamente el área que cubre la imagen renderizada.
    Se usa para normalizar los bounding boxes de los bloques a fracciones.
    """
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(pdf_path))
    try:
        page = document[page_index]
        try:
            width, height = page.get_size()
            return float(width), float(height)
        finally:
            page.close()
    finally:
        document.close()


def render_pdf_page(pdf_path: str | Path, page_index: int, dpi: int = DEFAULT_DPI) -> bytes:
    """Renderiza una página (0-indexada) del PDF y devuelve un PNG en bytes."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(pdf_path))
    try:
        page = document[page_index]
        try:
            bitmap = page.render(scale=dpi / 72)
            try:
                image = bitmap.to_pil()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def render_pdf_region(
    pdf_path: str | Path,
    page_index: int,
    bbox_pt: list[float],
    dpi: int = DEFAULT_DPI,
) -> bytes:
    """Renderiza SOLO la región `bbox_pt` ([left,bottom,right,top], puntos) en PNG.

    Se usa para recortar figuras/imágenes de una página. Lanza `ValueError` si
    la región es inválida (vacía o fuera de la página).
    """
    width_pt, height_pt = pdf_page_geometry(pdf_path, page_index)
    return crop_page_png(render_pdf_page(pdf_path, page_index, dpi), bbox_pt, width_pt, height_pt)
