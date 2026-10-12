"""GLM-OCR provider (Z.ai `POST {GLM_API_BASE_URL}/layout_parsing`).

Shape verified 2026-10-11 against docs.z.ai/api-reference/tools/layout-parsing:
request `{"model", "file"}` where `file` is a URL or base64; response
`md_results` (markdown) and `layout_details[page][i]` with `label`, `content`
and `bbox_2d` = normalized [x1, y1, x2, y2]. Errors: `{"code", "message"}`.
"""

from __future__ import annotations

import base64

import httpx

from app.config import get_settings
from app.services.text import clean_markdown_text
from app.services.ocr import OcrPage, OcrRetryableError, raise_for_http

NAME = "glm"
_transport: httpx.BaseTransport | None = None  # tests inject httpx.MockTransport
_TEXT_LABELS = {"text", "formula", "table"}


def missing_config() -> str | None:
    return None if get_settings().glm_api_key else "GLM_API_KEY no está configurada"


def _blocks(details) -> list[dict]:
    blocks = []
    for item in details or []:
        box = item.get("bbox_2d")
        if item.get("label") not in _TEXT_LABELS or not isinstance(box, list) or len(box) != 4:
            continue
        x1, y1, x2, y2 = (float(v) for v in box)
        blocks.append({"texto": str(item.get("content") or ""), "tipo": item["label"], "bbox": None,
                       "bbox_norm": [x1, y1, x2 - x1, y2 - y1]})
    return blocks


def ocr_image(data: bytes, mime: str) -> OcrPage:
    settings = get_settings()
    # ponytail: docs don't say whether a data: prefix is accepted; send raw base64.
    body = {"model": settings.glm_ocr_model, "file": base64.b64encode(data).decode("ascii")}
    try:
        with httpx.Client(transport=_transport, timeout=httpx.Timeout(120, connect=10)) as client:
            response = client.post(f"{settings.glm_api_base_url.rstrip('/')}/layout_parsing", json=body,
                                   headers={"Authorization": f"Bearer {settings.glm_api_key}"})
    except httpx.HTTPError as exc:
        raise OcrRetryableError(f"glm: {exc}") from exc
    if response.status_code != 200:
        raise_for_http(NAME, response.status_code, response.headers, response.text[:500])
    payload = response.json()
    details = (payload.get("layout_details") or [[]])[0]
    texto = clean_markdown_text(payload.get("md_results") or "").strip()
    return OcrPage(numero=None, texto=texto, confianza=None, motor=NAME,
                   modelo=settings.glm_ocr_model, bloques=_blocks(details))
