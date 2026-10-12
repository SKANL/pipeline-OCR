"""Tests del router de extracción: elige local vs OCR según clasificación."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import extract, pdf_classify
from app.services.extract import PageExtraction
from app.services.ocr import OcrPage, OcrResult


def test_text_based_pdf_uses_local_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pdf_classify,
        "classify_pdf_file",
        lambda path: {"tipo": "text_based", "confianza": 0.9, "paginas_ocr": [], "encoding_issues": False},
    )
    monkeypatch.setattr(
        extract,
        "_extract_pdf_local",
        lambda path: [PageExtraction(numero=1, texto="texto local", motor="pdf-inspector")],
    )

    def _boom(*args, **kwargs):  # pragma: no cover - no debe ejecutarse
        raise AssertionError("no se debe llamar a OCR en un PDF con texto")

    monkeypatch.setattr(extract.ocr_service, "ocr_pdf_file", _boom)

    result = extract.extract_from_pdf(Path("fake.pdf"))
    assert result.fuente == extract.FUENTE_PDF_DIGITAL
    assert result.motor == extract.MOTOR_LOCAL
    assert result.textos == ["texto local"]
    assert result.paginas[0].ocr_confianza is None


def test_scanned_pdf_routes_to_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pdf_classify,
        "classify_pdf_file",
        lambda path: {"tipo": "scanned", "confianza": 0.95, "paginas_ocr": [1, 2], "encoding_issues": False},
    )
    monkeypatch.setattr(
        extract.ocr_service,
        "ocr_pdf_file",
        lambda path: OcrResult(
            paginas=[
                OcrPage(numero=1, texto="pagina uno", confianza=0.8, modelo="mistral-ocr-latest"),
                OcrPage(numero=2, texto="pagina dos", confianza=0.6, modelo="mistral-ocr-latest"),
            ],
            modelo="mistral-ocr-latest",
        ),
    )

    result = extract.extract_from_pdf(Path("fake.pdf"))
    assert result.fuente == extract.FUENTE_PDF_ESCANEADO
    assert result.motor == "mistral"
    assert result.textos == ["pagina uno", "pagina dos"]
    assert result.paginas[0].ocr_confianza == 0.8
    assert result.confianza_media == pytest.approx(0.7)


def test_encoding_issues_force_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pdf_classify,
        "classify_pdf_file",
        lambda path: {"tipo": "text_based", "confianza": 0.9, "paginas_ocr": [], "encoding_issues": True},
    )
    monkeypatch.setattr(
        extract.ocr_service,
        "ocr_pdf_file",
        lambda path: OcrResult(paginas=[OcrPage(numero=1, texto="ocr", confianza=None)]),
    )
    result = extract.extract_from_pdf(Path("fake.pdf"))
    assert result.fuente == extract.FUENTE_PDF_ESCANEADO
