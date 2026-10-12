"""Publica las extracciones locales medidas, con respaldo y sin borrar archivos."""
from datetime import datetime, timezone
import json
from urllib.parse import urlsplit

from bson import json_util

from app.config import get_settings
from app.db import books_collection, pages_collection
from app.services.ingest import build_page_projection
from app.services.locator import extract_positioned_pdf
from tests.tools.phase2_evidence import ROOT, QUERIES


def main():
    settings = get_settings()
    parsed = urlsplit(settings.mongodb_uri)
    if parsed.scheme != "mongodb" or parsed.hostname not in ("localhost", "127.0.0.1", "::1") or "," in parsed.netloc:
        raise SystemExit("Solo se permite MongoDB local de una instancia")
    dest = ROOT / "_media/phase2-evidence"
    backup_path = dest / "db-before.json"
    if backup_path.exists() or (dest / "db-after.json").exists():
        raise SystemExit("No se sobrescribe el respaldo existente")
    books = [json.loads((dest / "after-final" / f"{name}.json").read_text(encoding="utf-8")) for name in QUERIES]
    for book in books:
        native = extract_positioned_pdf(ROOT / "tests/fixtures/real-pdfs" / book["libro_id"] / "paper.pdf")
        for measured, current in zip(book["paginas"], native, strict=True):
            if any(measured.get(key) != current.get(key) for key in ("texto", "posiciones", "motor", "advertencia_localizacion")):
                raise SystemExit("La extracción medida no coincide con el código actual; no se escribe")
        old = books_collection().find_one({"libro_id": book["libro_id"]})
        if not old or book["conteo_paginas"] != old["conteo_paginas"]:
            raise SystemExit("Libro ausente o número de páginas distinto; no se escribe")
        book["creado_en"] = old.get("creado_en")
        book["actualizado_en"] = datetime.now(timezone.utc)
        book["estado_ingesta"] = "indexed"
        for page in book["paginas"]:
            for resource in [page, *page.get("figuras", [])]:
                if resource.get("imagen_url"):
                    resource["imagen_url"] = resource["imagen_url"].replace("/media/", "/media/phase2-evidence/after-final/", 1)
    backup = {"books": list(books_collection().find({"libro_id": {"$in": list(QUERIES)}})),
              "pages": list(pages_collection().find({"libro_id": {"$in": list(QUERIES)}}))}
    backup_path.write_text(json_util.dumps(backup), encoding="utf-8")
    for book in books:
        books_collection().update_one({"libro_id": book["libro_id"]}, {"$set": book})
        for page in book["paginas"]:
            projection = build_page_projection(book["libro_id"], page, book["metadatos"])
            pages_collection().update_one({"ref": page["ref"]}, {"$set": projection})
        print(book["libro_id"], book["conteo_paginas"], "páginas locales actualizadas; sin borrado, OCR ni nueva conversión")
    (dest / "db-after.json").write_text(json_util.dumps(books), encoding="utf-8")


if __name__ == "__main__":
    main()
