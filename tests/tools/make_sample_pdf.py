"""Genera PDF de ejemplo para probar el router de extracción (dev).

Crea en `tests/fixtures/generated-pdfs/`:

- `texto_digital.pdf`: PDF de 3 páginas con capa de texto (extraíble local).
- `escaneado.pdf`: PDF de 3 páginas renderizadas como imágenes (rutea a OCR).

El contenido es ficticio y sin derechos de autor.

Uso:
    uv run python -m tests.tools.make_sample_pdf
"""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "tests/fixtures/generated-pdfs"

PAGES = [
    "El pacto de la gracia sostiene al creyente en la prueba.",
    "La justificacion por la fe es el centro del evangelio.",
    "El Espiritu Santo consuela y santifica a la iglesia.",
]


def make_text_pdf(path: Path) -> None:
    """Crea un PDF con capa de texto (3 páginas)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    for index, texto in enumerate(PAGES, start=1):
        c.setFont("Helvetica", 14)
        c.drawString(72, 760, f"Documento digital de prueba - pagina {index}")
        c.setFont("Helvetica", 11)
        c.drawString(72, 730, texto)
        c.showPage()
    c.save()


def _page_image(texto: str):
    """Renderiza una página como imagen RGB."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    draw.text((90, 140), texto, fill="black")
    draw.text((90, 180), "(contenido ficticio de prueba)", fill="gray")
    return image


def make_scanned_pdf(path: Path) -> None:
    """Crea un PDF cuyas páginas son imágenes (se clasifica como escaneado)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    for index, texto in enumerate(PAGES, start=1):
        buffer = BytesIO()
        _page_image(f"Escaneo de prueba - pagina {index}: {texto}").save(buffer, "PNG")
        buffer.seek(0)
        c.drawImage(ImageReader(buffer), 0, 0, width=A4[0], height=A4[1])
        c.showPage()
    c.save()


def main() -> int:
    if OUTPUT_DIR.exists() and any(OUTPUT_DIR.iterdir()):
        raise SystemExit("Refusing to overwrite existing PDF fixtures")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    text_path = OUTPUT_DIR / "texto_digital.pdf"
    scanned_path = OUTPUT_DIR / "escaneado.pdf"
    make_text_pdf(text_path)
    make_scanned_pdf(scanned_path)
    print(f"PDF de ejemplo creados en: {OUTPUT_DIR}")
    print(f"  - {text_path.name} (capa de texto, 3 paginas)")
    print(f"  - {scanned_path.name} (paginas como imagen, 3 paginas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
