"""Tesseract OCR provider (local binary via `pytesseract`; languages from OCR_LANGS)."""

from __future__ import annotations

import io
import shutil

from app.config import get_settings
from app.services.ocr import OcrPage, OcrPermanentError

NAME = "tesseract"


def missing_config() -> str | None:
    import pytesseract

    if shutil.which(pytesseract.pytesseract.tesseract_cmd) is None:
        return "el binario 'tesseract' no está instalado"
    return None


def _image_to_data(image, lang: str) -> dict:
    import pytesseract

    try:
        return pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractError as exc:  # e.g. missing traineddata: retrying won't help
        raise OcrPermanentError(f"tesseract: {exc}") from exc


def ocr_image(data: bytes, mime: str) -> OcrPage:
    from PIL import Image

    lang = get_settings().ocr_langs
    with Image.open(io.BytesIO(data)) as image:
        width, height = image.size
        words = _image_to_data(image.convert("L"), lang)

    lines: dict[tuple, list[int]] = {}
    for i, text in enumerate(words["text"]):
        if str(text).strip() and float(words["conf"][i]) >= 0:
            lines.setdefault((words["block_num"][i], words["par_num"][i], words["line_num"][i]), []).append(i)

    blocks, texto, previous_par, confs = [], "", None, []
    for (block, par, _line), ids in lines.items():
        line = " ".join(str(words["text"][i]).strip() for i in ids)
        confs += [float(words["conf"][i]) for i in ids]
        if previous_par is not None:
            texto += "\n" if (block, par) == previous_par else "\n\n"
        texto += line
        previous_par = (block, par)
        x0 = min(words["left"][i] for i in ids)
        y0 = min(words["top"][i] for i in ids)
        x1 = max(words["left"][i] + words["width"][i] for i in ids)
        y1 = max(words["top"][i] + words["height"][i] for i in ids)
        blocks.append({"texto": line, "tipo": "linea", "bbox": None,
                       "bbox_norm": [x0 / width, y0 / height, (x1 - x0) / width, (y1 - y0) / height]})
    confianza = sum(confs) / len(confs) / 100 if confs else None
    return OcrPage(numero=None, texto=texto, confianza=confianza, motor=NAME, modelo=lang, bloques=blocks)
