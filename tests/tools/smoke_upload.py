"""Ensayo end-to-end de la subida (upload) contra MongoDB real.

Sube el PDF de texto generado por `tests.tools.make_sample_pdf`, verifica que
el libro aparece, imprime el resumen y muestra `/search` golpeando el texto
subido. Si `MISTRAL_API_KEY` está configurada, además sube dos imágenes
(ruta OCR); si no, lo omite explícitamente.

Uso:
    uv run python -m tests.tools.make_sample_pdf
    uv run python -m tests.tools.smoke_upload
"""

from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import ensure_indexes  # noqa: E402
from app.main import app  # noqa: E402

API = "/api/v1"
SAMPLES = ROOT / "tests/fixtures/generated-pdfs"


def _image_bytes(texto: str) -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1240, 1754), "white")
    ImageDraw.Draw(image).text((90, 140), texto, fill="black")
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def main() -> int:
    pdf_path = SAMPLES / "texto_digital.pdf"
    if not pdf_path.exists():
        print(f"Falta {pdf_path}. Corre primero: uv run python -m tests.tools.make_sample_pdf")
        return 1

    settings = get_settings()
    print("Indices:", ensure_indexes())
    client = TestClient(app)

    # 1) Libro PDF de texto (extraccion local).
    response = client.post(
        f"{API}/ingest/upload",
        files=[("files", (pdf_path.name, pdf_path.read_bytes(), "application/pdf"))],
        data={
            "libro_id": "muestra-texto-digital",
            "metadatos": json.dumps(
                {
                    "titulo": "Muestra PDF Digital",
                    "autor": "Smoke Test",
                    "autor_normalizado": "Smoke, Test",
                    "genero": "teologia",
                }
            ),
        },
    )
    print("\nUpload PDF ->", response.status_code, response.json())
    folio = response.json().get("libro_id")

    # 1b) Imagen de pagina + verificacion (capa Pass 2a).
    page_doc = client.get(f"{API}/ref/{folio}/pagina/1").json()
    print(f"\nImagen de pagina 1 -> imagen_url={page_doc.get('imagen_url')!r} "
          f"bloques={len(page_doc.get('bloques') or [])}")
    image_response = client.get(f"{API}/pages/{folio}/pagina/1/imagen")
    print(f"GET /pages/{folio}/pagina/1/imagen -> {image_response.status_code} "
          f"content-type={image_response.headers.get('content-type')} "
          f"bytes={len(image_response.content)}")
    assert image_response.status_code == 200, image_response.text
    assert image_response.headers.get("content-type") == "image/png"

    # 2) Libro de imagenes (ruta OCR) solo si hay API key.
    if settings.mistral_api_key:
        image_response = client.post(
            f"{API}/ingest/upload",
            files=[
                ("files", ("pagina2.png", _image_bytes("Escaneo pagina 2: gracia"), "image/png")),
                ("files", ("pagina1.png", _image_bytes("Escaneo pagina 1: gracia"), "image/png")),
            ],
            data={
                "libro_id": "muestra-imagenes",
                "metadatos": json.dumps({"titulo": "Muestra Imagenes", "genero": "teologia"}),
            },
        )
        print("\nUpload imagenes ->", image_response.status_code, image_response.json())
    else:
        print(
            "\nMISTRAL_API_KEY vacia: se OMITE la subida de imagenes "
            "(rama OCR). La rama se prueba con un test mockeado (tests/test_extract.py)."
        )

    # 3) Busqueda sobre el contenido subido.
    resp = client.get(f"{API}/search", params={"q": "gracia", "limit": 3}).json()
    print(f"\n=== Busqueda 'gracia' -> total={resp['total']} ===")
    for hit in resp["resultados"]:
        print(f"  - ref={hit['ref']!r} libro_id={hit['libro_id']!r} titulo={hit['titulo']!r}")
        print(f"    snippet={hit['snippet'][:110]!r}")
        print(f"    imagen_url={hit.get('imagen_url')!r} bbox={hit.get('bbox')!r}")

    ref = f"{folio}/pagina/1"
    page = client.get(f"{API}/ref/{ref}")
    print(f"\nRef navegacion {ref} -> {page.status_code}")
    if page.status_code == 200:
        print("  ref_siguiente:", page.json().get("ref_siguiente"))

    # 4) Indice de paginas (Pass 2b): lista sin texto.
    index = client.get(f"{API}/books/{folio}/paginas", params={"limit": 20, "offset": 0}).json()
    print(f"\n=== Indice de paginas {folio} -> total={index['total']} ===")
    for item in index["resultados"]:
        print(
            f"  - numero={item['numero']} ref={item['ref']!r} "
            f"palabras={item['conteo_palabras']} imagen_url={item['imagen_url']!r}"
        )

    # 5) Facetas para los filtros.
    facetas = client.get(f"{API}/facets").json()
    print("\n=== Facetas ===")
    print("  generos:", facetas["generos"][:5])
    print("  autores:", facetas["autores"][:5])

    # 6) /books filtrado por genero y autor.
    filtrado = client.get(f"{API}/books", params={"genero": "teologia", "autor": "smoke"}).json()
    print(f"\n=== /books?genero=teologia&autor=smoke -> total={filtrado['total']} ===")
    for book in filtrado["resultados"]:
        meta = book["metadatos"]
        print(
            f"  - {book['libro_id']} genero={meta.get('genero')!r} autor={meta.get('autor')!r}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
