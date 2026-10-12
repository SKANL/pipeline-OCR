"""Crea los índices de MongoDB (incluido el índice `$text` de búsqueda).

El índice de texto lo crea `ensure_indexes()` sobre `pages.texto_busqueda`,
con `default_language="spanish"`. No hace falta nada más para buscar.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import ensure_indexes  # noqa: E402


def main() -> None:
    try:
        names = ensure_indexes()
        print("Índices de MongoDB creados/verificados:")
        for name in names:
            print(f"  - {name}")
    except Exception as exc:  # noqa: BLE001
        print(f"No se pudo conectar a MongoDB para crear índices: {exc}")


if __name__ == "__main__":
    main()
