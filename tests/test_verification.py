"""Tests de la capa de verificación: render de páginas y bloques con bbox.

- El parseo del JSON de opendataloader se prueba con datos de muestra (sin JVM).
- El render pypdfium2 se prueba con un PDF generado localmente.
- Una integración real con opendataloader se marca `skip` si no hay Java.
"""

from __future__ import annotations

import shutil
import subprocess
from io import BytesIO
from pathlib import Path

import pytest

from app.services import ingest, render, structure
from app.services.storage import LocalStorage

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

SAMPLE_STRUCTURE = {
    "file name": "muestra.pdf",
    "number of pages": 2,
    "kids": [
        {
            "type": "paragraph",
            "page number": 1,
            "bounding box": [72.0, 700.0, 300.0, 720.0],
            "content": "El pacto de la gracia sostiene al creyente.",
        },
        {
            "type": "text block",
            "page number": 2,
            "bounding box": [0.0, 0.0, 0.0, 0.0],
            "kids": [
                {
                    "type": "paragraph",
                    "page number": 2,
                    "bounding box": [10.0, 20.0, 30.0, 40.0],
                    "content": "Bloque anidado de prueba.",
                }
            ],
        },
        {"type": "image", "page number": 1, "bounding box": [1.0, 1.0, 1.0, 1.0]},
        {
            "type": "paragraph",
            "page number": 1,
            "bounding box": [1.0, 2.0, 3.0],
            "content": "bbox invalido, se ignora",
        },
        {"type": "paragraph", "page number": 1, "bounding box": [5.0, 6.0, 7.0, 8.0], "content": "  "},
    ],
}


def test_parse_structure_json_flattens_blocks() -> None:
    blocks = structure.parse_structure_json(SAMPLE_STRUCTURE)
    assert blocks[1] == [
        {"bbox": [72.0, 700.0, 300.0, 720.0], "texto": "El pacto de la gracia sostiene al creyente.", "tipo": "paragraph", "orden": 1}
    ]
    assert blocks[2] == [
        {"bbox": [10.0, 20.0, 30.0, 40.0], "texto": "Bloque anidado de prueba.", "tipo": "paragraph", "orden": 3}
    ]


def test_parse_structure_json_handles_empty() -> None:
    assert structure.parse_structure_json({}) == {}


def _write_text_pdf(path: Path, pages: list[str]) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    for texto in pages:
        c.setFont("Helvetica", 12)
        c.drawString(72, 720, texto)
        c.showPage()
    c.save()


def test_normalize_bbox_uses_top_left_origin() -> None:
    # width=600pt, height=800pt; bbox [left, bottom, right, top].
    norm = structure.normalize_bbox([60.0, 700.0, 300.0, 740.0], 600.0, 800.0)
    assert norm == pytest.approx([0.1, 0.075, 0.4, 0.05])


def test_normalize_bbox_rejects_invalid() -> None:
    assert structure.normalize_bbox([1.0, 2.0, 3.0], 600.0, 800.0) is None
    assert structure.normalize_bbox([1.0, 2.0, 3.0, 4.0], 0.0, 800.0) is None


def test_pdf_verification_computes_bbox_norm(monkeypatch, tmp_path: Path) -> None:
    """La ingesta pdf_digital normaliza el bbox a fracciones 0..1 (4 valores)."""
    pdf = tmp_path / "digital.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(render, "pdf_page_count", lambda _path: 1)
    monkeypatch.setattr(render, "render_pdf_page", lambda *_a, **_k: PNG_MAGIC)
    monkeypatch.setattr(render, "pdf_page_size", lambda _path, _index: (600.0, 800.0))
    monkeypatch.setattr(render, "pdf_page_geometry", lambda _path, _index: (600.0, 800.0))
    monkeypatch.setattr(
        structure,
        "extract_structure",
        lambda _path: {
            "bloques": {
                1: [{"bbox": [60.0, 700.0, 300.0, 740.0], "texto": "la gracia soberana"}]
            },
            "figuras": {},
        },
    )

    storage = LocalStorage(tmp_path / "media")
    image_urls, bloques_por_pagina, image_sizes, _figuras = ingest._pdf_verification(
        [pdf], "libro-x", storage
    )

    assert image_urls == ["/media/libro-x/paginas/1.png"]
    assert len(image_sizes) == 1
    blocks = bloques_por_pagina[1]
    assert len(blocks) == 1
    bbox_norm = blocks[0]["bbox_norm"]
    assert isinstance(bbox_norm, list) and len(bbox_norm) == 4
    assert all(0.0 <= value <= 1.0 for value in bbox_norm)
    assert blocks[0]["bbox"] == [60.0, 700.0, 300.0, 740.0]


def test_render_pdf_page_returns_png(tmp_path: Path) -> None:
    pdf = tmp_path / "digital.pdf"
    _write_text_pdf(pdf, ["Pagina uno con gracia.", "Pagina dos."])

    assert render.pdf_page_count(pdf) == 2
    data = render.render_pdf_page(pdf, 0)
    assert data[:8] == PNG_MAGIC
    assert len(data) > 0


def _java_available() -> bool:
    if not shutil.which("java"):
        return False
    try:
        subprocess.run(["java", "-version"], capture_output=True, check=True, timeout=30)
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _java_available(), reason="Java no disponible para opendataloader")
def test_opendataloader_real_extracts_blocks(tmp_path: Path) -> None:
    pdf = tmp_path / "digital.pdf"
    _write_text_pdf(pdf, ["El pacto de la gracia sostiene al creyente en la prueba."])

    blocks = structure.extract_page_blocks(pdf)
    assert 1 in blocks
    joined = " ".join(block["texto"] for block in blocks[1])
    assert "gracia" in joined
    assert all(len(block["bbox"]) == 4 for page in blocks.values() for block in page)
