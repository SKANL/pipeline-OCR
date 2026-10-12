"""Ensayo local end-to-end contra MongoDB (local o Atlas).

Indexa, ingesta a traves de la API real y prueba health, busqueda y cita.
Uso:
    uv run python -m tests.tools.smoke_local
"""

from __future__ import annotations

import sys
from pathlib import Path

# Permite ejecutar el script directamente: agrega la raiz del repo al path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import ensure_indexes  # noqa: E402
from app.main import app  # noqa: E402

API = "/api/v1"
ROOT = str(Path(__file__).resolve().parents[2] / "tests/fixtures/text-books")


def main() -> int:
    print("Indices:", ensure_indexes())

    client = TestClient(app)
    print("Health:", client.get("/health").json())

    ing = client.post(f"{API}/ingest", json={"root": ROOT}).json()
    print("Ingesta:", ing)

    # Segundo termino sin tilde: prueba insensibilidad a diacriticos.
    for query in ("gracia", "justificacion"):
        resp = client.get(f"{API}/search", params={"q": query, "limit": 3}).json()
        print(f"\n=== Busqueda '{query}' -> total={resp['total']} ===")
        for hit in resp["resultados"]:
            score = hit["score"]
            score_txt = f"{score:.2f}" if isinstance(score, (int, float)) else str(score)
            print(f"  - ref={hit['ref']!r} score={score_txt} titulo={hit['titulo']!r}")
            print(f"    snippet={hit['snippet'][:120]!r}")

    ref = "teologia-sistematica-vol-i/pagina/1"
    print("\nCite apa:", client.get(f"{API}/cite/{ref}", params={"estilo": "apa"}).json())
    page = client.get(f"{API}/ref/{ref}").json()
    print("Ref navegacion: siguiente =", page.get("ref_siguiente"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
