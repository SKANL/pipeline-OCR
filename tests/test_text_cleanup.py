"""Tests de limpieza de Markdown y patrón de autor sin diacríticos (puros)."""

from __future__ import annotations

import re

from app.services.text import clean_markdown_text, make_diacritic_insensitive_pattern


def test_clean_strips_heading_markers() -> None:
    assert clean_markdown_text("# Titulo") == "Titulo"
    assert clean_markdown_text("### Sub titulo") == "Sub titulo"
    assert clean_markdown_text("##Titulo sin espacio") == "##Titulo sin espacio"


def test_clean_strips_bold_and_italic() -> None:
    assert clean_markdown_text("Texto **negrita** y *cursiva*.") == "Texto negrita y cursiva."
    assert clean_markdown_text("__fuerte__ y _enfasis_.") == "fuerte y enfasis."


def test_clean_preserves_snake_case_and_math() -> None:
    assert clean_markdown_text("mi_variable y otra_cosa") == "mi_variable y otra_cosa"
    assert clean_markdown_text("2 * 3 * 4 = 24") == "2 * 3 * 4 = 24"


def test_clean_collapses_blank_lines() -> None:
    assert clean_markdown_text("uno\n\n\n\ndos") == "uno\n\ndos"


def test_clean_handles_combined_markers() -> None:
    texto = "# Titulo\n\nUn parrafo con **gracia** y *fe*.\n\n\n\nFin."
    assert clean_markdown_text(texto) == "Titulo\n\nUn parrafo con gracia y fe.\n\nFin."


def test_clean_empty_and_none_like() -> None:
    assert clean_markdown_text("") == ""


def test_diacritic_pattern_matches_variants() -> None:
    pattern = make_diacritic_insensitive_pattern("lopez")
    assert re.search(pattern, "López", re.IGNORECASE)
    assert re.search(pattern, "LOPEZ", re.IGNORECASE)
    assert re.search(pattern, "López, Ana", re.IGNORECASE)
    assert not re.search(pattern, "Garcia", re.IGNORECASE)


def test_diacritic_pattern_escapes_regex_specials() -> None:
    pattern = make_diacritic_insensitive_pattern("a.b")
    assert re.search(pattern, "a.b", re.IGNORECASE)
    assert not re.search(pattern, "aXb", re.IGNORECASE)
