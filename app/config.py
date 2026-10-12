"""Configuración de la aplicación.

Carga las variables de entorno con pydantic-settings desde el archivo `.env`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ajustes tipados leídos del entorno o del archivo `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "biblioteca"
    mistral_api_key: str = ""
    mistral_ocr_model: str = "mistral-ocr-latest"
    media_root: str = "./_media"
    # Almacenamiento S3-compatible (R2 / SeaweedFS); vacío => backend local MEDIA_ROOT
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_bucket: str = ""
    s3_public_base_url: str = ""  # vacío => URLs GET firmadas
    s3_region: str = "auto"
    max_upload_bytes: int = 104_857_600  # 100 MiB por petición / subida
    max_file_bytes: int = 52_428_800  # 50 MiB por archivo (subidas firmadas)
    worker_enabled: bool = True  # worker de la cola en el mismo proceso
    text_cleanup: bool = True  # quitar cabeceras/pies repetidos y guiones de fin de línea al armar el libro
    scan_preprocess: bool = True  # imágenes: EXIF, grises, contraste, enderezado y recorte antes del OCR
    page_image_dpi: int = 150  # resolución del render PDF -> PNG
    api_key: str = ""  # si está vacía, los endpoints de escritura no exigen auth (dev)
    auth_secret: str = ""  # HS256 secret shared with the PWA (bearer tokens); empty => no bearer auth
    admin_emails: str = ""  # bootstrap admins, comma separated (no DB row needed)
    trust_proxy_headers: bool = False  # trust X-Forwarded-For for rate limiting (true on Render)
    rate_limit_search_per_min: int = 120  # per client
    rate_limit_write_per_min: int = 20  # per client (uploads, edits, ingest)
    ingest_allowed_roots: str = ""  # absolute dirs for POST /ingest, comma separated; empty => disabled
    cors_origins: str = "http://localhost:3000,http://localhost:3010"  # orígenes permitidos, separados por coma


@lru_cache
def get_settings() -> Settings:
    """Devuelve una instancia cacheada de `Settings`."""
    return Settings()
