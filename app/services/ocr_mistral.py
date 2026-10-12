"""Mistral Document AI OCR provider (SDK `mistralai`, `client.ocr.process`)."""

from __future__ import annotations

import base64
from pathlib import Path

from app.config import get_settings
from app.services.ocr import OcrPage, OcrRetryableError, raise_for_http

NAME = "mistral"


def missing_config() -> str | None:
    return None if get_settings().mistral_api_key else "MISTRAL_API_KEY no está configurada"


def _client():
    try:  # mistralai >= 2 exposes the client under `mistralai.client`
        from mistralai.client import Mistral
    except ImportError:
        from mistralai import Mistral
    return Mistral(api_key=get_settings().mistral_api_key)


def _page_confidence(page) -> float | None:
    for attr in ("confidence", "ocr_confidence", "score"):
        value = getattr(page, attr, None)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _to_pages(response, modelo: str) -> list[OcrPage]:
    result = []
    for position, page in enumerate(getattr(response, "pages", None) or [], start=1):
        texto = getattr(page, "markdown", None) or getattr(page, "text", "") or ""
        index = getattr(page, "index", None)
        result.append(OcrPage(numero=index + 1 if isinstance(index, int) else position, texto=texto,
                              confianza=_page_confidence(page), motor=NAME, modelo=modelo))
    return result


def _call(fn, what: str):
    try:
        return fn()
    except Exception as exc:  # SDK/network errors: classify by status when present
        status = getattr(exc, "status_code", None)
        if status is None:
            raise OcrRetryableError(f"mistral ({what}): {exc}") from exc
        headers = getattr(getattr(exc, "raw_response", None), "headers", None)
        raise_for_http(NAME, status, headers, f"({what}) {exc}")


def ocr_image(data: bytes, mime: str) -> OcrPage:
    model = get_settings().mistral_ocr_model
    client = _client()
    document = {"type": "image_url", "image_url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"}
    response = _call(lambda: client.ocr.process(model=model, document=document), "imagen")
    pages = _to_pages(response, model)
    return pages[0] if pages else OcrPage(numero=None, texto="", motor=NAME, modelo=model)


def ocr_pdf(path: Path) -> list[OcrPage]:
    """Upload -> signed URL -> `document_url` (unchanged pre-registry behavior)."""
    model = get_settings().mistral_ocr_model
    client = _client()

    def run():
        uploaded = client.files.upload(file={"file_name": path.name, "content": path.read_bytes()}, purpose="ocr")
        signed = client.files.get_signed_url(file_id=uploaded.id)
        return client.ocr.process(model=model, document={"type": "document_url", "document_url": signed.url})

    return _to_pages(_call(run, "PDF"), model)
