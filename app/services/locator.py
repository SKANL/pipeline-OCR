"""Coincidencias literales y geometría nativa, sin interpolar cajas de texto."""
from __future__ import annotations

import math
import re
import unicodedata
from pathlib import Path

from app.services.structure import normalize_bbox, _valid_bbox

MAX_MATCHES = 100
MAX_RECTS = 64
MAX_GLYPHS = 100_000
QUERY_LIMIT = 500


def folded_with_offsets(text: str) -> tuple[str, list[tuple[int, int]]]:
    """NFKD, minúsculas y espacios plegados; índices del original intactos."""
    chars: list[str] = []
    offsets: list[tuple[int, int]] = []
    for index, char in enumerate(text):
        value = "".join(c for c in unicodedata.normalize("NFKD", char).lower() if not unicodedata.combining(c))
        if not value and offsets:
            start, _ = offsets[-1]
            offsets[-1] = (start, index + 1)
        for normalized in value:
            normalized = " " if normalized.isspace() else normalized
            if normalized == " " and chars and chars[-1] == " ":
                offsets[-1] = (offsets[-1][0], index + 1)
                continue
            chars.append(normalized)
            offsets.append((index, index + 1))
    return "".join(chars), offsets


def query_units(query: str) -> list[str]:
    """Términos independientes (OR); comillas dobles delimitan frases literales.

    La localización no aplica stemming, negación ni operadores de MongoDB.
    Comillas sin cerrar se tratan como delimitadores, no como caracteres.
    """
    units = re.findall(r'"([^"\n]+)"|([^\s"]+)', query[:QUERY_LIMIT])
    return list(dict.fromkeys(folded_with_offsets(phrase or term)[0].strip() for phrase, term in units if (phrase or term).strip()))[:32]


def match_ranges(text: str, query: str, limit: int = MAX_MATCHES) -> tuple[list[tuple[int, int]], bool]:
    folded, offsets = folded_with_offsets(text)
    units = [unit for unit in query_units(query) if unit]
    if not units:
        return [], False
    # One bounded forward pass: longest overlapping literal wins.
    pattern = re.compile("|".join(re.escape(unit) for unit in sorted(units, key=len, reverse=True)))
    found = []
    for match in pattern.finditer(folded):
        span = (offsets[match.start()][0], offsets[match.end() - 1][1])
        if found and span == found[-1]:
            continue
        if len(found) == limit:
            return found, True
        found.append(span)
    return found, False


def supported_frame(page) -> tuple[float, float]:
    width, height = page.get_size()
    if page.get_rotation() != 0 or any(not math.isclose(a, b, abs_tol=.01) for a, b in zip(page.get_bbox(), (0, 0, width, height))):
        raise ValueError("Geometría no compatible: página rotada o CropBox/MediaBox desplazado. Consulte la página original.")
    return width, height


