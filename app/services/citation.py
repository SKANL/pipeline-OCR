"""Construcción de citas bibliográficas.

Estilos soportados: `apa` (por defecto), `chicago`, `mla`.
"""

from __future__ import annotations

SUPPORTED_STYLES = ("apa", "chicago", "mla")


def _titulo(metadatos: dict) -> str:
    return metadatos.get("titulo") or "Título desconocido"


def _autor_apa(metadatos: dict) -> str:
    return metadatos.get("autor_normalizado") or metadatos.get("autor") or "Autor desconocido"


def _autor_natural(metadatos: dict) -> str:
    return metadatos.get("autor") or _autor_apa(metadatos)


def _anio(metadatos: dict) -> str:
    anio = metadatos.get("anio_publicacion")
    return str(anio) if anio else "s.f."


def build_citation(
    libro_id: str,
    metadatos: dict,
    numero: int,
    estilo: str = "apa",
) -> dict:
    """Devuelve `{ cita, ref, estilo }` para una página."""
    estilo = (estilo or "apa").lower()
    if estilo not in SUPPORTED_STYLES:
        raise ValueError(f"Estilo de cita no soportado: {estilo}")

    metadatos = metadatos or {}
    titulo = _titulo(metadatos)
    autor_apa = _autor_apa(metadatos)
    autor_natural = _autor_natural(metadatos)
    anio = _anio(metadatos)
    editorial = metadatos.get("editorial")
    ref = f"{libro_id}/pagina/{numero}"

    if estilo == "apa":
        parts = [f"{autor_apa}. ({anio}). {titulo}."]
        if editorial:
            parts.append(f"{editorial}.")
        parts.append(f"p. {numero}.")
        cita = " ".join(parts)
    elif estilo == "chicago":
        parts = [f"{autor_natural}. {titulo}."]
        tail = [value for value in (editorial, anio) if value]
        parts.append(", ".join(tail) + f", {numero}.")
        cita = " ".join(parts)
    else:  # mla
        parts = [f"{autor_apa}. {titulo}."]
        tail = [value for value in (editorial, anio) if value]
        parts.append(", ".join(tail) + f", p. {numero}.")
        cita = " ".join(parts)

    return {"cita": cita, "ref": ref, "estilo": estilo}
