"""Inspección de la API instalada y marcos reales; no usa OCR ni conversores."""
from collections import Counter
import json
from importlib.metadata import version

import pdf_inspector
import pypdfium2

from tests.tools.phase2_evidence import ROOT, QUERIES


def main():
    report = {"versiones": {name: version(name) for name in ("pdf-inspector", "pypdfium2", "opendataloader-pdf")},
              "contrato_textitem": pdf_inspector.TextItem.__doc__, "fixtures": {}}
    for name in QUERIES:
        path = ROOT / "tests/fixtures/real-pdfs" / name / "paper.pdf"
        items = pdf_inspector.extract_text_with_positions(str(path))
        frames = []
        with pypdfium2.PdfDocument(str(path)) as doc:
            for page in doc:
                try:
                    frames.append({"bbox": page.get_bbox(), "cropbox": page.get_cropbox(), "mediabox": page.get_mediabox(), "rotation": page.get_rotation(), "size": page.get_size()})
                finally:
                    page.close()
        report["fixtures"][name] = {"runs": len(items), "runs_multipalabra": sum(len(item.text.split()) > 1 for item in items),
                                    "runs_una_palabra": sum(len(item.text.split()) == 1 for item in items), "granularidad": dict(Counter(len(item.text.split()) for item in items)),
                                    "primero": {key: getattr(items[0], key) for key in ("text", "page", "x", "y", "width", "height", "rotation", "advance_known")}, "marcos": frames}
        print(name, "runs", len(items), "multiword", report["fixtures"][name]["runs_multipalabra"])
    dest = ROOT / "_media/phase2-evidence/inspector.json"
    if dest.exists():
        raise SystemExit("No se sobrescribe la inspección existente")
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(dest)


if __name__ == "__main__":
    main()
