"""Regresiones de localización literal y geometría real (sin OCR)."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.locator import extract_positioned_pdf, locate_matches, match_ranges
from app.services.search import make_snippet, _hit_from_doc


@pytest.mark.parametrize("text,query,expected", [
    ("¡Gracia, fe!", "gracia,", ["Gracia,"]),
    ("justificación justificacion", "justificacion", ["justificación", "justificacion"]),
    ("justificacio\u0301n", "justificacion", ["justificacio\u0301n"]),
    ("café\u0301", "cafe", ["café\u0301"]),
    ("oﬃce", "office", ["oﬃce"]),
    ("🙂 fe", "fe", ["fe"]),
    ("gracia y fe\ngracia fe", '"gracia fe"', ["gracia fe"]),
    ("gracia\n   fe y GRACIA fe", '"gracia fe"', ["gracia\n   fe", "GRACIA fe"]),
    ("gracia y fe", "gracia fe", ["gracia", "fe"]),
])
def test_original_offsets_and_literal_semantics(text, query, expected):
    ranges, truncated = match_ranges(text, query)
    assert [text[start:end] for start, end in ranges] == expected
    assert not truncated
    for value in expected:
        assert f"<mark>{value}</mark>" in make_snippet(text, query)


def _write_pdf(path, rotation=0, crop=False):
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=(600, 800))
    if rotation:
        c.setPageRotation(rotation)
    if crop:
        c.setCropBox((50, 50, 550, 750))
    c.setFont("Helvetica", 12)
    c.drawString(72, 700, "gracia fe, gracia")
    c.drawString(72, 680, "soberana")
    c.save()


def test_native_word_punctuation_multiline_and_repeated_geometry(tmp_path):
    path = tmp_path / "real.pdf"
    _write_pdf(path)
    page = extract_positioned_pdf(path)[0]
    matches, _ = locate_matches(page, "gracia")
    assert len(matches) == 2
    assert all(match["precision"] == "exacta" for match in matches)
    assert matches[0]["rects"] != matches[1]["rects"]
    x, y, width, height = matches[0]["rects"][0]
    assert x == pytest.approx(72.42 / 600, abs=.002)
    assert y == pytest.approx((800 - 708.616) / 800, abs=.002)
    assert width < .06  # not the entire line or a proportionally sliced run
    assert height < .02
    phrase, _ = locate_matches(page, '"gracia soberana"')
    assert len(phrase) == 1 and len(phrase[0]["rects"]) == 2
    punct, _ = locate_matches(page, "fe,")
    assert punct[0]["precision"] == "exacta"


@pytest.mark.parametrize("rotation,crop", [(90, False), (180, False), (270, False), (0, True)])
def test_rotated_or_shifted_crop_guard_preserves_text(tmp_path, rotation, crop):
    path = tmp_path / "guard.pdf"
    _write_pdf(path, rotation, crop)
    page = extract_positioned_pdf(path)[0]
    assert "gracia" in page["texto"]
    assert not page["posiciones"]
    assert page["advertencia_localizacion"]
    matches, _ = locate_matches(page, "gracia")
    assert all(match["precision"] == "sin_localizar" and not match["rects"] for match in matches)


def test_partial_native_geometry_never_claims_exact():
    page = {"texto": "fe", "posiciones": [[0, .1, .2, .01, .02]], "bloques": [{"texto": "fe", "bbox_norm": [.1, .2, .4, .1]}]}
    matches, _ = locate_matches(page, "fe")
    assert matches[0]["precision"] == "bloque"
    assert matches[0]["advertencia"]
    page["bloques"] *= 2
    assert locate_matches(page, "fe")[0][0]["precision"] == "sin_localizar"


def test_missing_bbox_legacy_and_caps():
    page = {"texto": "fe " * 150}
    matches, truncated = locate_matches(page, "fe")
    assert truncated and len(matches) == 100
    assert all(match["precision"] == "sin_localizar" for match in matches)
    hit = _hit_from_doc({**page, "libro_id": "x", "ref": "x/pagina/1", "numero": 1}, "fe", None)
    assert len(hit.coincidencias) == 8 and hit.coincidencias_truncadas


def test_long_phrase_snippet_marks_only_the_visible_matched_range():
    phrase = "gracia " * 45
    text = phrase + "fin"
    matches, _ = match_ranges(text, f'"{phrase.strip()}"')
    assert matches == [(0, len(phrase.strip()))]
    snippet = make_snippet(text, f'"{phrase.strip()}"', window=200)
    assert snippet == f"<mark>{text[:200]}</mark>…"


def test_page_query_recomputes_matches_and_does_not_expose_all_glyphs(monkeypatch):
    from app.routers import books
    page = {"texto": "fe gracia fe", "numero": 1, "posiciones": [], "bloques": []}
    class Pages:
        def find_one(self, query, projection=None):
            return page if query["ref"] == "x/pagina/1" else None
    monkeypatch.setattr(books, "pages_collection", lambda: Pages())
    client = TestClient(app)
    first = client.get("/api/v1/ref/x/pagina/1", params={"q": "fe"}).json()
    assert [(m["inicio"], m["fin"]) for m in first["coincidencias"]] == [(0, 2), (10, 12)]
    assert "posiciones" not in first
    assert client.get("/api/v1/ref/x/pagina/1", params={"q": '"fe gracia"'}).json()["coincidencias"][0]["fin"] == 9
    assert client.get("/api/v1/ref/x/pagina/1").json()["coincidencias"] == []
    assert client.get("/api/v1/ref/x/pagina/1", params={"q": "x" * 501}).status_code == 422


def test_shared_builder_prefers_native_over_visual_aids_and_reports_fallback(monkeypatch, tmp_path):
    from app.services import ingest, pdf_classify, render
    from app.services.storage import LocalStorage
    monkeypatch.setattr(pdf_classify, "classify_pdf_file", lambda _: {"tipo": "text_based", "encoding_issues": False})
    monkeypatch.setattr(render, "pdf_page_count", lambda _: 1)
    monkeypatch.setattr(ingest, "_pdf_verification", lambda *args: ([None], {1: [{"texto": "visual aid only", "bbox": [1, 1, 2, 2]}]}, [None], {}))
    monkeypatch.setattr(ingest, "extract_positioned_pdf", lambda _: [{"texto": "native label retained", "motor": "pypdfium2", "posiciones": [[0, .1, .2, .01, .02]]}])
    result = ingest._extract_pdf_source([Path("fake.pdf")], "x", [], LocalStorage(tmp_path))
    assert result["pages"][0]["texto"] == "native label retained"
    assert result["pages"][0]["motor"] == "pypdfium2"
    monkeypatch.setattr(ingest, "extract_positioned_pdf", lambda _: [])
    result = ingest._extract_pdf_source([Path("fake.pdf")], "x", [], LocalStorage(tmp_path))
    assert result["pages"][0]["texto"] == "visual aid only"
    assert result["pages"][0]["motor"] == "opendataloader"
