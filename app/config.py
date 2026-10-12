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
    max_upload_bytes: int = 104_857_600  # 100 MiB por petición
    page_image_dpi: int = 150  # resolución del render PDF -> PNG
    api_key: str = ""  # si está vacía, los endpoints de escritura no exigen auth (dev)
    cors_origins: str = "http://localhost:3000,http://localhost:3010"  # orígenes permitidos, separados por coma


@lru_cache
def get_settings() -> Settings:
    """Devuelve una instancia cacheada de `Settings`."""
    return Settings()
