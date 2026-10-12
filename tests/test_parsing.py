"""Tests de utilidades puras: slug, orden natural y contadores."""

from __future__ import annotations

from app.services.ingest import count_chars, count_words, natural_key, slugify


def test_slugify_basic() -> None:
    assert slugify("Teología Sistemática, Vol. I") == "teologia-sistematica-vol-i"


def test_slugify_accents_and_symbols() -> None:
    assert slugify("  Ñandú & Cañón  ") == "nandu-canon"


def test_natural_key_orders_numbers_numerically() -> None:
    names = ["pagina10.txt", "pagina2.txt", "pagina1.txt"]
    assert sorted(names, key=natural_key) == ["pagina1.txt", "pagina2.txt", "pagina10.txt"]


def test_count_words_and_chars_with_accents() -> None:
    texto = "Señor, gracia y añoranza"
    assert count_words(texto) == 4
    assert count_chars(texto) == len(texto)
