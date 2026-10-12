"""Utilidades puras de nombres: slug y orden natural.

Viven aparte de la ingesta para que otros módulos (extracción, storage)
puedan usarlas sin crear dependencias circulares con `ingest.py`.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def slugify(value: str) -> str:
    """Convierte un texto en slug ascii en minúsculas con guiones."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_value = ascii_value.lower()
    ascii_value = re.sub(r"[^a-z0-9]+", "-", ascii_value)
    return ascii_value.strip("-")


def natural_key(value: str) -> list[Any]:
    """Clave de orden natural: separa dígitos y texto (`p2` < `p10`)."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]
