"""Pluggable OCR providers: registry, override, error classes, adapters (no network)."""

from __future__ import annotations

import io
import json
import shutil
from types import SimpleNamespace

import httpx
import pytest

from app.config import get_settings
from app.services import jobs, ocr


def _png(width: int = 40, height: int = 20) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("L", (width, height), 255).save(buffer, format="PNG")
    return buffer.getvalue()


def test_registry_lists_the_three_providers() -> None:
    assert {"tesseract", "mistral", "glm"} <= set(ocr.PROVIDERS)


def test_default_provider_is_setting_and_override_wins(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "ocr_provider", "mistral")
    assert ocr.provider_name() == "mistral"
    with ocr.use_provider("glm"):
        assert ocr.provider_name() == "glm"
    with ocr.use_provider(None):  # no override -> setting
        assert ocr.provider_name() == "mistral"
    assert ocr.provider_name() == "mistral"


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValueError):
        ocr.validate_provider("nope")
    assert ocr.validate_provider(None) is None
    assert ocr.validate_provider("tesseract") == "tesseract"


def test_facade_dispatches_to_selected_provider(monkeypatch) -> None:
    fake = SimpleNamespace(
        NAME="fake", missing_config=lambda: None,
        ocr_image=lambda data, mime: ocr.OcrPage(numero=None, texto="hola", confianza=0.5, motor="fake", modelo="m1"),
    )
    monkeypatch.setitem(ocr.PROVIDERS, "fake", lambda: fake)
    with ocr.use_provider("fake"):
        result = ocr.ocr_image_bytes(b"x")
    assert result.paginas[0].texto == "hola" and result.motor == "fake" and result.modelo == "m1"


def test_missing_config_raises_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "glm_api_key", "")
    with ocr.use_provider("glm"), pytest.raises(ocr.OcrNotConfiguredError):
        ocr.require_configured()


def test_http_error_classification() -> None:
    with pytest.raises(ocr.OcrPermanentError, match="plan sin OCR"):
        ocr.raise_for_http("mistral", 429, {"x-ratelimit-limit-req-minute": "0"}, "quota")
    with pytest.raises(ocr.OcrRetryableError):
        ocr.raise_for_http("mistral", 429, {"x-ratelimit-limit-req-minute": "60"}, "slow down")
    with pytest.raises(ocr.OcrPermanentError):
        ocr.raise_for_http("glm", 401, {}, "bad key")
    with pytest.raises(ocr.OcrRetryableError):
        ocr.raise_for_http("glm", 503, {}, "busy")


def test_jobs_treat_ocr_permanent_errors_as_permanent() -> None:
    assert jobs.is_permanent(ocr.OcrPermanentError("x"))
    assert jobs.is_permanent(ocr.OcrNotConfiguredError("x"))
    assert not jobs.is_permanent(ocr.OcrRetryableError("x"))


def test_mistral_sdk_429_with_zero_quota_is_permanent(monkeypatch) -> None:
    from app.services import ocr_mistral

    class SDKError(Exception):
        status_code = 429
        raw_response = SimpleNamespace(headers={"x-ratelimit-limit-req-minute": "0"})

    def boom(**kwargs):
        raise SDKError("rate limited")

    monkeypatch.setattr(get_settings(), "mistral_api_key", "k")
    monkeypatch.setattr(ocr_mistral, "_client", lambda: SimpleNamespace(ocr=SimpleNamespace(process=boom)))
    with pytest.raises(ocr.OcrPermanentError, match="plan sin OCR"):
        ocr_mistral.ocr_image(b"x", "image/png")


def test_glm_parses_layout_details_into_blocks(monkeypatch) -> None:
    from app.services import ocr_glm

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "t", "created": 1, "model": "GLM-OCR", "md_results": "# Titulo\n\nTexto",
            "layout_details": [[
                {"index": 1, "label": "text", "bbox_2d": [0.1, 0.2, 0.5, 0.3], "content": "Titulo", "width": 600, "height": 800},
                {"index": 2, "label": "image", "bbox_2d": [0.1, 0.4, 0.9, 0.8], "content": "https://x/img.png"},
            ]],
            "data_info": {"num_pages": 1, "pages": [{"width": 600, "height": 800}]},
        })

    monkeypatch.setattr(get_settings(), "glm_api_key", "secret")
    monkeypatch.setattr(ocr_glm, "_transport", httpx.MockTransport(handler))
    page = ocr_glm.ocr_image(b"\x89PNG", "image/png")

    assert seen["url"].endswith("/layout_parsing") and seen["auth"] == "Bearer secret"
    assert seen["body"]["model"] == get_settings().glm_ocr_model
    assert page.texto == "Titulo\n\nTexto" and page.motor == "glm"
    assert page.bloques == [{"texto": "Titulo", "tipo": "text", "bbox": None,
                             "bbox_norm": pytest.approx([0.1, 0.2, 0.4, 0.1])}]


