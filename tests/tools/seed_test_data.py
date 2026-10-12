"""Genera datos de prueba deterministas para la ingesta.

Crea `tests/fixtures/text-books/` con 3 libros falsos: cada uno con
`metadatos.json` + `paginas/001.txt..005.txt`. El texto es un latin
eclesiástico ficticio EN ESPAÑOL, con acentos y ñ, para probar UTF-8.
No contiene material con derechos de autor.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "tests/fixtures/text-books"

BOOKS = [
    {
        "carpeta": "Teologia_Sistematica_Vol_I",
        "metadatos": {
            "titulo": "Teología Sistemática, Volumen I",
            "autor": "Juan Pérez Ramírez",
            "autor_normalizado": "Pérez Ramírez, Juan",
            "editorial": "Editorial Sión",
            "anio_publicacion": 1998,
            "idioma": "es",
            "genero": "teologia",
            "temas": ["doctrina", "gracia", "salvación"],
            "descripcion": "Obra ficticia de prueba sobre teología sistemática.",
        },
        "capitulos": [
            {"numero": 1, "titulo": "La gracia soberana", "pagina_inicio": 1, "pagina_fin": 3},
            {"numero": 2, "titulo": "La fe del creyente", "pagina_inicio": 4, "pagina_fin": 5},
        ],
        "vocabulario": ["gracia", "justificación", "santificación", "redención", "pacto", "elección"],
    },
    {
        "carpeta": "Comentario_Evangelio_Juan",
        "metadatos": {
            "titulo": "Comentario al Evangelio de Juan",
            "autor": "María González",
            "autor_normalizado": "González, María",
            "editorial": "Casa Bautista",
            "anio_publicacion": 2005,
            "idioma": "es",
            "genero": "comentario",
            "temas": ["exégesis", "evangelio", "Espíritu"],
            "descripcion": "Comentario ficticio de prueba al cuarto evangelio.",
        },
        "capitulos": [
            {"numero": 1, "titulo": "El Verbo encarnado", "pagina_inicio": 1, "pagina_fin": 5},
        ],
        "vocabulario": ["Verbo", "encarnación", "discípulo", "Nicodemo", "samaritana", "milagro"],
    },
    {
        "carpeta": "Historia_Iglesia_Antigua",
        "metadatos": {
            "titulo": "Historia de la Iglesia Antigua",
            "autor": "Carlos Ramírez",
            "autor_normalizado": "Ramírez, Carlos",
            "editorial": "Ediciones Kairós",
            "anio_publicacion": 1987,
            "idioma": "es",
            "genero": "historia",
            "temas": ["patrística", "concilios", "mártires"],
            "descripcion": "Historia ficticia de prueba de la iglesia primitiva.",
        },
        "capitulos": [
            {"numero": 1, "titulo": "Los mártires", "pagina_inicio": 1, "pagina_fin": 2},
            {"numero": 2, "titulo": "Los concilios", "pagina_inicio": 3, "pagina_fin": 5},
        ],
        "vocabulario": ["mártir", "concilio", "Nicea", "obispo", "persecución", "catacumba"],
    },
]


def _page_text(book: dict, numero: int) -> str:
    titulo = book["metadatos"]["titulo"]
    vocabulario = book["vocabulario"]
    destacada = vocabulario[(numero - 1) % len(vocabulario)]
    enfasis = " ".join([destacada] * numero)
    temas = ", ".join(vocabulario)
    return (
        f"Página {numero} de «{titulo}». {enfasis}.\n\n"
        f"Temas de esta página: {temas}. "
        f"La {destacada} ocupa el centro de la reflexión número {numero} "
        f"y se cita a los maestros antiguos con paciencia.\n\n"
        f"Conclusión de la página {numero}: se profundiza en {destacada}.\n"
    )


def build_book(dir_path: Path, book: dict) -> None:
    pages_dir = dir_path / "paginas"
    pages_dir.mkdir(parents=True, exist_ok=True)

    metadatos = dict(book["metadatos"])
    metadatos["capitulos"] = book["capitulos"]
    (dir_path / "metadatos.json").write_text(
        json.dumps(metadatos, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    for numero in range(1, 6):
        (pages_dir / f"{numero:03d}.txt").write_text(
            _page_text(book, numero), encoding="utf-8"
        )


def main() -> None:
    if OUTPUT_DIR.exists() and any(OUTPUT_DIR.iterdir()):
        raise SystemExit("Refusing to overwrite existing text fixtures")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for book in BOOKS:
        build_book(OUTPUT_DIR / book["carpeta"], book)
    print(f"Datos de prueba creados en: {OUTPUT_DIR}")
    print(f"Libros: {len(BOOKS)} | Páginas por libro: 5")


if __name__ == "__main__":
    main()
