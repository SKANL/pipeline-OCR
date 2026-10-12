"""Regresión: el camino de PDF escaneado promedia la confianza OCR (sin red)."""

from __future__ import annotations

from pathlib import Path

from app.services import ingest, ocr, pdf_classify, render


def test_scanned_pdf_reports_confianza_media(monkeypatch, tmp_path: Path) -> None:
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-fake")
    result = ocr.OcrResult(
        paginas=[
            ocr.OcrPage(numero=1, texto="uno", confianza=0.8),
            ocr.OcrPage(numero=2, texto="dos", confianza=0.6),
        ]
    )
    monkeypatch.setattr(ingest, "extract_positioned_pdf", lambda p: [])
    monkeypatch.setattr(pdf_classify, "classify_pdf_file", lambda p: {})
    monkeypatch.setattr(pdf_classify, "is_text_based", lambda info: False)
    monkeypatch.setattr(render, "pdf_page_count", lambda p: 2)
    monkeypatch.setattr(ingest, "_pdf_verification", lambda *a, **k: ([], {}, [], {}))
    monkeypatch.setattr(ocr, "ocr_pdf_file", lambda p: result)

    out = ingest._extract_pdf_source([pdf], "libro-x", [], storage=None)

    assert out["fuente"] == ingest.FUENTE_PDF_ESCANEADO
    assert out["confianza_media"] == 0.7
