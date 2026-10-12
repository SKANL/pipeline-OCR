"""Tests de citación en los 3 estilos."""

from __future__ import annotations

import pytest

from app.services.citation import build_citation

METADATOS = {
    "titulo": "Teología Sistemática",
    "autor": "Juan Pérez",
    "autor_normalizado": "Pérez, Juan",
    "editorial": "Editorial Sión",
    "anio_publicacion": 1998,
}


def test_apa_style() -> None:
    result = build_citation("teologia", METADATOS, 12, estilo="apa")
    assert result["ref"] == "teologia/pagina/12"
    assert result["estilo"] == "apa"
    assert result["cita"].startswith("Pérez, Juan. (1998).")
    assert "Teología Sistemática." in result["cita"]
    assert result["cita"].endswith("p. 12.")


def test_chicago_style() -> None:
    result = build_citation("teologia", METADATOS, 12, estilo="chicago")
    assert result["estilo"] == "chicago"
    assert "Juan Pérez." in result["cita"]
    assert "Editorial Sión, 1998, 12." in result["cita"]


def test_mla_style() -> None:
    result = build_citation("teologia", METADATOS, 12, estilo="mla")
    assert result["estilo"] == "mla"
    assert result["cita"].startswith("Pérez, Juan.")
    assert "Editorial Sión, 1998, p. 12." in result["cita"]


def test_missing_year_becomes_sf() -> None:
    meta = {"titulo": "Obra anónima", "autor_normalizado": "Anónimo"}
    result = build_citation("x", meta, 1, estilo="apa")
    assert "(s.f.)" in result["cita"]


def test_unsupported_style_raises() -> None:
    with pytest.raises(ValueError):
        build_citation("x", METADATOS, 1, estilo="harvard")
