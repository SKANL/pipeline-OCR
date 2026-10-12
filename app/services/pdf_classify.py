"""Clasificación de PDF con `pdf-inspector`.

Envoltorio fino sobre la detección rápida de la librería. No extrae texto:
solo decide si un PDF tiene capa de texto (extraíble localmente) o si hay
que rutear sus páginas a OCR.

API de pdf-inspector usada:
- `pdf_inspector.detect_pdf(path)` -> PdfResult
  (`.pdf_type`, `.confidence`, `.pages_needing_ocr` 1-indexed,
   `.has_encoding_issues`, `.page_count`)
- `pdf_inspector.detect_pdf_bytes(data)` -> PdfResult

La importación es diferida para que el resto del pipeline pueda importarse
y testearse incluso si la extensión nativa no está disponible.
"""

from __future__ import annotations

from pathlib import Path

# Tipos de pdf-inspector que consideramos con capa de texto nativa.
TEXT_BASED = "text_based"


def _normalize(result) -> dict:
    tipo = str(getattr(result, "pdf_type", "") or "")
    confianza = float(getattr(result, "confidence", 0.0) or 0.0)
    paginas_ocr = list(getattr(result, "pages_needing_ocr", None) or [])
    return {
        "tipo": tipo,
        "confianza": confianza,
        "paginas_ocr": paginas_ocr,
        "paginas": int(getattr(result, "page_count", 0) or 0),
        "encoding_issues": bool(getattr(result, "has_encoding_issues", False)),
    }


def classify_pdf_file(path: str | Path) -> dict:
    """Clasifica un PDF en disco. Devuelve `{tipo, confianza, paginas_ocr, ...}`."""
    import pdf_inspector

    return _normalize(pdf_inspector.detect_pdf(str(path)))


def classify_pdf_bytes(data: bytes) -> dict:
    """Clasifica un PDF en memoria (sin escribir en disco)."""
    import pdf_inspector

    return _normalize(pdf_inspector.detect_pdf_bytes(data))


def is_text_based(info: dict) -> bool:
    """True si el PDF puede extraerse localmente sin OCR.

    Un PDF con fuente rota (`encoding_issues`) se considera no confiable y
    se rutea a OCR aunque su tipo reportado sea `text_based`.
    """
    return info.get("tipo") == TEXT_BASED and not info.get("encoding_issues")
