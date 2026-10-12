"""Write-endpoint security: editor bearer tokens (PWA) or `X-API-Key` (ops).

Token contract (minted server-side by the PWA, never in the browser):
HS256 signed with `AUTH_SECRET`; claims `sub`=`email`, `iat`, `exp` (lifetime
<= 10 min), `iss`="biblioteca-web", `aud`="biblioteca-api". Sent as
`Authorization: Bearer <jwt>`.

Roles: bootstrap admins from `ADMIN_EMAILS` (no DB row needed), otherwise the
`editores` collection `{email, rol: "editor"|"admin", creado}`.

Dev mode: with neither `API_KEY` nor `AUTH_SECRET`, writes stay open
(`main.lifespan` logs a warning).
"""

from __future__ import annotations

import hmac

import jwt
from fastapi import Depends, Header, HTTPException, Request, status

from app.config import get_settings
from app.db import editors_collection

ISSUER = "biblioteca-web"
AUDIENCE = "biblioteca-api"
MAX_TOKEN_LIFETIME = 600  # seconds
LEEWAY = 30  # seconds of clock skew


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def bearer_email(request: Request) -> str | None:
    """Verified, lower-cased email of the bearer token; `None` without a bearer.

    Raises 401 when a bearer is present but invalid (or auth is not configured).
    """
    header = request.headers.get("authorization", "")
    scheme, _, raw = header.partition(" ")
    if scheme.lower() != "bearer" or not raw.strip():
        return None
    secret = get_settings().auth_secret
    if not secret:
        raise _unauthorized("Autenticación por token no configurada (AUTH_SECRET).")
    try:
        claims = jwt.decode(
            raw.strip(), secret, algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER, leeway=LEEWAY,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise _unauthorized("Token inválido o vencido.") from exc
    if claims["exp"] - claims["iat"] > MAX_TOKEN_LIFETIME:
        raise _unauthorized("Token con vigencia mayor a la permitida.")
    email = str(claims.get("email") or claims["sub"]).strip().lower()
    if not email:
        raise _unauthorized("Token sin email.")
    return email


def role_of(email: str) -> str | None:
    """`admin` for ADMIN_EMAILS, else the `editores` row's rol, else `None`."""
    admins = {e.strip().lower() for e in get_settings().admin_emails.split(",") if e.strip()}
    if email in admins:
        return "admin"
    row = editors_collection().find_one({"email": email}, {"rol": 1})
    return row["rol"] if row else None


def require_editor(request: Request, x_api_key: str | None = Header(default=None)) -> dict:
    """Editor/admin bearer, or a valid ops `X-API-Key`, or open dev mode.

    Returns `{email, rol}`; `email` is `None` for the API key and dev mode.
    """
    settings = get_settings()
    email = bearer_email(request)
    if email:
        rol = role_of(email)
        if rol not in ("editor", "admin"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu cuenta no tiene permisos de editor.")
        return {"email": email, "rol": rol}
    if settings.api_key and x_api_key and hmac.compare_digest(x_api_key.encode(), settings.api_key.encode()):
        return {"email": None, "rol": "admin"}
    if not settings.api_key and not settings.auth_secret:
        return {"email": None, "rol": "admin"}  # dev mode
    raise _unauthorized("Credenciales ausentes o inválidas (Authorization: Bearer o cabecera X-API-Key).")


def require_admin(principal: dict = Depends(require_editor)) -> dict:
    if principal["rol"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Se requiere rol admin.")
    return principal