def extract_positioned_pdf(path: str | Path) -> list[dict]:
    """Una pasada nativa: texto y posiciones compactas [índice,x,y,ancho,alto].

    No usa get_text_range: sus índices UCS-2 pueden diferir del índice nativo.
    Cada posición apunta a un punto de código Python del texto almacenado.
    """
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    pages = []
    with pdfium.PdfDocument(str(path)) as document:
        for page in document:
            try:
                warning = None
                try:
                    width, height = supported_frame(page)
                except ValueError as exc:
                    width = height = 0
                    warning = str(exc)
                textpage = page.get_textpage()
                try:
                    chars, positions = [], []
                    text_warning = None
                    count = textpage.count_chars()
                    if count > MAX_GLYPHS:
                        warning = "La página supera el límite de geometría; se conserva todo el texto."
                    for index in range(count):
                        codepoint = raw.FPDFText_GetUnicode(textpage, index)
                        if not codepoint:
                            if raw.FPDFText_IsGenerated(textpage, index) == 1:
                                continue
                            codepoint = 0xFFFD
                            text_warning = "Hay glifos sin correspondencia Unicode; consulte el original para verificar el texto."
                        # PDFium represents an extracted discretionary hyphen as U+0002.
                        char = "-" if codepoint == 2 and raw.FPDFText_IsHyphen(textpage, index) == 1 else chr(codepoint)
                        if char == "\r":
                            continue
                        if ord(char) < 32 and char not in "\n\t":
                            char = "\ufffd"
                            text_warning = "Hay glifos sin correspondencia Unicode; consulte el original para verificar el texto."
                        offset = len(chars)
                        chars.append(char)
                        if warning or char.isspace() or char == "\ufffd":
                            continue
                        try:
                            angle = raw.FPDFText_GetCharAngle(textpage, index)
                            box = textpage.get_charbox(index)
                            if abs(angle) > .001 or not _valid_bbox(box):
                                continue
                            if box[0] < 0 or box[1] < 0 or box[2] > width or box[3] > height:
                                continue
                            positions.append([offset, *normalize_bbox(box, width, height)])
                        except Exception:
                            # Missing glyphs never acquire invented geometry.
                            continue
                    from app.services.pdf_layout import native_layout, reorder_native
                    try:
                        supports, rules = native_layout(page, width, height, textpage) if not warning else ([], [])
                    except Exception:
                        supports, rules = [], []
                        text_warning = text_warning or "No se pudo analizar el orden visual; se conserva el texto nativo y la página original."
                    text, positions, flow = reorder_native(chars, positions, supports, rules, width, height)
                    if supports:
                        text_warning = text_warning or "Las etiquetas visuales sin texto Unicode no son buscables; consulte el soporte visual completo."
                    pages.append({"texto": text, "motor": "pypdfium2", "posiciones": positions,
                                  "lectura": flow, "soportes": supports,
                                  "advertencia_localizacion": warning or text_warning})
                finally:
                    textpage.close()
            finally:
                page.close()
    return pages


def _valid_rect(box) -> bool:
    return isinstance(box, (list, tuple)) and len(box) == 4 and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in box) and box[0] >= 0 and box[1] >= 0 and box[2] > 0 and box[3] > 0 and box[0] + box[2] <= 1 and box[1] + box[3] <= 1


def _glyph_rects(text: str, start: int, end: int, positions: dict) -> list[list[float]] | None:
    rects = []
    current = None
    for index in range(start, end):
        char = text[index]
        if char in "\r\n":
            current = None
        if char.isspace():
            continue
        box = positions.get(index)
        if not _valid_rect(box):
            return None
        x, y, width, height = box
        # Only nearby, vertically overlapping glyphs merge, never across columns/lines.
        if current is not None and min(current[1]+current[3], y+height) > max(current[1], y) and -width <= x-(current[0]+current[2]) <= max(height, current[3])*2:
            right, bottom = max(current[0]+current[2], x+width), max(current[1]+current[3], y+height)
            current[0], current[1] = min(current[0], x), min(current[1], y)
            current[2], current[3] = right-current[0], bottom-current[1]
        else:
            current = list(box)
            rects.append(current)
            if len(rects) > MAX_RECTS:
                return None
    return rects or None


def locate_matches(doc: dict, query: str, limit: int = MAX_MATCHES) -> tuple[list[dict], bool]:
    text = doc.get("texto") or ""
    ranges, truncated = match_ranges(text, query, limit)
    positions = {entry[0]: entry[1:] for entry in doc.get("posiciones", []) if isinstance(entry, (list, tuple)) and len(entry) == 5}
    blocks = doc.get("bloques") or []
    out = []
    for start, end in ranges:
        rects = _glyph_rects(text, start, end, positions)
        precision, source, warning = "exacta", "pypdfium2", None
        if not rects:
            # Legacy fallback only certifies a containing block, never a word.
            unit = folded_with_offsets(text[start:end])[0]
            candidates = [block for block in blocks if isinstance(block, dict) and unit in folded_with_offsets(block.get("texto", ""))[0] and _valid_rect(block.get("bbox_norm"))]
            # Repeated blocks are ambiguous: do not assign all hits to the first.
            rects = [candidates[0]["bbox_norm"]] if len(candidates) == 1 else []
            precision = "bloque" if rects else "sin_localizar"
            source = "opendataloader" if rects else None
            warning = doc.get("advertencia_localizacion") or ("Sin geometría nativa completa; la caja de bloque es aproximada." if rects else "No se pudo localizar esta coincidencia en la imagen original.")
        out.append({"inicio": start, "fin": end, "rects": rects, "precision": precision, "fuente": source, "advertencia": warning})
    return out, truncated
