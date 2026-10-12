"""Local-only visual evidence; never calls OCR, MongoDB, or remote services."""
from __future__ import annotations

import argparse
import hashlib
import json
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from app.services import ingest, render, structure
from app.services.storage import LocalStorage

ROOT = Path(__file__).resolve().parents[2]
SELECTED = {"attention": [3, 4, 11, 12], "bert": [3, 15], "resnet": [2, 3, 4, 6]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["before", "after", "verified"])
    args = parser.parse_args()
    dest = ROOT / "_media" / "figure-evidence" / args.stage
    if dest.exists():
        raise SystemExit(f"Refusing to overwrite evidence: {dest}")
    dest.mkdir(parents=True)
    report = {}
    for name, selected in SELECTED.items():
        pdf = ROOT / "tests/fixtures/real-pdfs" / name / "paper.pdf"
        raw_dir = dest / name / "raw"
        arch = structure.extract_structure(pdf, output_dir=raw_dir)
        urls, blocks, sizes, figures = ingest._pdf_verification([pdf], name, LocalStorage(dest))
        pages = {}
        for number in selected:
            candidates = arch["figuras"].get(number, [])
            width, height = render.pdf_page_size(pdf, number - 1)
            tiles = []
            for index, candidate in enumerate(candidates):
                try:
                    data = render.render_pdf_region(pdf, number - 1, candidate["bbox"])
                    path = dest / name / f"candidate-{number}-{index}.png"
                    path.write_bytes(data)
                    with Image.open(BytesIO(data)) as image:
                        tile = Image.new("RGB", (260, 210), "#eeeeee")
                        image.thumbnail((250, 175))
                        tile.paste(image.convert("RGB"), (5, 25))
                        ImageDraw.Draw(tile).text((5, 5), f"p{number} candidate {index}", fill="black")
                        tiles.append(tile)
                except Exception as exc:
                    candidate["crop_error"] = str(exc)
            if tiles:
                sheet = Image.new("RGB", (260 * min(4, len(tiles)), 210 * ((len(tiles) + 3) // 4)), "white")
                for index, tile in enumerate(tiles):
                    sheet.paste(tile, ((index % 4) * 260, (index // 4) * 210))
                sheet.save(dest / name / f"candidates-{number}.png")
            pages[number] = {
                "raw_candidates": candidates,
                "below_previous_two_percent": sum((f["bbox"][2]-f["bbox"][0])*(f["bbox"][3]-f["bbox"][1]) < .02*width*height for f in candidates),
                "saved_figures": figures.get(number, []),
                "source_blocks": arch["bloques"].get(number, []),
                "retained_blocks": blocks.get(number, []),
                "page_image": urls[number-1],
                "page_dimensions": sizes[number-1],
            }
        report[name] = {"sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(), "pages": pages,
                        "all_saved_figures": sum(len(value) for value in figures.values())}
    (dest / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(dest / "report.json")


if __name__ == "__main__":
    main()
