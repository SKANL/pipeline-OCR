"""OPENDATALOADER_ENABLED: off skips the JVM; PDFium text still indexes the page."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from app.config import get_settings
from app.services import structure


def _counting_converter(monkeypatch) -> list:
    calls = []
    monkeypatch.setitem(sys.modules, "opendataloader_pdf", SimpleNamespace(convert=lambda **kw: calls.append(kw)))
    return calls


def test_disabled_never_starts_opendataloader(monkeypatch, tmp_path) -> None:
    calls = _counting_converter(monkeypatch)
    monkeypatch.setattr(get_settings(), "opendataloader_enabled", False)
    assert structure.extract_structure(tmp_path / "x.pdf") == {"bloques": {}, "figuras": {}}
    assert calls == []


def test_enabled_runs_opendataloader(monkeypatch, tmp_path) -> None:
    calls = _counting_converter(monkeypatch)
    monkeypatch.setattr(get_settings(), "opendataloader_enabled", True)
    structure.extract_structure(tmp_path / "x.pdf")
    assert len(calls) == 1


def test_digital_pdf_is_indexed_without_opendataloader(monkeypatch, tmp_path) -> None:
    from reportlab.pdfgen import canvas

    from app.services import ingest
    from app.services.storage import LocalStorage

    pdf = tmp_path / "d.pdf"
    c = canvas.Canvas(str(pdf))
    c.drawString(72, 720, "Texto digital sin opendataloader")
    c.save()
    calls = _counting_converter(monkeypatch)
    monkeypatch.setattr(get_settings(), "opendataloader_enabled", False)
    out = ingest._extract_pdf_source([pdf], "libro-odl", [], LocalStorage(str(tmp_path / "media")))
    assert calls == []
    page = out["pages"][0]
    assert "Texto digital sin opendataloader" in page["texto"]
    assert page["motor"] == "pypdfium2" and page["figuras"] == []
