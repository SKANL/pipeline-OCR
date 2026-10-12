"""Acceso a MongoDB.

Expone un cliente singleton perezoso, los accesos a las colecciones `books`
y `pages`, y el helper `ensure_indexes()`.
"""

from __future__ import annotations

from pymongo import ASCENDING, TEXT, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from app.config import get_settings

_client: MongoClient | None = None


def get_client() -> MongoClient:
    """Devuelve el cliente de MongoDB (singleton perezoso)."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=3000)
    return _client


def get_db() -> Database:
    """Devuelve la base de datos configurada."""
    return get_client()[get_settings().mongodb_db]


def books_collection() -> Collection:
    """Colección `books`: documento de archivo/agregado."""
    return get_db()["books"]


def pages_collection() -> Collection:
    """Colección `pages`: proyección indexable para búsqueda."""
    return get_db()["pages"]


def ensure_indexes() -> list[str]:
    """Crea los índices requeridos y devuelve sus nombres.

    - `$text` sobre `pages.texto_busqueda` (texto plegado: sin acentos)
    - índice simple sobre `pages.libro_id`
    - único sobre `pages.ref`
    - único sobre `books.libro_id`

    Migra limpiamente: elimina el índice legado `tx_pages_texto` si existe.
    """
    books = books_collection()
    pages = pages_collection()

    # Migración: el índice de texto apuntaba a `texto` (sensible a acentos).
    try:
        if "tx_pages_texto" in pages.index_information():
            pages.drop_index("tx_pages_texto")
    except Exception:  # noqa: BLE001 - si ya no existe, no hay nada que hacer
        pass

    names: list[str] = []
    names.append(books.create_index("libro_id", unique=True, name="uq_books_libro_id"))
    names.append(pages.create_index("libro_id", name="ix_pages_libro_id"))
    names.append(pages.create_index("ref", unique=True, name="uq_pages_ref"))
    names.append(
        pages.create_index(
            [("texto_busqueda", TEXT)],
            name="tx_pages_texto_busqueda",
            default_language="spanish",
        )
    )
    return names
