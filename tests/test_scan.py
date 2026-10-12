"""Scan preprocessing for image uploads (EXIF, grayscale, contrast, deskew, crop)."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

from app.services.scan import estimate_skew, preprocess_image


def _page(angle: float = 0.0, margin: int = 0) -> Image.Image:
    page = Image.new("L", (800, 1000), 245)
    draw = ImageDraw.Draw(page)
    for row in range(20):
        y = 100 + row * 40
        for word in range(8):
            x = 80 + word * 80
            draw.rectangle([x, y, x + 60, y + 12], fill=30)
    canvas = Image.new("L", (800 + 2 * margin, 1000 + 2 * margin), 245)
    canvas.paste(page, (margin, margin))
    return canvas.rotate(angle, fillcolor=245) if angle else canvas


def _jpeg(image: Image.Image, orientation: int | None = None) -> bytes:
    buffer = BytesIO()
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    image.convert("RGB").save(buffer, "JPEG", exif=exif.tobytes())
    return buffer.getvalue()


def test_estimate_skew_finds_the_correcting_angle() -> None:
    assert abs(estimate_skew(_page(4.0)) + 4.0) <= 0.3
    assert abs(estimate_skew(_page(0.0))) <= 0.3


def test_preprocess_applies_exif_orientation_deskews_and_outputs_gray_png() -> None:
    stored = _page(3.0).transpose(Image.Transpose.ROTATE_90)  # sensor pixels, displayed with orientation 6
    out = Image.open(BytesIO(preprocess_image(_jpeg(stored, orientation=6))))
    assert out.format == "PNG" and out.mode == "L"
    assert out.height > out.width
    assert abs(estimate_skew(out)) <= 0.3


def test_preprocess_crops_blank_margins() -> None:
    out = Image.open(BytesIO(preprocess_image(_jpeg(_page(margin=300)))))
    assert out.width < 900 and out.height < 1100


def test_preprocess_bounds_large_images() -> None:
    big = Image.new("L", (6000, 8000), 250)
    ImageDraw.Draw(big).rectangle([1000, 1000, 5000, 1200], fill=0)
    out = Image.open(BytesIO(preprocess_image(_jpeg(big))))
    assert max(out.size) <= 3000


def test_image_ingest_sends_preprocessed_png_to_ocr(monkeypatch, tmp_path) -> None:
    from app.services import ingest
    from app.services.extract import ExtractionResult, PageExtraction
    from app.services.storage import LocalStorage

    seen = []

    def fake_ocr(paths):
        seen.extend(Image.open(p).copy() for p in paths)
        return ExtractionResult(fuente="imagenes", paginas=[PageExtraction(numero=1, texto="x")])

    monkeypatch.setattr(ingest, "extract_from_images", fake_ocr)
    path = tmp_path / "foto.jpg"
    path.write_bytes(_jpeg(_page(3.0).transpose(Image.Transpose.ROTATE_90), orientation=6))
    source = ingest._ImageSource(path=path, data=path.read_bytes(), suffix=".jpg")
    result = ingest._extract_image_source([source], "libro-foto", [], LocalStorage(tmp_path / "media"))
    assert seen[0].mode == "L" and seen[0].height > seen[0].width
    assert result["pages"][0]["imagen_alto"] > result["pages"][0]["imagen_ancho"]
