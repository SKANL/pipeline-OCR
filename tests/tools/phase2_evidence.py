"""Medición local reproducible; no utiliza MongoDB ni OCR remoto."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from app.services import ingest
from app.services.search import _match_block_for_query
from app.services.storage import LocalStorage

ROOT = Path(__file__).resolve().parents[2]
QUERIES = {
    "attention": [(1, '"Attention Is All You Need"'), (3, "encoder"), (4, '"Scaled Dot-Product Attention"'), (1, '"recurrent or convolutional"')],
    "bert": [(1, "BERT"), (3, "Pre-training"), (1, '"deep bidirectional"'), (15, "Entailment")],
    "resnet": [(1, '"Deep Residual Learning"'), (2, "identity"), (3, "residual"), (6, "ImageNet")],
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["before", "after", "after-final"])
    args = parser.parse_args()
    dest = ROOT / "_media" / "phase2-evidence" / args.stage
    if dest.exists():
        raise SystemExit(f"No se sobrescribe evidencia existente: {dest}")
    dest.mkdir(parents=True)
    results = {}
    for name, queries in QUERIES.items():
        pdf = ROOT / "tests/fixtures/real-pdfs" / name / "paper.pdf"
        with patch.object(ingest.ocr_service, "ocr_pdf_file", side_effect=AssertionError("OCR prohibido")):
            book = ingest.build_book_dir(pdf.parent, libro_id=name, storage=LocalStorage(dest))
        (dest / f"{name}.json").write_text(json.dumps(book, ensure_ascii=False), encoding="utf-8")
        measurements = []
        for number, query in queries:
            page = book["paginas"][number - 1]
            if args.stage == "before":
                _, _, box = _match_block_for_query(page, query.replace('"', ''))
                measurements.append({"pagina": number, "q": query, "precision": "bloque" if box else "sin_localizar", "bbox_norm": box})
            else:
                from app.services.locator import locate_matches
                from PIL import Image, ImageDraw
                matches, truncated = locate_matches(page, query)
                measurements.append({"pagina": number, "q": query, "coincidencias": matches, "truncadas": truncated})
                image_path = dest / name / "paginas" / f"{number}.png"
                with Image.open(image_path) as source:
                    image = source.convert("RGB")
                    draw = ImageDraw.Draw(image)
                    for match in matches:
                        for x, y, width, height in match["rects"]:
                            bounds = (x*image.width, y*image.height, (x+width)*image.width, (y+height)*image.height)
                            draw.rectangle(bounds, outline="red", width=2)
                    image.save(dest / f"{name}-{number}-{len(measurements)}-matches.png")
                    if matches and matches[0]["rects"]:
                        x, y, width, height = matches[0]["rects"][0]
                        bounds = (max(0, int(x*image.width)-20), max(0, int(y*image.height)-20), min(image.width, int((x+width)*image.width)+20), min(image.height, int((y+height)*image.height)+20))
                        image.crop(bounds).save(dest / f"{name}-{number}-{len(measurements)}-crop.png")
        results[name] = {"sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(), "paginas": len(book["paginas"]), "caracteres": sum(len(p["texto"]) for p in book["paginas"]), "mediciones": measurements}
        print(name, results[name]["paginas"], results[name]["caracteres"])
    (dest / "report.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(dest)


if __name__ == "__main__":
    main()
