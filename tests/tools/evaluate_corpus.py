"""Evaluate the ingest pipeline on the public-domain + synthetic corpus.

Runs the REAL per-page job path (`jobs._extract_page` -> ingest builders ->
`ingest._assemble_libro`), persists into the throwaway DB `biblioteca_eval`
(loopback only, dropped on each run) and searches with `search.search_pages`.

Metrics: CER/WER vs ground truth (folded, punctuation-free), header/footer
leakage, hyphenation splits, search recall@10 and MRR.

Live Mistral OCR: only for files under `tests/fixtures/real-pdfs/public-domain/`,
cached by page/bytes and capped per file (see BUDGET). Synthetic files never
reach OCR.

Uso: uv run python -m tests.tools.evaluate_corpus --etiqueta base|despues
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["MONGODB_DB"] = "biblioteca_eval"
os.environ["MEDIA_ROOT"] = str(Path(tempfile.gettempdir()) / "pipeline_ocr_eval_media")
os.environ["S3_ENDPOINT_URL"] = ""
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.services import ingest, jobs, ocr, pdf_classify, structure  # noqa: E402
from app.services.extract import ExtractionResult, PageExtraction  # noqa: E402
from app.services.storage import LocalStorage  # noqa: E402
from tests.tools.eval_metrics import (  # noqa: E402
    broken_splits, error_rates, leakage, residual_hyphens, wikisource_pages)

PD = ROOT / "tests/fixtures/real-pdfs/public-domain"
SYN = ROOT / "tests/fixtures/generated-pdfs/eval"
CACHE = SYN / "ocr-cache"
DOCS = ROOT / "docs"
BUDGET = {"astete-1787": 20, "molinero-1695": 5, "ordo-1812": 5, "astete-1700-foto": 3}

PHOTO_GT = ("DOCTRINA CHRISTIANA. CON SU BREVE DECLAracion, por Preguntas, y Respuestas. "
            "POR EL PADRE GASPAR de Astete de la Compañia de JESUS. Aora de nuevo corregida, "
            "y enmendada. Con Licencia: En Valladolid, por Alonso del Riego, Impressor de Libros, y de la")


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------
def corpus() -> list[dict]:
    gt = wikisource_pages(PD / "astete-1787-scan/astete-1787.gt.txt")
    astete_pages = sorted(gt)[:20]
    items = [
        {"slug": "astete-1787", "kind": "pdf", "path": PD / "astete-1787-scan/astete-1787.pdf",
         "pages": astete_pages, "modos": ["ocr", "capa"],
         "gt": [gt[n]["texto"] for n in astete_pages], "mobiliario": [gt[n]["mobiliario"] for n in astete_pages],
         "consultas": [("santiguar", 12), ("cautividad", 12), ("advenimiento", 13), ('"valle de lagrimas"', 16),
                       ("desterrados", 16), ('"trino en las personas"', 24), ("infalible", 28), ("catecismo", None)]},
        {"slug": "molinero-1695", "kind": "pdf", "path": PD / "molinero-1695-scan/A11302024.pdf",
         "pages": list(range(10, 15)), "modos": ["ocr", "capa"]},
        {"slug": "ordo-1812", "kind": "pdf", "path": PD / "ordo-divini-officii-1812-la-scan/ordo-1812.pdf",
         "pages": list(range(10, 15)), "modos": ["ocr", "capa"]},
        {"slug": "astete-1700-foto", "kind": "image", "path": PD / "astete-1700-page-photo/astete-1700.jpg",
         "pages": [1], "modos": ["ocr"], "gt": [PHOTO_GT], "gt_nota": "transcripción manual"},
        {"slug": "constitucion-1978", "kind": "pdf",
         "path": PD / "constitucion-1978-boe-digital/constitucion-1978.pdf", "pages": None, "modos": ["digital"],
         "mobiliario_fn": lambda n: ["BOLETÍN OFICIAL DEL ESTADO", "LEGISLACIÓN CONSOLIDADA", f"Página {n}"],
         "consultas": [('"reunion pacifica"', 7), ('"tribunales de honor"', 7), ("secuestro publicaciones", 6),
                       ('"setenta y dos horas"', 6), ("constitucion", None)]},
    ]
    for name, kind in (("sint-guiones.pdf", "pdf"), ("sint-dos-columnas.pdf", "pdf"),
                       ("sint-tipografia.pdf", "pdf"), ("sint-foto-movil.jpg", "image"), ("sint-libro.txt", "txt")):
        spec = json.loads((SYN / f"{name}.gt.json").read_text(encoding="utf-8"))
        items.append({"slug": Path(name).stem, "kind": kind, "path": SYN / name, "pages": None,
                      "modos": ["geometria"] if kind == "image" else ["digital"], "gt": spec["paginas"],
                      "mobiliario": spec["mobiliario"], "cortes": spec["cortes"], "spec": spec,
                      "consultas": [(c["q"], c["pagina"]) for c in spec["consultas"]]})
    return items


# --------------------------------------------------------------------------
# OCR cache + budget (public-domain only)
# --------------------------------------------------------------------------
CURRENT: dict = {}
LIVE_CALLS: dict[str, int] = {}
_real_pdf_file, _real_image_bytes = ocr.ocr_pdf_file, ocr.ocr_image_bytes


def _cached(key: str, call):
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / f"{key}.json"
    if target.exists():
        pages = json.loads(target.read_text(encoding="utf-8"))
        return ocr.OcrResult(paginas=[ocr.OcrPage(**p) for p in pages], modelo=pages[0]["modelo"] if pages else None)
    source = Path(CURRENT["path"]).resolve()
    if not source.is_relative_to(PD.resolve()):
        raise RuntimeError(f"OCR refused: {source.name} is not a public-domain fixture")
    budget_file = CACHE / "presupuesto.json"
    spent = json.loads(budget_file.read_text()) if budget_file.exists() else {}
    slug = CURRENT["slug"]
    if spent.get(slug, 0) >= BUDGET.get(slug, 0):
        raise RuntimeError(f"OCR budget exhausted for {slug}")
    for attempt in range(4):  # free-tier rate limit: 429s are rejected, not billed
        time.sleep(2 * 2 ** attempt if attempt else 1.5)
        try:
            result = call()
            break
        except RuntimeError as exc:
            if "429" not in str(exc) or attempt == 3:
                raise
    spent[slug] = spent.get(slug, 0) + 1
    LIVE_CALLS[slug] = LIVE_CALLS.get(slug, 0) + 1
    budget_file.write_text(json.dumps(spent))
    target.write_text(json.dumps([p.__dict__ for p in result.paginas], ensure_ascii=False), encoding="utf-8")
    return result


def _ocr_pdf_file(path):
    return _cached(CURRENT["key"], lambda: _real_pdf_file(path))


def _ocr_image_bytes(data: bytes, mime: str = "image/png"):
    key = f"{CURRENT['slug']}-img-{hashlib.sha256(data).hexdigest()[:16]}"
    return _cached(key, lambda: _real_image_bytes(data, mime))


ocr.ocr_pdf_file = _ocr_pdf_file
ocr.ocr_image_bytes = _ocr_image_bytes


# --------------------------------------------------------------------------
# Pipeline run
# --------------------------------------------------------------------------
ODL = {"llamadas": 0, "segundos": 0.0}
_real_structure = structure.extract_structure


def _timed_structure(*args, **kwargs):
    start = time.perf_counter()
    try:
        return _real_structure(*args, **kwargs)
    finally:
        ODL["llamadas"] += 1
        ODL["segundos"] += time.perf_counter() - start


structure.extract_structure = _timed_structure


def run_item(item: dict, modo: str, storage) -> dict:
    """Build the book through the job path; returns the assembled libro + timings."""
    _real_is_text = pdf_classify.is_text_based
    if modo == "ocr":
        pdf_classify.is_text_based = lambda info: False
    elif modo == "capa":
        pdf_classify.is_text_based = lambda info: True
    libro_id = f"eval-{item['slug']}" + ("" if modo in ("ocr", "digital") else f"-{modo}")
    kind = item["kind"]
    count = jobs._page_count(kind, item["path"])
    locals_ = [n - 1 for n in item["pages"]] if item["pages"] else list(range(count))
    ODL.update(llamadas=0, segundos=0.0)
    start = time.perf_counter()
    try:
        results = []
        for numero, local in enumerate(locals_, 1):
            CURRENT.update(slug=item["slug"], path=item["path"], key=f"{item['slug']}-p{local + 1}")
            results.append(jobs._extract_page(kind, item["path"], local, numero, libro_id, storage))
    finally:
        pdf_classify.is_text_based = _real_is_text
    seconds = time.perf_counter() - start
    pages = []
    for numero, result in enumerate(results, 1):
        page = result["pages"][0]
        page["numero"] = numero
        pages.append(page)
    fuentes = [r["fuente"] for r in results]
    libro = ingest._assemble_libro(
        libro_id=libro_id, metadatos=ingest._metadatos_from({"titulo": item.get("titulo", item["slug"].replace("-", " "))}),
        capitulos=[], pages=ingest._pages_from_extraction(pages, []),
        fuente="pdf_escaneado" if "pdf_escaneado" in fuentes else fuentes[0],
        motor=next((r["motor"] for r in results if r.get("motor")), None),
        modelo=next((r["modelo"] for r in results if r.get("modelo")), None),
        confianza_media=None, origen=[item["path"].name])
    return {"libro": libro, "segundos": seconds, "odl": dict(ODL), "paginas_pdf": [n + 1 for n in locals_]}


def skew_score(image, angle: float) -> float:
    rotated = image.rotate(angle, fillcolor=0)
    rows = list(rotated.resize((1, rotated.height), 4).get_flattened_data())  # BOX: row means
    return sum((a - b) ** 2 for a, b in zip(rows, rows[1:]))


def measure_geometry(data: bytes) -> dict:
    """Independent check of the image sent to OCR: residual skew and orientation."""
    from io import BytesIO

    from PIL import Image, ImageOps

    with Image.open(BytesIO(data)) as raw:
        gray = ImageOps.grayscale(raw)
    gray.thumbnail((700, 700))
    ink = gray.point(lambda v: 255 if v < 100 else 0)
    angles = [a / 4 for a in range(-60, 61)]
    best = max(angles, key=lambda a: skew_score(ink, a))
    turned = ink.transpose(Image.Transpose.ROTATE_90)
    upright = skew_score(ink, best) >= max(skew_score(turned, a) for a in angles[::4])
    return {"sesgo_residual": abs(best), "orientacion_ok": upright, "tamano": list(gray.size)}


def geometry_item(item: dict, storage) -> dict:
    """Run the image builder with OCR stubbed out; measure what OCR would receive."""
    captured: list[bytes] = []
    real = ingest.extract_from_images

    def capture(paths):
        captured.extend(Path(p).read_bytes() for p in paths)
        return ExtractionResult(fuente="imagenes", paginas=[PageExtraction(numero=1, texto="")])

    ingest.extract_from_images = capture
    real_guard = ingest._require_ocr_if_needed
    ingest._require_ocr_if_needed = lambda *, needs_ocr: None
    try:
        source = ingest._ImageSource(path=item["path"], data=item["path"].read_bytes(), suffix=item["path"].suffix.lower())
        ingest._extract_image_source([source], f"eval-{item['slug']}", [], storage)
    finally:
        ingest.extract_from_images = real
        ingest._require_ocr_if_needed = real_guard
    return measure_geometry(captured[0])


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------
def search_metrics(item: dict, libro_id: str) -> dict | None:
    from app.services.search import search_pages

    queries = item.get("consultas") or []
    if not queries:
        return None
    hits = rr = 0.0
    for query, page in queries:
        _, results = search_pages(query, limit=10)
        rank = next((i for i, r in enumerate(results, 1) if r.libro_id == libro_id
                     and (page is None or r.numero == item["_numero_de"](page))), None)
        hits += rank is not None
        rr += 1 / rank if rank else 0
    return {"recall": hits / len(queries), "mrr": rr / len(queries), "n": len(queries)}


COLUMNS = [("paginas", "Págs"), ("cer", "CER"), ("wer", "WER"), ("fuga", "Fuga cab./pie"),
           ("cortes_rotos", "Cortes rotos"), ("guiones_residuales_1k", "Guiones fin línea /1k"),
           ("recall", "Recall@10"), ("mrr", "MRR"), ("segundos", "Seg."), ("odl_segundos", "Seg. ODL"),
           ("sesgo_residual", "Sesgo residual °"), ("orientacion_ok", "Orientación OK")]


def _cell(row: dict, key: str) -> str:
    if "error" in row:
        return "—"
    value = row.get(key)
    if value is None:
        return "n/a"
    if key == "fuga":
        return f"{value}/{row['fuga_total']}"
    if key == "cortes_rotos":
        return f"{value}/{row['cortes_total']}"
    return str(value)


def table(data: dict, base: dict | None = None) -> str:
    lines = ["| Ítem | Modo | " + " | ".join(name for _, name in COLUMNS) + " |",
             "|---|---|" + "---:|" * len(COLUMNS)]
    before = {(r["item"], r["modo"]): r for r in (base or {}).get("filas", [])}
    for row in data["filas"]:
        cells = []
        for key, _ in COLUMNS:
            cell = _cell(row, key)
            old = before.get((row["item"], row["modo"]), {}).get(key)
            new = row.get(key)
            if base and isinstance(new, (int, float)) and isinstance(old, (int, float)) and not isinstance(new, bool) and new != old:
                cell += f" ({new - old:+.4g})"
            cells.append(cell)
        note = f" ⚠ {row['error'][:60]}" if "error" in row else ""
        lines.append(f"| {row['item']} | {row['modo']}{note} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--etiqueta", required=True)
    parser.add_argument("--solo", help="slug filter (comma separated)")
    args = parser.parse_args()

    settings = get_settings()
    host = settings.mongodb_uri.split("@")[-1].split("//")[-1].split(":")[0].split("/")[0]
    if settings.mongodb_db != "biblioteca_eval" or host not in ("localhost", "127.0.0.1"):
        raise SystemExit("Refusing: eval needs loopback Mongo and DB biblioteca_eval")
    from pymongo import MongoClient

    from app.db import ensure_indexes

    MongoClient(settings.mongodb_uri).drop_database("biblioteca_eval")
    ensure_indexes()
    storage = LocalStorage(settings.media_root)

    rows = []
    only = set(args.solo.split(",")) if args.solo else None
    for item in corpus():
        if only and item["slug"] not in only:
            continue
        for modo in item["modos"]:
            row = {"item": item["slug"], "modo": modo}
            if modo == "geometria":
                row.update(geometry_item(item, storage))
                rows.append(row)
                print(row, flush=True)
                continue
            try:
                run = run_item(item, modo, storage)
            except RuntimeError as exc:  # OCR quota/rate limit or budget: report, do not guess
                row["error"] = str(exc)[:160]
                rows.append(row)
                print(row, flush=True)
                continue
            libro = run["libro"]
            outputs = [p["texto"] for p in libro["paginas"]]
            pdf_pages = run["paginas_pdf"]
            item["_numero_de"] = (lambda n, pp=pdf_pages: pp.index(n) + 1 if item["pages"] else n)
            row.update(paginas=len(outputs), segundos=round(run["segundos"], 1),
                       odl_llamadas=run["odl"]["llamadas"], odl_segundos=round(run["odl"]["segundos"], 1),
                       guiones_residuales_1k=round(residual_hyphens(outputs), 2))
            if item.get("gt"):
                cer, wer = error_rates(outputs, item["gt"])
                row.update(cer=round(cer, 4), wer=round(wer, 4))
            furniture = item.get("mobiliario") or (
                [item["mobiliario_fn"](n) for n in pdf_pages] if item.get("mobiliario_fn") else None)
            if furniture and any(furniture):
                row["fuga"], row["fuga_total"] = leakage(outputs, furniture)
            if item.get("cortes"):
                row["cortes_rotos"], row["cortes_total"] = broken_splits(outputs, item["cortes"]), len(item["cortes"])
            ingest._persist(libro, storage)
            row["_libro_id"] = libro["libro_id"]
            rows.append(row)
            print(row, flush=True)

    # Search after every book is indexed, so ranking competes across the corpus.
    for item in corpus():
        if only and item["slug"] not in only or not item.get("consultas"):
            continue
        row = next((r for r in rows if r["item"] == item["slug"] and "_libro_id" in r), None)
        if row is None:
            continue
        pdf_pages = [n for n in (item["pages"] or [])]
        item["_numero_de"] = (lambda n, pp=pdf_pages: pp.index(n) + 1 if pp else n)
        metrics = search_metrics(item, row["_libro_id"])
        if metrics:
            row.update(recall=round(metrics["recall"], 3), mrr=round(metrics["mrr"], 3), consultas=metrics["n"])
            print(row["item"], row["modo"], "recall", row["recall"], "mrr", row["mrr"], flush=True)

    out = DOCS / "evaluacion" / f"{args.etiqueta}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"filas": rows, "ocr_llamadas_en_vivo": LIVE_CALLS}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("OCR live calls this run:", LIVE_CALLS)
    print("wrote", out.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
