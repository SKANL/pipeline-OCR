"""Pipeline de ingesta.

Un libro puede provenir de tres fuentes:

- `paginas/*.txt` (ruta de texto legada), UTF-8, orden natural;
- cualquier `*.pdf` del directorio del libro (extracción local u OCR según
  clasificación);
- un conjunto de imágenes (`*.png/.jpg/.jpeg/.webp`) que se rutean a OCR.

Los builders `_extract_pdf_source` y `_extract_image_source` son la ÚNICA
implementación por tipo de fuente y los comparten la ingesta desde directorio
y desde archivos subidos. El armado puro (DB-free) vive en funciones separadas
para poder testearlo sin MongoDB; la persistencia hace `upsert` por
`libro_id`/`ref` en las colecciones `books` y `pages`.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.db import books_collection, pages_collection
from app.models import Capitulo, Libro, Metadatos, OcrInfo, Pagina, Procedencia
from app.services import ocr as ocr_service
from app.services import pdf_classify, render, scan, structure
from app.services.extract import (
    FUENTE_IMAGENES,
    FUENTE_PDF_DIGITAL,
    FUENTE_PDF_ESCANEADO,
    FUENTE_TEXTO,
    MOTOR_LOCAL,
    ExtractionResult,
    extract_from_images,
    extract_local_pdf_texts,
    list_image_paths,
)
from app.services.naming import natural_key, slugify
from app.services.ocr import IMAGE_SUFFIXES, OcrNotConfiguredError
from app.services.storage import Storage, get_storage, safe_filename
from app.services.text import fold_text
from app.services.locator import extract_positioned_pdf
from app.services.cleanup import clean_pages

# Reexportadas para compatibilidad (los tests las importan desde aquí).
__all__ = [
    "slugify",
    "natural_key",
    "count_words",
    "count_chars",
    "PAGE_FILE_GLOB",
    "parse_book_directory",
    "build_page_projection",
    "ingest_root",
    "ingest_book_dir",
    "ingest_uploaded_files",
    "UploadedFileData",
]

PAGE_FILE_GLOB = "*.txt"

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Utilidades puras
# --------------------------------------------------------------------------
def count_words(texto: str) -> int:
    """Cuenta palabras separando por espacios en blanco."""
    return len(texto.split())


def count_chars(texto: str) -> int:
    """Cuenta caracteres del texto."""
    return len(texto)


def _page_number_from_name(path: Path, fallback: int) -> int:
    match = re.search(r"(\d+)", path.stem)
    return int(match.group(1)) if match else fallback


def _chapter_for_page(numero: int, capitulos: list[dict]) -> int | None:
    for cap in capitulos:
        start = cap.get("pagina_inicio")
        end = cap.get("pagina_fin")
        if start is not None and end is not None and start <= numero <= end:
            return cap.get("numero")
    return None


def load_metadatos(metadatos_path: Path) -> dict:
    """Lee `metadatos.json` (o devuelve `{}` si no existe)."""
    if not metadatos_path.exists():
        return {}
    return json.loads(metadatos_path.read_text(encoding="utf-8"))


def read_pages(pages_dir: Path) -> list[tuple[Path, str]]:
    """Lee los `.txt` de `pages_dir` en orden natural con encoding UTF-8."""
    files = sorted(pages_dir.glob(PAGE_FILE_GLOB), key=lambda p: natural_key(p.name))
    return [(path, path.read_text(encoding="utf-8")) for path in files]


def _split_metadatos(raw: dict) -> tuple[dict, str | None, list[dict]]:
    """Separa `metadatos.json` en (meta_source, libro_id, capitulos)."""
    if isinstance(raw.get("metadatos"), dict):
        return raw["metadatos"], raw.get("libro_id"), raw.get("capitulos") or []
    return raw, raw.get("libro_id"), raw.get("capitulos") or []


def _metadatos_from(source: dict) -> Metadatos:
    """Construye `Metadatos` tomando solo los campos conocidos del origen."""
    return Metadatos(
        **{k: v for k, v in source.items() if k in Metadatos.model_fields}
    )


def _image_files(*dirs: Path) -> list[Path]:
    """Imágenes soportadas dentro de los directorios dados (orden natural)."""
    candidates: list[Path] = [
        path
        for directory in dirs
        if Path(directory).is_dir()
        for path in Path(directory).iterdir()
    ]
    return list_image_paths(candidates)


def parse_book_directory(book_dir: Path) -> dict:
    """Parsea una carpeta legacy de libro (solo `paginas/*.txt`) a un `Libro`."""
    book_dir = Path(book_dir)
    raw = load_metadatos(book_dir / "metadatos.json")
    meta_source, libro_id, capitulos = _split_metadatos(raw)
    libro_id = libro_id or slugify(book_dir.name)

    paginas: list[Pagina] = []
    origen: list[str] = []
    pages_dir = book_dir / "paginas"
    if pages_dir.exists():
        for index, (path, texto) in enumerate(read_pages(pages_dir), start=1):
            origen.append(path.name)
            numero = _page_number_from_name(path, index)
            paginas.append(
                Pagina(
                    numero=numero,
                    ref=f"{libro_id}/pagina/{numero}",
                    capitulo_numero=_chapter_for_page(numero, capitulos),
                    texto=texto,
                    conteo_palabras=count_words(texto),
                    conteo_caracteres=count_chars(texto),
                    motor=FUENTE_TEXTO,
                )
            )
    paginas.sort(key=lambda p: p.numero)

    libro = Libro(
        libro_id=libro_id,
        metadatos=_metadatos_from(meta_source),
        procedencia=Procedencia(fuente=FUENTE_TEXTO),
        origen=origen,
        estado_ingesta="pending",
        capitulos=[Capitulo(**c) for c in capitulos],
        paginas=paginas,
    )
    _set_totals(libro)
    return libro.model_dump(mode="json")


def build_page_projection(libro_id: str, pagina: dict, metadatos: dict) -> dict:
    """Proyecta una página a la colección `pages` (unidad indexable)."""
    texto = pagina.get("texto", "")
    return {
        "libro_id": libro_id,
        "ref": pagina["ref"],
        "numero": pagina["numero"],
        "capitulo_numero": pagina.get("capitulo_numero"),
        "texto": texto,
        "texto_busqueda": fold_text(texto),
        "conteo_palabras": pagina.get("conteo_palabras", 0),
        "conteo_caracteres": pagina.get("conteo_caracteres", 0),
        "ocr_confianza": pagina.get("ocr_confianza"),
        "imagen_url": pagina.get("imagen_url"),
        "imagen_ancho": pagina.get("imagen_ancho"),
        "imagen_alto": pagina.get("imagen_alto"),
        "motor": pagina.get("motor"),
        "bbox": pagina.get("bbox"),
        "bloques": pagina.get("bloques") or [],
        "figuras": pagina.get("figuras") or [],
        "lectura": pagina.get("lectura") or [],
        "posiciones": pagina.get("posiciones") or [],
        "advertencia_localizacion": pagina.get("advertencia_localizacion"),
        "genero": metadatos.get("genero"),
        "autor_normalizado": metadatos.get("autor_normalizado"),
        "titulo": metadatos.get("titulo"),
        "autor": metadatos.get("autor"),
    }


# --------------------------------------------------------------------------
# Armado (DB-free)
# --------------------------------------------------------------------------
@dataclass
class UploadedFileData:
    """Archivo subido: nombre original y bytes."""

    filename: str
    data: bytes


@dataclass
class _ImageSource:
    """Imagen a ingerir: ruta para OCR, bytes y sufijo para la imagen de página."""

    path: Path
    data: bytes
    suffix: str


def _set_totals(libro: Libro) -> None:
    """Recalcula los totales agregados del libro a partir de sus páginas."""
    libro.conteo_paginas = len(libro.paginas)
    libro.conteo_palabras_total = sum(p.conteo_palabras for p in libro.paginas)
    libro.caracteres_totales = sum(p.conteo_caracteres for p in libro.paginas)


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _pages_from_extraction(pages: list[dict], capitulos: list[dict]) -> list[dict]:
    """Renumera y completa páginas ya extraídas (texto/confianza/motor/url)."""
    out: list[dict] = []
    for index, page in enumerate(pages, start=1):
        texto = page.get("texto", "")
        out.append(
            {
                "numero": index,
                "texto": texto,
                "ocr_confianza": page.get("ocr_confianza"),
                "motor": page.get("motor"),
                "imagen_url": page.get("imagen_url"),
                "imagen_ancho": page.get("imagen_ancho"),
                "imagen_alto": page.get("imagen_alto"),
                "bbox": page.get("bbox"),
                "bloques": page.get("bloques") or [],
                "figuras": page.get("figuras") or [],
                "lectura": page.get("lectura") or [],
                "posiciones": page.get("posiciones") or [],
                "advertencia_localizacion": page.get("advertencia_localizacion"),
                "capitulo_numero": _chapter_for_page(index, capitulos),
                "conteo_palabras": count_words(texto),
                "conteo_caracteres": count_chars(texto),
            }
        )
    return out


def _assemble_libro(
    *,
    libro_id: str,
    metadatos: Metadatos,
    capitulos: list[dict],
    pages: list[dict],
    fuente: str,
    motor: str | None,
    modelo: str | None,
    confianza_media: float | None,
    origen: list[str],
) -> dict:
    """Construye el documento `Libro` (dict) a partir de páginas extraídas.

    Con `text_cleanup` (por defecto) limpia el libro completo antes: quita
    cabeceras/pies/números de página repetidos y guiones de fin de línea,
    remapeando posiciones de glifos (ver `services/cleanup.py`).
    """
    now = datetime.now(timezone.utc)
    if get_settings().text_cleanup:
        clean_pages(pages)
        for page in pages:
            page["conteo_palabras"] = count_words(page.get("texto", ""))
            page["conteo_caracteres"] = count_chars(page.get("texto", ""))
    if fuente in (FUENTE_PDF_ESCANEADO, FUENTE_IMAGENES):
        ocr_info = OcrInfo(
            motor=motor or "mistral",
            modelo=modelo,
            fecha=now,
            confianza_media=confianza_media,
        )
    else:
        ocr_info = OcrInfo(motor=None, modelo=None, fecha=None, confianza_media=None)

    paginas = [
        Pagina(
            numero=p["numero"],
            ref=f"{libro_id}/pagina/{p['numero']}",
            capitulo_numero=p.get("capitulo_numero"),
            texto=p.get("texto", ""),
            conteo_palabras=p.get("conteo_palabras", 0),
            conteo_caracteres=p.get("conteo_caracteres", 0),
            ocr_confianza=p.get("ocr_confianza"),
            imagen_url=p.get("imagen_url"),
            imagen_ancho=p.get("imagen_ancho"),
            imagen_alto=p.get("imagen_alto"),
            motor=p.get("motor"),
            bbox=p.get("bbox"),
            bloques=p.get("bloques") or [],
            figuras=p.get("figuras") or [],
            lectura=p.get("lectura") or [],
            posiciones=p.get("posiciones") or [],
            advertencia_localizacion=p.get("advertencia_localizacion"),
        )
        for p in pages
    ]

    libro = Libro(
        libro_id=libro_id,
        metadatos=metadatos,
        procedencia=Procedencia(fuente=fuente, ocr=ocr_info),
        origen=origen,
        estado_ingesta="pending",
        capitulos=[Capitulo(**c) for c in capitulos],
        paginas=paginas,
    )
    _set_totals(libro)
    return libro.model_dump(mode="json")


def _require_ocr_if_needed(*, needs_ocr: bool) -> None:
    """Guarda de OCR: sin API key no se puede rutear a OCR."""
    if needs_ocr and not get_settings().mistral_api_key:
        raise OcrNotConfiguredError(
            "La fuente requiere OCR (PDF escaneado o imágenes) pero "
            "MISTRAL_API_KEY no está configurada en el entorno (.env)."
        )


def _pages_from_result(
    result: ExtractionResult, image_urls: list[str | None] | None = None
) -> list[dict]:
    """Convierte un `ExtractionResult` en páginas-dict (sin numerar todavía)."""
    pages = [
        {
            "texto": p.texto,
            "ocr_confianza": p.ocr_confianza,
            "motor": p.motor,
            "imagen_url": p.imagen_url,
            "bbox": None,
            "bloques": [],
        }
        for p in result.paginas
    ]
    if image_urls:
        for page, url in zip(pages, image_urls):
            page["imagen_url"] = url
    return pages


# --------------------------------------------------------------------------
# Verificación: imagen de página + bloques con bounding box
# --------------------------------------------------------------------------
def _page_png_bytes(data: bytes, suffix: str) -> bytes:
    """Normaliza los bytes de una imagen a PNG (conserva PNG intacto)."""
    if suffix == ".png":
        return data
    from PIL import Image

    image = Image.open(BytesIO(data)).convert("RGB")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _png_size(data: bytes) -> tuple[int, int] | None:
    """Devuelve `(ancho, alto)` en píxeles de una imagen, o `None` si falla.

    Se usa para fijar la relación de aspecto de la imagen de página en el
    front (evita el salto de layout mientras carga).
    """
    try:
        from PIL import Image

        with Image.open(BytesIO(data)) as image:
            return int(image.width), int(image.height)
    except Exception:  # noqa: BLE001 - la dimensión es opcional
        return None


def _normalize_blocks_for_page(
    pdf_path: Path, local_page: int, blocks: list[dict]
) -> list[dict]:
    """Añade `bbox_norm` a los bloques de una página (origen arriba-izquierda).

    Usa el tamaño de página en puntos de pypdfium2, el mismo page box que
    cubre la imagen renderizada. Nunca falla: sin tamaño de página los bloques
    quedan sin `bbox_norm`.
    """
    if not blocks:
        return blocks
    try:
        width_pt, height_pt = render.pdf_page_size(pdf_path, local_page - 1)
    except Exception as exc:  # noqa: BLE001 - no debe tumbar la ingesta
        logger.warning(
            "No se pudo obtener el tamaño de %s pág. %d: %s",
            pdf_path.name,
            local_page,
            exc,
        )
        return blocks
    return structure.with_bbox_norm(blocks, width_pt, height_pt)


def _blocks_outside_figures(blocks: list[dict], figures: list[dict]) -> list[dict]:
    """Compatibility helper: geometry alone cannot prove text is expendable.

    Preserve captions, labels and prose even after crop success. Search must
    not lose content based on an unverified image detector.
    """
    return blocks


def _significant_figures(
    figuras: list[dict], width_pt: float, height_pt: float
) -> list[dict]:
    """Keep all valid candidates, regardless of area; never classify noise."""
    valid = [figure for figure in figuras if structure._valid_bbox(figure.get("bbox"))]
    # Correct only horizontally separated, top-aligned panels; no union of boxes.
    pending = sorted(valid, key=lambda figure: -figure["bbox"][3])
    out = []
    while pending:
        first = pending.pop(0)
        row = [first]
        while pending and abs(first["bbox"][3] - pending[0]["bbox"][3]) <= 18:
            row.append(pending.pop(0))
        if all(a["bbox"][2] <= b["bbox"][0] for a, b in zip(sorted(row, key=lambda f: f["bbox"][0]), sorted(row, key=lambda f: f["bbox"][0])[1:])):
            slots = sorted(figure.get("orden", index) for index, figure in enumerate(row))
            for slot, figure in zip(slots, sorted(row, key=lambda f: f["bbox"][0])):
                out.append({**figure, "orden_fuente": figure.get("orden"), "orden": slot})
        else:
            out.extend(row)
    return out


def _overlapping_candidate(figure: dict, figures: list[dict]) -> bool:
    """Containment/overlap is a fragmentation warning, not permission to merge."""
    left, bottom, right, top = figure["bbox"]
    area = (right - left) * (top - bottom)
    for other in figures:
        if other is figure:
            continue
        x0, y0, x1, y1 = other["bbox"]
        intersection = max(0, min(right, x1) - max(left, x0)) * max(0, min(top, y1) - max(bottom, y0))
        if intersection >= 0.5 * min(area, (x1 - x0) * (y1 - y0)):
            return True
    return False


def _figure_caption(figure: dict, blocks: list[dict]) -> str | None:
    """Associate only an unambiguous nearby caption below the candidate.

    Keep the caption block in prose. Never invent a caption or extend crop
    geometry using a caption as a guessed diagram boundary.
    """
    left, bottom, right, _ = figure["bbox"]
    candidates = []
    for block in blocks:
        if not structure.is_caption(block):
            continue
        x0, _, x1, top = block["bbox"]
        if 0 <= bottom - top <= 36 and min(right, x1) > max(left, x0):
            candidates.append(block["texto"])
    return candidates[0] if len(candidates) == 1 else None


def _crop_figures(
    pdf_path: Path,
    local_page: int,
    figuras: list[dict],
    libro_id: str,
    numero: int,
    storage: Storage,
    dpi: int,
    width_pt: float,
    height_pt: float,
    page_png: bytes | None = None,
    blocks: list[dict] | None = None,
    geometry_warning: str | None = None,
) -> list[dict]:
    """Recorta cada figura de una página y devuelve sus registros."""
    recortadas: list[dict] = []
    for index, figura in enumerate(figuras):
        bbox = figura.get("bbox")
        fragmented = _overlapping_candidate(figura, figuras)
        caption = figura.get("pie") or (_figure_caption(figura, blocks or []) if not fragmented else None)
        record = {**figura, "bbox_norm": None, "imagen_url": None,
                  "pie": caption, "texto_alternativo": caption or f"Recorte de la página {numero}; consultar la página original para el contexto completo.",
                  "estado": "fragmento" if fragmented else "no_verificado",
                   "advertencia": figura.get("advertencia") or ("Soporte delimitado por objetos nativos; no se certifica el texto buscable de todas las etiquetas. Consulte el original."
                       if figura.get("tipo") == "soporte_nativo" else "Los recortes pueden omitir componentes vectoriales, títulos o etiquetas. Consulte la página original.")}
        if figura.get("detectada") is False:
            record["texto_alternativo"] = f"Página original completa {numero}; las etiquetas visuales sin Unicode no son buscables."
        try:
            if geometry_warning:
                raise ValueError(geometry_warning)
            if figura.get("detectada") is False:
                record.update(estado="pagina_original")
            data = (render.crop_page_png(page_png, bbox, width_pt, height_pt) if page_png
                    else render.render_pdf_region(pdf_path, local_page - 1, bbox, dpi=dpi))
            size = _png_size(data)
            if not size:
                raise ValueError("Crop has no valid image dimensions")
            relative = storage.save_figure(libro_id, numero, index, data)
            record.update(imagen_url=relative, imagen_ancho=size[0], imagen_alto=size[1],
                          bbox_norm=structure.normalize_bbox(bbox, width_pt, height_pt))
        except Exception as exc:  # noqa: BLE001 - la figura no debe tumbar la ingesta
            logger.warning(
                "No se pudo recortar una figura de %s pág. %d: %s",
                pdf_path.name,
                local_page,
                exc,
            )
            record.update(estado="pagina_original", advertencia=str(exc))
        recortadas.append(record)
    return recortadas


def _pdf_verification(
    pdf_paths: list[Path],
    libro_id: str,
    storage: Storage,
    native_by_path: dict | None = None,
    first_page: int = 1,
) -> tuple[
    list[str | None],
    dict[int, list[dict]],
    list[tuple[int, int] | None],
    dict[int, list[dict]],
]:
    """Renderiza páginas, extrae bloques con bbox y recorta figuras.

    Devuelve `(urls, bloques_por_pagina, tamanos, figuras_por_pagina)` con
    numeración global (1-indexada), consistente con el orden en que la ingesta
    concatena las páginas. Todo el texto se conserva; los recortes no están
    verificados semánticamente y nunca justifican pérdida de texto.
    """
    dpi = get_settings().page_image_dpi
    image_urls: list[str | None] = []
    image_sizes: list[tuple[int, int] | None] = []
    bloques_por_pagina: dict[int, list[dict]] = {}
    figuras_por_pagina: dict[int, list[dict]] = {}
    offset = first_page - 1
    for pdf_path in pdf_paths:
        arch = structure.extract_structure(pdf_path)
        try:
            count = render.pdf_page_count(pdf_path)
        except Exception as exc:  # noqa: BLE001 - no debe tumbar la ingesta
            logger.warning("No se pudo abrir %s para renderizar: %s", pdf_path.name, exc)
            count = 0
        for page_index in range(count):
            numero = offset + page_index + 1
            local_page = page_index + 1
            data = None
            try:
                data = render.render_pdf_page(pdf_path, page_index, dpi=dpi)
                relative = storage.save_page_image(libro_id, numero, data)
                image_urls.append(relative)
                image_sizes.append(_png_size(data))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "No se pudo renderizar %s pág. %d: %s",
                    pdf_path.name,
                    page_index + 1,
                    exc,
                )
                image_urls.append(None)
                image_sizes.append(None)

            geometry_warning = None
            try:
                width_pt, height_pt = render.pdf_page_geometry(pdf_path, page_index)
            except Exception as exc:  # noqa: BLE001 - original-page fallback
                width_pt = height_pt = 0.0
                geometry_warning = str(exc)
                logger.warning("Crop/overlay geometry unavailable for %s page %d: %s", pdf_path.name, local_page, exc)
            figuras_pt = _significant_figures(
                arch["figuras"].get(local_page) or [], width_pt, height_pt
            )
            native = (native_by_path or {}).get(pdf_path, [])
            supports = native[page_index].get("soportes", []) if page_index < len(native) else []
            if supports:
                from app.services.pdf_layout import compose_visual_supports
                figuras_pt = compose_visual_supports(supports, figuras_pt)
            blocks = _blocks_outside_figures(
                arch["bloques"].get(local_page) or [], figuras_pt
            )
            if blocks:
                bloques_por_pagina[numero] = structure.with_bbox_norm(blocks, width_pt, height_pt)
            recortadas = _crop_figures(
                pdf_path,
                local_page,
                figuras_pt,
                libro_id,
                numero,
                storage,
                dpi,
                width_pt,
                height_pt,
                page_png=data,
                blocks=blocks,
                geometry_warning=geometry_warning,
            )
            if recortadas:
                figuras_por_pagina[numero] = recortadas
        offset += count
    return image_urls, bloques_por_pagina, image_sizes, figuras_por_pagina


def _apply_pdf_verification(
    pages: list[dict],
    image_urls: list[str | None],
    bloques_por_pagina: dict[int, list[dict]],
    image_sizes: list[tuple[int, int] | None],
    figuras_por_pagina: dict[int, list[dict]],
    first_page: int = 1,
) -> None:
    """Asigna a cada página su `imagen_url`, `bloques`, `figuras` y tamaño."""
    for index, page in enumerate(pages):
        numero = first_page + index
        if index < len(image_urls):
            page["imagen_url"] = image_urls[index]
        page["bloques"] = bloques_por_pagina.get(numero, [])
        page["figuras"] = figuras_por_pagina.get(numero, [])
        if index < len(image_sizes) and image_sizes[index]:
            page["imagen_ancho"], page["imagen_alto"] = image_sizes[index]


# --------------------------------------------------------------------------
# Builders de fuente (compartidos por directorio y por archivos subidos)
# --------------------------------------------------------------------------
def _extract_pdf_source(
    pdf_paths: list[Path],
    libro_id: str,
    capitulos: list[dict],
    storage: Storage,
    first_page: int = 1,
) -> dict:
    """Extrae páginas de uno o más PDF (texto, bloques, imagen y procedencia).

    Los digitales usan texto y glifos de PDFium en una sola pasada alineada.
    OpenDataLoader conserva ayudas visuales y cajas aproximadas de respaldo.
    Sin texto nativo se usan los bloques o pdf-inspector, con motor real.
    `first_page` numera las imágenes/recortes guardados (cola: una página por vez).
    """
    native_by_path = {}
    for pdf_path in pdf_paths:
        try:
            native_by_path[pdf_path] = extract_positioned_pdf(pdf_path)
        except Exception as exc:
            logger.warning("Extracción nativa no disponible para %s: %s", pdf_path.name, exc)
            native_by_path[pdf_path] = []
    image_urls, bloques_por_pagina, image_sizes, figuras_por_pagina = _pdf_verification(
        pdf_paths, libro_id, storage, native_by_path, first_page
    )

    pages: list[dict] = []
    fuentes: list[str] = []
    motor: str | None = None
    modelo: str | None = None
    confianzas: list[float] = []
    numero = first_page - 1

    for pdf_path in pdf_paths:
        info = pdf_classify.classify_pdf_file(pdf_path)
        try:
            count = render.pdf_page_count(pdf_path)
        except Exception:  # noqa: BLE001 - coherente con _pdf_verification
            count = 0
        nums = range(numero + 1, numero + count + 1)
        numero += count

        if pdf_classify.is_text_based(info):
            fuentes.append(FUENTE_PDF_DIGITAL)
            native_pages = native_by_path[pdf_path]
            motor = "pypdfium2" if native_pages else "opendataloader"
            respaldo: list[str] | None = None
            for local_index, page_number in enumerate(nums):
                native = native_pages[local_index] if local_index < len(native_pages) else None
                if native and native["texto"].strip():
                    pages.append(native)
                    continue
                blocks = bloques_por_pagina.get(page_number) or []
                if blocks:
                    texto = "\n\n".join(
                        str(block.get("texto", "")).strip() for block in blocks
                    ).strip()
                else:
                    # Sin bloques: respaldo con la extracción local de pdf-inspector.
                    if respaldo is None:
                        respaldo = extract_local_pdf_texts(pdf_path)
                    texto = (
                        respaldo[local_index] if local_index < len(respaldo) else ""
                    )
                pages.append({"texto": texto, "motor": "opendataloader" if blocks else MOTOR_LOCAL,
                              "advertencia_localizacion": "Extracción sin geometría de glifos; solo localización aproximada cuando hay bloques."})
        else:
            fuentes.append(FUENTE_PDF_ESCANEADO)
            result = ocr_service.ocr_pdf_file(pdf_path)
            for page in result.paginas:
                pages.append(
                    {
                        "texto": page.texto,
                        "ocr_confianza": page.confianza,
                        "motor": page.motor,
                    }
                )
            motor = result.motor or motor
            modelo = result.modelo or modelo
            confianzas += [
                p.confianza for p in result.paginas if p.confianza is not None
            ]

    fuente = (
        FUENTE_PDF_ESCANEADO if FUENTE_PDF_ESCANEADO in fuentes else FUENTE_PDF_DIGITAL
    )
    _apply_pdf_verification(
        pages, image_urls, bloques_por_pagina, image_sizes, figuras_por_pagina, first_page
    )
    return {
        "pages": _pages_from_extraction(pages, capitulos),
        "fuente": fuente,
        "motor": motor,
        "modelo": modelo,
        "confianza_media": _average(confianzas),
    }


def _extract_image_source(
    sources: list[_ImageSource],
    libro_id: str,
    capitulos: list[dict],
    storage: Storage,
    first_page: int = 1,
) -> dict:
    """Guarda la imagen de cada página y rutea el conjunto a OCR.

    Con `scan_preprocess` (por defecto) cada imagen se endereza y limpia
    (`services/scan.py`); esa versión es la que va al OCR y la que se guarda
    como imagen de página. El original queda intacto en el almacenamiento.
    """
    urls: list[str | None] = []
    sizes: list[tuple[int, int] | None] = []
    preprocess = get_settings().scan_preprocess
    with tempfile.TemporaryDirectory() as tmp:
        ocr_paths: list[Path] = []
        for index, source in enumerate(sources, start=first_page):
            if preprocess:
                png = scan.preprocess_image(source.data)
                path = Path(tmp) / f"pagina-{index}.png"
                path.write_bytes(png)
            else:
                png, path = _page_png_bytes(source.data, source.suffix), source.path
            ocr_paths.append(path)
            relative = storage.save_page_image(libro_id, index, png)
            urls.append(relative)
            sizes.append(_png_size(png))

        result = extract_from_images(ocr_paths)
    pages = _pages_from_extraction(_pages_from_result(result, urls), capitulos)
    for page, size in zip(pages, sizes):
        if size:
            page["imagen_ancho"], page["imagen_alto"] = size
    return {
        "pages": pages,
        "fuente": FUENTE_IMAGENES,
        "motor": result.motor,
        "modelo": result.modelo,
        "confianza_media": result.confianza_media,
    }


# --------------------------------------------------------------------------
# Ingesta desde directorio
# --------------------------------------------------------------------------
def _detect_source(book_dir: Path) -> str:
    pages_dir = book_dir / "paginas"
    if pages_dir.is_dir() and any(pages_dir.glob(PAGE_FILE_GLOB)):
        return FUENTE_TEXTO
    if any(book_dir.glob("*.pdf")):
        return "pdf"
    if _image_files(book_dir, book_dir / "imagenes"):
        return FUENTE_IMAGENES
    return "vacio"


def build_book_dir(
    book_dir: Path,
    *,
    libro_id: str | None = None,
    metadatos_override: dict | None = None,
    storage: Storage | None = None,
) -> dict:
    """Arma (sin persistir) el `Libro` de una carpeta con txt/pdf/imágenes."""
    book_dir = Path(book_dir)
    raw = load_metadatos(book_dir / "metadatos.json")
    meta_source, raw_id, capitulos = _split_metadatos(raw)
    if metadatos_override:
        meta_source = {**meta_source, **metadatos_override}
    libro_id = libro_id or raw_id or slugify(book_dir.name)
    storage = storage or get_storage()

    kind = _detect_source(book_dir)

    if kind == FUENTE_TEXTO:
        libro = parse_book_directory(book_dir)
        libro["libro_id"] = libro_id
        libro["metadatos"] = _metadatos_from(
            {**libro["metadatos"], **meta_source}
        ).model_dump(mode="json")
        for pagina in libro["paginas"]:
            pagina["ref"] = f"{libro_id}/pagina/{pagina['numero']}"
        return libro

    if kind == "pdf":
        pdf_paths = sorted(book_dir.glob("*.pdf"), key=lambda p: natural_key(p.name))
        source = _extract_pdf_source(pdf_paths, libro_id, capitulos, storage)
        return _assemble_libro(
            libro_id=libro_id,
            metadatos=_metadatos_from(meta_source),
            capitulos=capitulos,
            origen=[p.name for p in pdf_paths],
            **source,
        )

    if kind == FUENTE_IMAGENES:
        image_paths = _image_files(book_dir, book_dir / "imagenes")
        sources = [
            _ImageSource(path=p, data=p.read_bytes(), suffix=p.suffix.lower())
            for p in image_paths
        ]
        source = _extract_image_source(sources, libro_id, capitulos, storage)
        return _assemble_libro(
            libro_id=libro_id,
            metadatos=_metadatos_from(meta_source),
            capitulos=capitulos,
            origen=[p.name for p in image_paths],
            **source,
        )

    raise ValueError(f"No se encontró fuente ingerible en {book_dir} (txt/pdf/imágenes).")


# --------------------------------------------------------------------------
# Ingesta desde archivos subidos
# --------------------------------------------------------------------------
def ingest_uploaded_files(
    uploads: list[UploadedFileData],
    *,
    libro_id: str | None = None,
    metadatos_override: dict | None = None,
    storage: Storage | None = None,
) -> dict:
    """Ingesta archivos subidos (uno o más PDF, o solo imágenes).

    Guarda los originales vía `storage`, corre el router y persiste. Devuelve
    el resumen (mismo formato que `ingest_root` + `libro_id`).
    """
    if not uploads:
        raise ValueError("No se recibió ningún archivo.")

    storage = storage or get_storage()
    pdfs = [u for u in uploads if u.filename.lower().endswith(".pdf")]
    images = [u for u in uploads if Path(u.filename).suffix.lower() in IMAGE_SUFFIXES]

    if pdfs and images:
        raise ValueError("No se admite mezclar un PDF con imágenes en la misma ingesta.")
    if not pdfs and not images:
        raise ValueError(
            "No se recibió ningún PDF ni imagen soportada (.png/.jpg/.jpeg/.webp)."
        )

    libro_id = libro_id or slugify(Path(uploads[0].filename).stem) or "libro"

    # Guarda de OCR ANTES de escribir en disco (clasifica el PDF desde bytes).
    if pdfs:
        needs_ocr = any(
            not pdf_classify.is_text_based(pdf_classify.classify_pdf_bytes(u.data))
            for u in pdfs
        )
        _require_ocr_if_needed(needs_ocr=needs_ocr)
    else:
        _require_ocr_if_needed(needs_ocr=True)

    # Persiste originales y arma el mapa nombre -> ruta relativa.
    stored = {
        upload.filename: storage.save(libro_id, upload.filename, upload.data)
        for upload in uploads
    }

    meta_source: dict = dict(metadatos_override or {})
    if "titulo" not in meta_source:
        meta_source["titulo"] = Path(uploads[0].filename).stem

    if pdfs:
        ordered_pdfs = sorted(pdfs, key=lambda u: natural_key(u.filename))
        pdf_paths = [storage.path(stored[u.filename]) for u in ordered_pdfs]
        source = _extract_pdf_source(pdf_paths, libro_id, [], storage)
        origen = [u.filename for u in ordered_pdfs]
    else:
        ordered = sorted(images, key=lambda u: natural_key(u.filename))
        sources = [
            _ImageSource(
                path=storage.path(stored[u.filename]),
                data=u.data,
                suffix=Path(u.filename).suffix.lower(),
            )
            for u in ordered
        ]
        source = _extract_image_source(sources, libro_id, [], storage)
        origen = [u.filename for u in ordered]

    libro = _assemble_libro(
        libro_id=libro_id,
        metadatos=_metadatos_from(meta_source),
        capitulos=[],
        origen=origen,
        **source,
    )
    _persist(libro, storage, originals=stored.values())
    return {
        "libro_id": libro_id,
        "books": 1,
        "pages": libro["conteo_paginas"],
        "books_processed": [libro_id],
        "errors": [],
        "fuente": libro["procedencia"]["fuente"],
    }


# --------------------------------------------------------------------------
# Persistencia
# --------------------------------------------------------------------------
def _persist(libro: dict, storage: Storage, originals: Iterable[str] = ()) -> None:
    """Upsert del libro en `books` y de sus páginas en `pages` (con poda).

    `originals` son las claves reales de los originales guardados; se
    conservan siempre. La poda corre al final: si persistir falla, no borra.
    """
    now = datetime.now(timezone.utc)
    libro_id = libro["libro_id"]

    libro["estado_ingesta"] = "indexed"
    libro["actualizado_en"] = now

    doc = {k: v for k, v in libro.items() if k != "creado_en"}
    books_collection().update_one(
        {"libro_id": libro_id},
        {"$set": doc, "$setOnInsert": {"creado_en": now}},
        upsert=True,
    )

    numeros = [pagina["numero"] for pagina in libro["paginas"]]
    pages = pages_collection()

    metadatos = libro.get("metadatos", {})
    for pagina in libro["paginas"]:
        projection = build_page_projection(libro_id, pagina, metadatos)
        pages.update_one({"ref": projection["ref"]}, {"$set": projection}, upsert=True)

    pages.delete_many({"libro_id": libro_id, "numero": {"$nin": numeros}})

    # Poda de media: borra todo objeto bajo `{libro_id}/` que el libro nuevo
    # no referencia (páginas, recortes y originales obsoletos).
    keep = set(originals)
    keep.update(f"{libro_id}/{safe_filename(nombre)}" for nombre in libro.get("origen") or [])
    for pagina in libro["paginas"]:
        keep.add(pagina.get("imagen_url"))
        keep.update(f.get("imagen_url") for f in pagina.get("figuras") or [])
    storage.delete_prefix(f"{libro_id}/", keep={k for k in keep if k})


def ingest_book_dir(
    book_dir: str | Path,
    *,
    libro_id: str | None = None,
    metadatos_override: dict | None = None,
    storage: Storage | None = None,
) -> dict:
    """Ingesta una carpeta de libro (txt/pdf/imágenes) y la persiste."""
    storage = storage or get_storage()
    libro = build_book_dir(
        Path(book_dir),
        libro_id=libro_id,
        metadatos_override=metadatos_override,
        storage=storage,
    )
    _persist(libro, storage)
    return {
        "libro_id": libro["libro_id"],
        "books": 1,
        "pages": libro["conteo_paginas"],
        "books_processed": [libro["libro_id"]],
        "errors": [],
        "fuente": libro["procedencia"]["fuente"],
    }


def ingest_root(root: str | Path) -> dict:
    """Ingesta todas las subcarpetas de `root` como libros.

    El router de extracción decide automáticamente si cada fuente necesita OCR.

    Devuelve un resumen: libros procesados, páginas y errores.
    """
    root_path = Path(root)
    if not root_path.exists() or not root_path.is_dir():
        raise FileNotFoundError(f"El directorio raíz no existe: {root_path}")

    summary: dict[str, Any] = {
        "books": 0,
        "pages": 0,
        "books_processed": [],
        "errors": [],
        "fuentes": {},
    }

    book_dirs = sorted(
        (d for d in root_path.iterdir() if d.is_dir()), key=lambda p: natural_key(p.name)
    )
    for book_dir in book_dirs:
        try:
            result = ingest_book_dir(book_dir)
            summary["books"] += 1
            summary["pages"] += result["pages"]
            summary["books_processed"].append(result["libro_id"])
            fuente = result["fuente"]
            summary["fuentes"][fuente] = summary["fuentes"].get(fuente, 0) + 1
        except Exception as exc:  # noqa: BLE001 - se reporta en el resumen
            summary["errors"].append({"book": book_dir.name, "error": str(exc)})

    return summary
