"""Configuración compartida de pytest.

Aísla los tests que usan MongoDB en una base de datos dedicada
(`biblioteca_test`) para no depender de la base de desarrollo `biblioteca`.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Debe fijarse ANTES de que `get_settings()` (cacheada) se instancie por
# primera vez. Las variables de entorno tienen prioridad sobre `.env`.
os.environ.setdefault("MONGODB_DB", "biblioteca_test")
os.environ.setdefault(
    "MEDIA_ROOT", str(Path(tempfile.gettempdir()) / "pipeline_ocr_test_media")
)

import pytest  # noqa: E402
from pymongo import MongoClient  # noqa: E402

TEST_DB = os.environ["MONGODB_DB"]


def _drop_test_database() -> None:
    """Elimina la base de datos de test (nunca la de desarrollo)."""
    from app.config import get_settings

    settings = get_settings()
    client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=3000)
    try:
        client.drop_database(settings.mongodb_db)
    except Exception:  # noqa: BLE001 - Mongo puede no estar accesible
        pass
    finally:
        client.close()


@pytest.fixture(scope="session", autouse=True)
def clean_test_database():
    """Limpia `biblioteca_test` al inicio y al final de la sesión."""
    _drop_test_database()
    yield
    _drop_test_database()
