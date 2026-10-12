"""Mide la cobertura de bloques sobre libros reales (proxy de "aparece la caja").

Ingesta `tests/fixtures/real-pdfs/` y, para cada página, calcula qué fracción de las
palabras de contenido del TEXTO aparecen en algún BLOQUE.

- cobertura = 1.0  -> toda palabra buscable es localizable en un bloque
                      (la caja aparece siempre).
- cobertura < 1.0  -> hay palabras del texto que no están en ningún bloque
                      (búsqueda encontrada ≠ caja localizable).

Uso: uv run python -m tests.tools.medir_cobertura_bbox
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.db import pages_collection
from app.services.ingest import ingest_root
from app.services.text import fold_text

ROOT = str(Path(__file__).resolve().parents[2] / "tests/fixtures/real-pdfs")


def content_words(texto: str) -> set[str]:
    """Palabras de contenido (>=4 chars) normalizadas como en la búsqueda."""
    return {fold_text(w) for w in re.findall(r"\w+", texto) if len(w) >= 4}


def main() -> int:
    summary = ingest_root(ROOT)
    print(
        "Ingesta:",
        {k: summary[k] for k in ("books", "pages", "errors", "fuentes")},
    )
    ids = set(summary["books_processed"])

    docs = list(pages_collection().find({"libro_id": {"$in": list(ids)}}))

    total_words = covered = 0
    tw_blk = cov_blk = tw_noblk = cov_noblk = 0
    con_imagen = con_bloques = 0
    figuras_total = paginas_con_figuras = 0
    lens: list[int] = []
    bloques_count: list[int] = []
    per_book: dict[str, list[int]] = {}

    for doc in docs:
        texto = doc.get("texto") or ""
        bloques = doc.get("bloques") or []
        words = content_words(texto)
        block_words: set[str] = set()
        for bloque in bloques:
            block_words |= content_words(str(bloque.get("texto", "")))

        total_words += len(words)
        covered += len(words & block_words)
        if bloques:
            con_bloques += 1
            tw_blk += len(words)
            cov_blk += len(words & block_words)
        else:
            tw_noblk += len(words)
            cov_noblk += len(words & block_words)
        lens.append(len(texto))
        bloques_count.append(len(bloques))
        if doc.get("imagen_url"):
            con_imagen += 1
        figuras = doc.get("figuras") or []
        figuras_total += len(figuras)
        if figuras:
            paginas_con_figuras += 1

        acc = per_book.setdefault(doc["libro_id"], [0, 0])
        acc[0] += len(words)
        acc[1] += len(words & block_words)

    coverage = covered / total_words if total_words else 0.0
    print(f"paginas={len(docs)} con_imagen={con_imagen} con_bloques={con_bloques}")
    print(f"figuras={figuras_total} paginas_con_figuras={paginas_con_figuras}")
    print(f"COBERTURA_GLOBAL={coverage:.3f} ({covered}/{total_words})")
    print(
        f"  en paginas CON bloques:   {cov_blk / tw_blk if tw_blk else 0:.3f} ({cov_blk}/{tw_blk})"
    )
    print(
        f"  en paginas SIN bloques:   {cov_noblk / tw_noblk if tw_noblk else 0:.3f} ({cov_noblk}/{tw_noblk})"
    )
    if lens:
        print(
            f"texto_promedio_chars={int(mean(lens))} "
            f"bloques_promedio={mean(bloques_count):.1f}"
        )
    for libro, (words, cov) in sorted(per_book.items()):
        print(f"  {libro}: cobertura={cov / words if words else 0:.3f} ({cov}/{words})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
