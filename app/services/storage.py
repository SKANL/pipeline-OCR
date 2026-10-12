"""Abstracción de almacenamiento de archivos originales.

Implementación por defecto en sistema de archivos local bajo `MEDIA_ROOT`,
organizada como `{MEDIA_ROOT}/{libro_id}/{filename}`. La interfaz es
intercambiable para migrar a objetos (Cloudflare R2 / Backblaze B2) sin
tocar la ingesta.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path

from app.config import get_settings

_URL_PREFIX = "/media"


def safe_filename(name: str) -> str:
    """Normaliza un nombre de archivo para usarlo en disco.

    Elimina separadores de ruta y caracteres problemáticos, pero conserva
    letras (incluidas acentuadas), dígitos, punto, guion y guion bajo.
    """
    name = name.replace("\\", "/").split("/")[-1].strip()
    name = re.sub(r"[^\w.\- ]+", "_", name, flags=re.UNICODE)
    name = re.sub(r"\s+", "_", name).strip("._")
    return name or "archivo"


class Storage(ABC):
    """Contrato mínimo de almacenamiento de originales."""

    @abstractmethod
    def save(self, libro_id: str, filename: str, data: bytes) -> str:
        """Guarda `data` y devuelve la ruta relativa almacenada."""

    @abstractmethod
    def save_page_image(self, libro_id: str, numero: int, data: bytes) -> str:
        """Guarda la imagen PNG de una página y devuelve su ruta relativa."""

    @abstractmethod
    def save_figure(self, libro_id: str, pagina: int, indice: int, data: bytes) -> str:
        """Guarda el recorte PNG de una figura y devuelve su ruta relativa."""

    @abstractmethod
    def url(self, relative_path: str) -> str:
        """Devuelve la URL pública de un recurso almacenado."""

    @abstractmethod
    def delete(self, relative_path: str) -> None:
        """Elimina un recurso almacenado (no falla si no existe)."""

    @abstractmethod
    def path(self, relative_path: str) -> Path:
        """Devuelve la ruta absoluta en disco de un recurso."""


class LocalStorage(Storage):
    """Almacenamiento local en `{root}/{libro_id}/{filename}`."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def save(self, libro_id: str, filename: str, data: bytes) -> str:
        relative = f"{libro_id}/{safe_filename(filename)}"
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return relative.replace("\\", "/")

    def save_page_image(self, libro_id: str, numero: int, data: bytes) -> str:
        relative = f"{libro_id}/paginas/{numero}.png"
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return relative

    def save_figure(self, libro_id: str, pagina: int, indice: int, data: bytes) -> str:
        relative = f"{libro_id}/figuras/{pagina}-{indice}.png"
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return relative

    def url(self, relative_path: str) -> str:
        return f"{_URL_PREFIX}/{relative_path.lstrip('/').replace(chr(92), '/')}"

    def delete(self, relative_path: str) -> None:
        """Elimina el archivo. Respeta la misma guarda anti-escape que `path`."""
        self.path(relative_path).unlink(missing_ok=True)

    def path(self, relative_path: str) -> Path:
        """Devuelve la ruta absoluta, rechazando cualquier escape del root.

        Resuelve el root y el destino y exige que el destino quede contenido
        en el root; si no (p. ej. `../`), lanza `ValueError` para que los
        callers no puedan leer archivos fuera de `MEDIA_ROOT`.
        """
        root = self.root.resolve()
        target = (self.root / relative_path).resolve()
        if target != root and not target.is_relative_to(root):
            raise ValueError(f"Ruta fuera de MEDIA_ROOT no permitida: {relative_path}")
        return target


def get_storage() -> Storage:
    """Devuelve el backend de almacenamiento configurado."""
    return LocalStorage(get_settings().media_root)
