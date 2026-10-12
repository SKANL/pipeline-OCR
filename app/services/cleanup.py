"""Book-level text cleanup: running headers/footers, page numbers, line-end hyphens.

Only deletes characters, so the PDFium alignment survives: `posiciones` drop the
deleted glyphs and shift the rest, `lectura` ranges are remapped the same way
(AGENTS.md "Fuente alineada"). Needs every page of the book, so it runs once at
assembly time.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from app.services.text import fold_text

EDGE_LINES = 3  # candidates: first/last non-empty lines of each page
MIN_PAGES = 3
_PAGE_NUMBER = re.compile(r"(?:pagina|pag|p|fol|folio)? ?\d{1,4}")
_HYPHEN = re.compile(r"(\w+)-([ \t]*\n[ \t]*)?(\w+)")


def _key(line: str) -> str:
    key = " ".join(re.findall(r"\w+", fold_text(line)))
    return "<num>" if _PAGE_NUMBER.fullmatch(key) else key


def _edge_lines(texto: str) -> list[tuple[int, int, str]]:
    """(start, end_including_newline, key) of the first/last non-empty lines."""
    lines, start = [], 0
    for raw in texto.splitlines(keepends=True):
        if raw.strip():
            lines.append((start, start + len(raw), _key(raw)))
        start += len(raw)
    if len(lines) <= 2 * EDGE_LINES:
        return lines
    return lines[:EDGE_LINES] + lines[-EDGE_LINES:]


def _furniture(pages: list[dict]) -> list[set[int]]:
    """Per page, the indices of lines repeated at the page edges across the book."""
    deleted: list[set[int]] = [set() for _ in pages]
    if len(pages) < MIN_PAGES:
        return deleted
    edges = [_edge_lines(p.get("texto") or "") for p in pages]
    counts = Counter(key for page in edges for key in {k for _, _, k in page if k and len(k) <= 80})
    threshold = max(MIN_PAGES, math.ceil(0.3 * len(pages)))
    for index, page in enumerate(edges):
        for start, end, key in page:
            if counts.get(key, 0) >= threshold:
                deleted[index].update(range(start, end))
    return deleted


def _wraps(hyphen: int, following: int, boxes: dict) -> bool:
    """The next glyph starts a new line: back to the left and below (top-left origin)."""
    here, there = boxes.get(hyphen), boxes.get(following)
    if here is None or there is None:
        return False
    return there[0] < here[0] and there[1] > here[1] + here[3]


def _hyphens(pages: list[dict]) -> list[set[int]]:
    """Line-end hyphens to delete; real compounds (seen inline, or Capitalised) are kept."""
    found = []
    inline_forms = set()
    for page in pages:
        texto = page.get("texto") or ""
        boxes = {int(p[0]): p[1:] for p in page.get("posiciones") or [] if len(p) == 5}
        for match in _HYPHEN.finditer(texto):
            hyphen = match.start() + len(match.group(1))
            if match.group(2):
                line_end = True
            else:  # PDFium already joined the line: compare the glyph boxes
                line_end = _wraps(hyphen, match.start(3), boxes)
            form = fold_text(match.group(1) + "-" + match.group(3))
            if line_end:
                found.append((page, match, hyphen))
            else:
                inline_forms.add(form)
    deleted: list[set[int]] = [set() for _ in pages]
    index_of = {id(page): i for i, page in enumerate(pages)}
    for page, match, hyphen in found:
        if match.group(3)[0].isupper() or fold_text(match.group(1) + "-" + match.group(3)) in inline_forms:
            continue
        deleted[index_of[id(page)]].update(range(hyphen, match.start(3)))
    return deleted


def _apply(page: dict, deleted: set[int]) -> None:
    texto = page.get("texto") or ""
    new_index, kept = [], 0
    for index in range(len(texto) + 1):
        new_index.append(kept)
        kept += index < len(texto) and index not in deleted
    page["texto"] = "".join(ch for i, ch in enumerate(texto) if i not in deleted)
    if page.get("posiciones"):
        page["posiciones"] = [[new_index[p[0]], *p[1:]] for p in page["posiciones"] if p[0] not in deleted]
    if page.get("lectura"):
        page["lectura"] = [{**flow, "inicio": new_index[flow["inicio"]], "fin": new_index[flow["fin"]]}
                           for flow in page["lectura"]]


def clean_pages(pages: list[dict]) -> None:
    """Clean `pages` in place (dicts with `texto`, optional `posiciones`/`lectura`)."""
    furniture = _furniture(pages)
    hyphens = _hyphens(pages)
    for page, a, b in zip(pages, furniture, hyphens):
        if a or b:
            _apply(page, a | b)
