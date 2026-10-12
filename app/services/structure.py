"""Extracción de bloques (texto + bounding box) con `opendataloader-pdf`.

`opendataloader-pdf` analiza el layout de un PDF digital y emite un JSON
jerárquico con los elementos detectados (párrafos, encabezados, tablas,
listas, etc.). Cada elemento de texto trae:

- `page number`  -> página 1-indexada;
- `bounding box` -> `[left, bottom, right, top]` en puntos PDF;
- `content`      -> texto crudo.

Este módulo recorre el árbol (`kids`) y aplana, por un lado, los elementos de
texto a `página -> [{"bbox": [...], "texto": "..."}]` y, por otro, los
elementos `image` (figuras) a `página -> [{"bbox": [...]}]`.

El proceso lanza una JVM (requiere Java 11+). Si Java o el conversor fallan,
se registra el error y se devuelve un mapa vacío: la ingesta NO falla por
esto (la imagen de la página ya da valor por sí sola).
"""

from __future__ import annotations

import json
import logging
import math
import re
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _valid_bbox(value: object) -> bool:
    """True si `value` es una caja `[left, bottom, right, top]` numérica."""
    return (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(isinstance(v, (int, float)) for v in value)
        and all(not isinstance(v, bool) and math.isfinite(v) for v in value)
        and value[2] > value[0]
        and value[3] > value[1]
    )


def normalize_bbox(
    bbox: object, width_pt: float, height_pt: float
) -> list[float] | None:
    """Normaliza un bbox `[left, bottom, right, top]` (puntos PDF) a fracciones.

    El resultado es `[nx, ny, nw, nh]` con origen ARRIBA-IZQUIERDA, listo para
    posicionarse como porcentajes sobre la imagen de la página:

    - `nx = left / width_pt`
    - `ny = (height_pt - top) / height_pt`
    - `nw = (right - left) / width_pt`
    - `nh = (top - bottom) / height_pt`

    Devuelve `None` si el bbox es inválido o el tamaño de página no sirve.
    """
    if not _valid_bbox(bbox) or not all(math.isfinite(v) and v > 0 for v in (width_pt, height_pt)):
        return None
    left, bottom, right, top = (float(v) for v in bbox)
    return [
        left / width_pt,
        (height_pt - top) / height_pt,
        (right - left) / width_pt,
        (top - bottom) / height_pt,
    ]


def with_bbox_norm(
    blocks: list[dict[str, object]], width_pt: float, height_pt: float
) -> list[dict[str, object]]:
    """Copia `blocks` añadiendo `bbox_norm` (calculado del `bbox`)."""
    out: list[dict[str, object]] = []
    for block in blocks:
        bbox_norm = normalize_bbox(block.get("bbox"), width_pt, height_pt)
        out.append({**block, "bbox_norm": bbox_norm})
    return out


def _collect(element: object, out: dict[int, list[dict[str, object]]]) -> None:
    """Recorre recursivamente un elemento y acumula los bloques de texto."""
    if not isinstance(element, dict):
        return

    content = element.get("content")
    page = element.get("page number")
    bbox = element.get("bounding box")
    if (
        isinstance(content, str)
        and content.strip()
        and isinstance(page, int)
        and _valid_bbox(bbox)
    ):
        out.setdefault(page, []).append(
            {"bbox": [float(v) for v in bbox], "texto": content}
        )

    kids = element.get("kids")
    if isinstance(kids, list):
        for child in kids:
            _collect(child, out)


def _elements(data: object):
    """Walk converter reading order, including list-item captions."""
    if not isinstance(data, dict):
        return
    yield data
    for key in ("kids", "list items"):
        for child in data.get(key, []) or []:
            yield from _elements(child)


def is_caption(block: dict) -> bool:
    return block.get("tipo") == "caption" or bool(
        re.match(r"^\s*(?:Figure|Fig\.|Figura)\s+\d+[\s:.$]", str(block.get("texto", "")), re.I)
    )


def parse_structure_json(data: dict) -> dict[int, list[dict[str, object]]]:
    """Aplana el JSON de opendataloader a `página -> bloques` (DB-free)."""
    out: dict[int, list[dict[str, object]]] = {}
    for order, element in enumerate(_elements(data)):
        content, page, bbox = element.get("content"), element.get("page number"), element.get("bounding box")
        if isinstance(content, str) and content.strip() and isinstance(page, int) and _valid_bbox(bbox):
            out.setdefault(page, []).append({"bbox": [float(v) for v in bbox], "texto": content,
                                            "tipo": element.get("type", "paragraph"), "orden": order})
    return out


def _collect_figures(element: object, out: dict[int, list[dict[str, object]]]) -> None:
    """Recorre recursivamente y acumula los elementos `image` (figuras)."""
    if not isinstance(element, dict):
        return
    if element.get("type") == "image":
        page = element.get("page number")
        bbox = element.get("bounding box")
        if isinstance(page, int) and _valid_bbox(bbox):
            out.setdefault(page, []).append({"bbox": [float(v) for v in bbox]})
    kids = element.get("kids")
    if isinstance(kids, list):
        for child in kids:
            _collect_figures(child, out)


def parse_figures_json(data: dict) -> dict[int, list[dict[str, object]]]:
    """Aplana el JSON de opendataloader a `página -> figuras` (DB-free)."""
    out: dict[int, list[dict[str, object]]] = {}
    for order, element in enumerate(_elements(data)):
        page, bbox = element.get("page number"), element.get("bounding box")
        if element.get("type") in ("image", "figure") and isinstance(page, int):
            if _valid_bbox(bbox):
                out.setdefault(page, []).append({"bbox": [float(v) for v in bbox],
                                                "tipo": element["type"], "orden": order})
            else:
                logger.warning("Invalid figure box on page %s; use original page", page)
    return out


def extract_structure(
    pdf_path: str | Path, *, output_dir: str | Path | None = None
) -> dict[str, dict[int, list[dict[str, object]]]]:
    """Convierte el PDF UNA vez y devuelve `{"bloques": ..., "figuras": ...}`.

    Nunca lanza: ante cualquier fallo (JVM ausente, error del conversor)
    registra el problema y devuelve mapas vacíos.
    """
    pdf_path = Path(pdf_path)
    work_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="odl_"))
    cleanup = output_dir is None
    empty: dict[str, dict[int, list[dict[str, object]]]] = {
        "bloques": {},
        "figuras": {},
    }

    try:
        import opendataloader_pdf

        work_dir.mkdir(parents=True, exist_ok=True)
        opendataloader_pdf.convert(
            input_path=[str(pdf_path)],
            output_dir=str(work_dir),
            format="json",
            quiet=True,
        )
        json_files = sorted(work_dir.glob("*.json"))
        if not json_files:
            logger.warning("opendataloader no produjo JSON para %s", pdf_path.name)
            return empty
        data = json.loads(json_files[0].read_text(encoding="utf-8"))
        return {
            "bloques": parse_structure_json(data),
            "figuras": parse_figures_json(data),
        }
    except Exception as exc:  # noqa: BLE001 - la ingesta no debe fallar por esto
        logger.warning(
            "No se pudo extraer la estructura de %s (¿Java/opendataloader?): %s",
            pdf_path.name,
            exc,
        )
        return empty
    finally:
        if cleanup:
            shutil.rmtree(work_dir, ignore_errors=True)


def extract_page_blocks(
    pdf_path: str | Path, *, output_dir: str | Path | None = None
) -> dict[int, list[dict[str, object]]]:
    """Devuelve solo `página -> bloques` (compatibilidad)."""
    return extract_structure(pdf_path, output_dir=output_dir)["bloques"]
