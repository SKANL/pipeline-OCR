"""Almacenamiento de originales, páginas y recortes por clave.

Dos backends: local bajo `MEDIA_ROOT` (por defecto, servido en `/media`) y
S3-compatible (Cloudflare R2 / SeaweedFS) cuando hay `S3_ENDPOINT_URL` y
`S3_BUCKET`. Claves: `{libro_id}/{original}`, `{libro_id}/paginas/{n}.png`,
`{libro_id}/figuras/{pagina}-{indice}.png`.
"""

from __future__ import annotations

import logging
import mimetypes
import re
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import get_settings

logger = logging.getLogger(__name__)

_URL_PREFIX = "/media"
_GET_EXPIRY = 3600  # ponytail: 1 h presigned GET; set S3_PUBLIC_BASE_URL to avoid expiry
_S3_CACHE = Path(tempfile.gettempdir()) / "pipeline_ocr_s3"


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
    """Contrato mínimo de almacenamiento por clave (`{libro_id}/...`).

    Mongo guarda CLAVES; las URLs se construyen al responder (`media_url`),
    así cambiar entre URL pública y firmada no exige re-ingestar.
    """

    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str) -> None:
        """Guarda `data` bajo `key`."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Devuelve los bytes guardados bajo `key`."""

    @abstractmethod
    def delete_prefix(self, prefix: str, keep: Iterable[str] = ()) -> None:
        """Borra toda clave bajo `prefix` salvo las de `keep`."""

    @abstractmethod
    def url(self, key: str) -> str:
        """Devuelve una URL legible por el cliente para `key`."""

    @abstractmethod
    def path(self, key: str) -> Path:
        """Devuelve una ruta local con el contenido de `key`."""

    @abstractmethod
    def size(self, key: str) -> int | None:
        """Tamaño en bytes de `key`, o `None` si no existe."""

    @abstractmethod
    def presign_put(self, key: str, content_type: str, expires: int = 900) -> str:
        """URL firmada para subir `key` directamente con PUT."""

    def save(self, libro_id: str, filename: str, data: bytes) -> str:
        """Guarda un original y devuelve su clave."""
        key = f"{libro_id}/{safe_filename(filename)}"
        self.put(key, data, mimetypes.guess_type(key)[0] or "application/octet-stream")
        return key

    def save_page_image(self, libro_id: str, numero: int, data: bytes) -> str:
        key = f"{libro_id}/paginas/{numero}.png"
        self.put(key, data, "image/png")
        return key

    def save_figure(self, libro_id: str, pagina: int, indice: int, data: bytes) -> str:
        key = f"{libro_id}/figuras/{pagina}-{indice}.png"
        self.put(key, data, "image/png")
        return key


class LocalStorage(Storage):
    """Almacenamiento local en `{root}/{key}`, servido por el mount `/media`."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self.path(key).read_bytes()

    def delete_prefix(self, prefix: str, keep: Iterable[str] = ()) -> None:
        base = self.path(prefix)
        if not base.is_dir():
            return
        keep_paths = {self.path(k) for k in keep}
        for file in base.rglob("*"):
            if file.is_file() and file not in keep_paths:
                file.unlink()

    def url(self, key: str) -> str:
        return f"{_URL_PREFIX}/{key.lstrip('/').replace(chr(92), '/')}"

    def size(self, key: str) -> int | None:
        path = self.path(key)
        return path.stat().st_size if path.is_file() else None

    def presign_put(self, key: str, content_type: str, expires: int = 900) -> str:
        raise NotImplementedError("Presigned uploads require the S3 backend (S3_ENDPOINT_URL).")

    def path(self, key: str) -> Path:
        """Devuelve la ruta absoluta, rechazando cualquier escape del root.

        Resuelve el root y el destino y exige que el destino quede contenido
        en el root; si no (p. ej. `../`), lanza `ValueError` para que los
        callers no puedan leer archivos fuera de `MEDIA_ROOT`.
        """
        root = self.root.resolve()
        target = (self.root / key).resolve()
        if target != root and not target.is_relative_to(root):
            raise ValueError(f"Ruta fuera de MEDIA_ROOT no permitida: {key}")
        return target


class S3Storage(Storage):
    """Almacenamiento S3-compatible (Cloudflare R2 en prod, SeaweedFS local)."""

    def __init__(self, *, endpoint_url: str | None, access_key_id: str,
                 secret_access_key: str, bucket: str, region: str = "auto",
                 public_base_url: str = "") -> None:
        self.bucket = bucket
        self.public_base_url = public_base_url
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete_prefix(self, prefix: str, keep: Iterable[str] = ()) -> None:
        keep = set(keep)
        pages = self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix
        )
        for page in pages:
            doomed = [{"Key": o["Key"]} for o in page.get("Contents", []) if o["Key"] not in keep]
            if doomed:
                result = self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": doomed})
                for error in result.get("Errors", []):
                    # ponytail: logged, not raised; a leftover object only wastes space.
                    logger.error("S3 delete failed for %s: %s %s", error.get("Key"),
                                 error.get("Code"), error.get("Message"))

    def url(self, key: str) -> str:
        if self.public_base_url:
            return f"{self.public_base_url.rstrip('/')}/{key}"
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=_GET_EXPIRY
        )

    def size(self, key: str) -> int | None:
        try:
            return self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"]
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    def presign_put(self, key: str, content_type: str, expires: int = 900) -> str:
        return self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires,
        )

    def path(self, key: str) -> Path:
        """Descarga `key` a un caché temporal (los extractores leen de disco)."""
        target = LocalStorage(_S3_CACHE).path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, key, str(target))
        return target


@lru_cache
def get_storage() -> Storage:
    """Devuelve el backend configurado: S3 si hay endpoint y bucket, si no local."""
    settings = get_settings()
    if settings.s3_endpoint_url and settings.s3_bucket:
        return S3Storage(
            endpoint_url=settings.s3_endpoint_url,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            bucket=settings.s3_bucket,
            region=settings.s3_region,
            public_base_url=settings.s3_public_base_url,
        )
    return LocalStorage(settings.media_root)


def media_url(value: str | None) -> str | None:
    """Convierte la clave guardada (o una ruta `/media/...` legada) en URL."""
    if not value:
        return value
    return get_storage().url(value.removeprefix(_URL_PREFIX + "/").lstrip("/"))
