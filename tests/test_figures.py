"""Figure preservation, conservative geometry and real-fixture regressions."""
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.services import ingest, render, structure
from app.services.storage import LocalStorage
from app.services.text import fold_text


def png():
    buffer = BytesIO()
    Image.new("RGB", (600, 800), "white").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("box", [[0, 0, 0, 1], [2, 0, 1, 1], [0, 0, float("nan"), 1], [0, 0, 1, float("inf")]])
def test_invalid_boxes_are_rejected(box):
    assert not structure._valid_bbox(box)
    assert structure.normalize_bbox(box, 600, 800) is None
    with pytest.raises(ValueError):
        render.crop_page_png(png(), box, 600, 800)


def test_small_figure_kept_with_dimensions_and_caption(tmp_path):
    figure = {"bbox": [50, 100, 60, 110], "tipo": "image", "orden": 2}
    caption = {"bbox": [40, 80, 120, 95], "texto": "Figure 1: A small real aid.", "tipo": "caption", "orden": 3}
    assert ingest._significant_figures([figure], 600, 800)[0]["bbox"] == figure["bbox"]
    records = ingest._crop_figures(Path("unused.pdf"), 1, [figure], "book", 1,
                                  LocalStorage(tmp_path), 150, 600, 800, page_png=png(), blocks=[caption])
    record = records[0]
    assert (record["imagen_ancho"], record["imagen_alto"]) == (10, 10)
    assert record["pie"] == caption["texto"]
    assert record["texto_alternativo"] == caption["texto"]
    assert ingest._blocks_outside_figures([caption], records) == [caption]


def test_fragments_warn_without_merging_unrelated_figures(tmp_path):
    figures = [{"bbox": [10, 100, 100, 200]}, {"bbox": [20, 150, 30, 160]},
               {"bbox": [300, 100, 400, 200]}]
    records = ingest._crop_figures(Path("unused"), 1, figures, "book", 1,
                                  LocalStorage(tmp_path), 150, 600, 800, page_png=png())
    assert [r["bbox"] for r in records] == [f["bbox"] for f in figures]
    assert [r["estado"] for r in records] == ["fragmento", "fragmento", "no_verificado"]
    assert all(r["imagen_url"] for r in records)


def test_aligned_panels_read_left_to_right_without_union():
    right = {"bbox": [300, 100, 400, 200], "orden": 1}
    left = {"bbox": [10, 100, 100, 195], "orden": 2}
    result = ingest._significant_figures([right, left], 600, 800)
    assert [r["bbox"] for r in result] == [left["bbox"], right["bbox"]]
    assert [r["orden"] for r in result] == [1, 2]
    assert [r["orden_fuente"] for r in result] == [2, 1]


def test_save_failure_preserves_searchable_prose_and_caption(monkeypatch, tmp_path):
    from reportlab.pdfgen import canvas
    pdf = tmp_path / "fixture.pdf"
    c = canvas.Canvas(str(pdf), pagesize=(600, 800))
    c.drawString(10, 10, "fixture")
    c.save()
    blocks = [{"bbox": [20, 150, 80, 160], "texto": "Grácia searchable prose", "tipo": "paragraph"},
              {"bbox": [10, 70, 110, 90], "texto": "Figure 1: Keep this caption", "tipo": "caption"}]
    monkeypatch.setattr(structure, "extract_structure", lambda _: {"bloques": {1: blocks}, "figuras": {1: [{"bbox": [10, 100, 100, 200]}]}})
    storage = LocalStorage(tmp_path / "media")
    def fail(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr(storage, "save_figure", fail)
    _, retained, _, figures = ingest._pdf_verification([pdf], "book", storage)
    assert [b["texto"] for b in retained[1]] == [b["texto"] for b in blocks]
    assert "gracia searchable prose" in fold_text(" ".join(b["texto"] for b in retained[1]))
    assert figures[1][0]["estado"] == "pagina_original"
    assert figures[1][0]["imagen_url"] is None


@pytest.mark.parametrize("geometry", ["rotation", "crop"])
def test_guarded_geometry_preserves_original_and_text(geometry, monkeypatch, tmp_path):
    import pypdfium2 as pdfium
    pdf = tmp_path / "geometry.pdf"
    document = pdfium.PdfDocument.new()
    page = document.new_page(600, 800)
    if geometry == "rotation":
        page.set_rotation(90)
    else:
        page.set_cropbox(20, 30, 500, 700)
    document.save(str(pdf))
    page.close()
    document.close()
    with pytest.raises(ValueError, match="Unsupported"):
        render.pdf_page_geometry(pdf, 0)
    assert render.render_pdf_page(pdf, 0).startswith(b"\x89PNG")
    monkeypatch.setattr(structure, "extract_structure", lambda _: {
        "bloques": {1: [{"bbox": [30, 40, 60, 70], "texto": "keep"}]},
        "figuras": {1: [{"bbox": [30, 40, 60, 70]}]}})
    urls, blocks, sizes, figures = ingest._pdf_verification([pdf], "book", LocalStorage(tmp_path / "media"))
    assert urls[0] and sizes[0]
    assert blocks[1][0]["texto"] == "keep" and blocks[1][0]["bbox_norm"] is None
    assert figures[1][0]["estado"] == "pagina_original"
    assert "Unsupported" in figures[1][0]["advertencia"]


@pytest.mark.parametrize("method,args", [("save", ("../escape", "file.png")), ("save_page_image", ("../escape", 1)), ("save_figure", ("../escape", 1, 0))])
def test_writes_use_safe_path(method, args, tmp_path):
    with pytest.raises(ValueError):
        getattr(LocalStorage(tmp_path / "media"), method)(*args, png())
    assert not (tmp_path / "escape").exists()


def test_real_bert_small_components_and_caption_survive(tmp_path):
    pdf = Path(__file__).resolve().parents[1] / "tests/fixtures/real-pdfs/bert/paper.pdf"
    if not pdf.exists():
        pytest.skip("Local real fixture unavailable")
    arch = structure.extract_structure(pdf)
    assert arch["figuras"].get(3) and arch["figuras"].get(15), "Real converter returned no BERT components"
    for number in (3, 15):
        width, height = render.pdf_page_geometry(pdf, number - 1)
        figures = ingest._significant_figures(arch["figuras"][number], width, height)
        assert any((f["bbox"][2]-f["bbox"][0])*(f["bbox"][3]-f["bbox"][1]) < .02*width*height for f in figures)
        records = ingest._crop_figures(pdf, number, figures, "bert", number, LocalStorage(tmp_path), 150,
                                      width, height, page_png=render.render_pdf_page(pdf, number-1), blocks=arch["bloques"][number])
        assert len(records) == len(figures) and all(r["imagen_url"] for r in records)
        # These visually confirmed composite parts do NOT overlap. No geometric
        # rule may certify their completeness; the reader defaults to original.
        assert all(r["estado"] in ("no_verificado", "fragmento") for r in records)
        assert all(r["advertencia"] for r in records)
        assert any(structure.is_caption(b) and "Figure" in b["texto"] for b in arch["bloques"][number])
