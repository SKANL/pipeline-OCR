"""Dependencias de seguridad para los endpoints de escritura.

La autenticación es deliberadamente mínima: una API key estática comparada
contra la cabecera `X-API-Key`. Si `settings.api_key` está vacía, la auth
queda desactivada para no romper el demo local ni los tests.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from app.config import get_settings


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Exige `X-API-Key` cuando `API_KEY` está configurada.

    - `API_KEY` vacía -> modo dev: se permite todo.
    - `API_KEY` definida -> la cabecera debe coincidir, si no responde 401.
    """
    expected = get_settings().api_key
    if not expected:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida o ausente (cabecera requerida: X-API-Key).",
        )