def test_glm_http_errors_are_classified(monkeypatch) -> None:
    from app.services import ocr_glm

    monkeypatch.setattr(get_settings(), "glm_api_key", "secret")
    monkeypatch.setattr(ocr_glm, "_transport", httpx.MockTransport(lambda r: httpx.Response(401, json={"code": 1, "message": "bad"})))
    with pytest.raises(ocr.OcrPermanentError):
        ocr_glm.ocr_image(b"x", "image/png")
    monkeypatch.setattr(ocr_glm, "_transport", httpx.MockTransport(lambda r: httpx.Response(500, text="oops")))
    with pytest.raises(ocr.OcrRetryableError):
        ocr_glm.ocr_image(b"x", "image/png")


def test_tesseract_groups_words_into_line_blocks(monkeypatch) -> None:
    from app.services import ocr_tesseract

    data = {
        "text": ["", "Hola", "mundo", "Adios"],
        "conf": [-1, 90, 80, 70],
        "left": [0, 10, 60, 10], "top": [0, 10, 12, 50], "width": [0, 40, 50, 60], "height": [0, 20, 18, 20],
        "block_num": [1, 1, 1, 1], "par_num": [1, 1, 1, 2], "line_num": [1, 1, 1, 1],
    }
    monkeypatch.setattr(ocr_tesseract, "_image_to_data", lambda image, lang: data)
    page = ocr_tesseract.ocr_image(_png(200, 100), "image/png")

    assert page.texto == "Hola mundo\n\nAdios"
    assert page.confianza == pytest.approx(0.8)
    assert page.motor == "tesseract" and page.modelo == get_settings().ocr_langs
    assert page.bloques[0]["texto"] == "Hola mundo"
    assert page.bloques[0]["bbox_norm"] == pytest.approx([0.05, 0.1, 0.5, 0.2])


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract binary not installed (runs in the Docker image)")
def test_tesseract_real_run() -> None:
    from PIL import Image, ImageDraw

    from app.services import ocr_tesseract

    image = Image.new("L", (600, 120), 255)
    ImageDraw.Draw(image).text((20, 40), "Biblioteca", fill=0, font_size=48)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page = ocr_tesseract.ocr_image(buffer.getvalue(), "image/png")
    assert "Biblioteca" in page.texto


def test_upload_request_validates_ocr_proveedor() -> None:
    from pydantic import ValidationError

    from app.routers.jobs import SubidaRequest

    archivo = {"nombre": "a.pdf", "tipo_contenido": "application/pdf", "tamano": 1, "sha256": "a" * 64}
    assert SubidaRequest(archivos=[archivo], ocr_proveedor="glm").ocr_proveedor == "glm"
    assert SubidaRequest(archivos=[archivo]).ocr_proveedor is None
    with pytest.raises(ValidationError):
        SubidaRequest(archivos=[archivo], ocr_proveedor="nope")


def test_process_runs_under_the_job_provider(monkeypatch) -> None:
    seen = []

    def fake_process(job):
        seen.append(ocr.provider_name())
        return 1

    monkeypatch.setattr(jobs, "_process_pages", fake_process)
    assert jobs.process({"ocr_proveedor": "glm"}) == 1
    monkeypatch.setattr(get_settings(), "ocr_provider", "tesseract")
    jobs.process({})
    assert seen == ["glm", "tesseract"]


def test_ocr_blocks_without_pdf_points_survive_assembly() -> None:
    from app.services import ingest

    page = {"numero": 1, "texto": "Hola", "motor": "tesseract",
            "bloques": [{"texto": "Hola", "tipo": "linea", "bbox": None, "bbox_norm": [0.1, 0.1, 0.2, 0.05]}]}
    libro = ingest._assemble_libro(
        libro_id="ocr-bloques", metadatos=ingest._metadatos_from({"titulo": "x"}), capitulos=[],
        pages=ingest._pages_from_extraction([page], []), fuente="imagenes", motor="tesseract",
        modelo="spa+lat", confianza_media=None, origen=["a.png"])
    assert libro["paginas"][0]["bloques"][0]["bbox_norm"] == [0.1, 0.1, 0.2, 0.05]


def test_public_job_error_hides_provider_detail() -> None:
    message = jobs.public_error(ocr.OcrPermanentError("glm: HTTP 401 {'token': 'abc123'}"))
    assert "abc123" not in message and "glm" not in message


def test_glm_malformed_200_payload_is_retryable(monkeypatch) -> None:
    from app.services import ocr_glm

    monkeypatch.setattr(get_settings(), "glm_api_key", "secret")
    for bad in (httpx.Response(200, text="<html>"), httpx.Response(200, json=["x"])):
        monkeypatch.setattr(ocr_glm, "_transport", httpx.MockTransport(lambda r, bad=bad: bad))
        with pytest.raises(ocr.OcrRetryableError):
            ocr_glm.ocr_image(b"x", "image/png")


def test_tesseract_undecodable_image_is_permanent() -> None:
    from app.services import ocr_tesseract

    with pytest.raises(ocr.OcrPermanentError):
        ocr_tesseract.ocr_image(b"not an image", "image/png")
