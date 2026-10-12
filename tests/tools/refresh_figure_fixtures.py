"""Refresh only the three local digital fixtures, without OCR or deletion.

Preserves the prior database documents in ignored local evidence and writes
new media in a separate namespace. Refuses non-loopback MongoDB servers.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

os.environ["MISTRAL_API_KEY"] = ""

from bson import json_util

from app.config import get_settings
from app.db import books_collection, get_client, pages_collection
from app.services import ingest, pdf_classify
from app.services.storage import LocalStorage

ROOT = Path(__file__).resolve().parents[2]
NAMES = ("attention", "bert", "resnet")


class EvidenceStorage(LocalStorage):
    def url(self, relative_path: str) -> str:
        return "/media/figure-evidence/refreshed/" + relative_path


def main() -> None:
    # Access configuration normally; never log connection strings/credentials.
    parsed = urlsplit(get_settings().mongodb_uri)
    if parsed.scheme != "mongodb" or parsed.hostname not in ("localhost", "127.0.0.1", "::1") or "," in parsed.netloc:
        raise SystemExit("Fixture refresh requires single-instance loopback MongoDB")
    if get_client().address[0] not in ("localhost", "127.0.0.1", "::1"):
        raise SystemExit("Fixture refresh requires loopback MongoDB")
    dest = ROOT / "_media/figure-evidence/refreshed"
    if dest.exists():
        raise SystemExit("Refusing to overwrite fixture-refresh evidence")
    for name in NAMES:
        if not pdf_classify.is_text_based(pdf_classify.classify_pdf_file(ROOT / "tests/fixtures/real-pdfs" / name / "paper.pdf")):
            raise SystemExit("Refusing non-digital fixture; OCR is prohibited")
        if not books_collection().find_one({"libro_id": name}):
            raise SystemExit(f"Missing existing fixture book: {name}")
    dest.mkdir(parents=True)
    backup = {"books": list(books_collection().find({"libro_id": {"$in": list(NAMES)}})),
              "pages": list(pages_collection().find({"libro_id": {"$in": list(NAMES)}}))}
    (dest / "db-before.json").write_text(json_util.dumps(backup, indent=2), encoding="utf-8")
    storage = EvidenceStorage(dest)
    # Even an unexpected classification change cannot invoke an OCR client.
    with patch.object(ingest.ocr_service, "ocr_pdf_file", side_effect=AssertionError("Live OCR prohibited")):
        books = [ingest.build_book_dir(ROOT / "tests/fixtures/real-pdfs" / name, libro_id=name, storage=storage) for name in NAMES]
    for book in books:
        old = books_collection().find_one({"libro_id": book["libro_id"]})
        if book["conteo_paginas"] != old["conteo_paginas"]:
            raise SystemExit("Page count changed; refresh aborted without database writes")
    for book in books:
        book["estado_ingesta"] = "indexed"
        book["actualizado_en"] = datetime.now(timezone.utc)
        book["creado_en"] = books_collection().find_one({"libro_id": book["libro_id"]}).get("creado_en")
        books_collection().update_one({"libro_id": book["libro_id"]}, {"$set": book})
        for page in book["paginas"]:
            projection = ingest.build_page_projection(book["libro_id"], page, book["metadatos"])
            pages_collection().update_one({"ref": page["ref"]}, {"$set": projection})
        print(f"Refreshed {book['libro_id']}: {book['conteo_paginas']} pages; no deletion or OCR")
    (dest / "db-after.json").write_text(json_util.dumps(books, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
