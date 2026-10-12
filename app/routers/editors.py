"""Editor identity (`/yo`) and admin management of the `editores` collection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.db import editors_collection
from app.ratelimit import limit_write
from app.security import bearer_email, require_admin, role_of

router = APIRouter(tags=["editores"])


class EditorRequest(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    rol: Literal["editor", "admin"] = "editor"


@router.get("/yo")
def me(request: Request) -> dict:
    """`{email, rol}` of the bearer token (`rol` is null for non-editors); 401 without one."""
    email = bearer_email(request)
    if not email:
        raise HTTPException(401, "Falta el token (Authorization: Bearer).", headers={"WWW-Authenticate": "Bearer"})
    return {"email": email, "rol": role_of(email)}


@router.get("/editores", dependencies=[Depends(limit_write), Depends(require_admin)])
def list_editors() -> list[dict]:
    return list(editors_collection().find({}, {"_id": 0}).sort("email", 1))


@router.post("/editores", status_code=201, dependencies=[Depends(limit_write), Depends(require_admin)])
def add_editor(payload: EditorRequest) -> dict:
    email = payload.email.strip().lower()
    editors_collection().update_one(
        {"email": email},
        {"$set": {"rol": payload.rol}, "$setOnInsert": {"creado": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return {"email": email, "rol": payload.rol}


@router.delete("/editores/{email}", status_code=204, dependencies=[Depends(limit_write), Depends(require_admin)])
def remove_editor(email: str) -> Response:
    editors_collection().delete_one({"email": email.strip().lower()})
    return Response(status_code=204)
