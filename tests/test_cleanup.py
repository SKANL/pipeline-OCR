"""Book-level text cleanup: furniture removal and de-hyphenation, with position remap."""

from __future__ import annotations

from app.services.cleanup import clean_pages
from app.services.text import fold_text
from app.services.locator import match_ranges


def _pages(*texts: str) -> list[dict]:
    return [{"texto": t} for t in texts]


def test_removes_repeated_headers_footers_and_page_numbers() -> None:
    pages = _pages(*[f"TRATADO DE LA FE\ncuerpo {n} único\nCapítulo I\n{n + 10}" for n in range(4)])
    clean_pages(pages)
    assert [p["texto"].strip() for p in pages] == [f"cuerpo {n} único" for n in range(4)]


def test_keeps_lines_that_do_not_repeat_or_books_too_short() -> None:
    pages = _pages("Prólogo\nuno", "Capítulo\ndos", "Epílogo\ntres")
    clean_pages(pages)
    assert pages[0]["texto"] == "Prólogo\nuno"
    short = _pages("TITULO\na", "TITULO\nb")
    clean_pages(short)
    assert short[0]["texto"] == "TITULO\na"


def test_dehyphenates_line_end_breaks_but_keeps_compounds() -> None:
    pages = _pages("la conver-\nsión del alma y el estudio teórico-\npráctico", "otro teórico-práctico y Jesu-\nChristo")
    clean_pages(pages)
    assert pages[0]["texto"] == "la conversión del alma y el estudio teórico-\npráctico"
    assert pages[1]["texto"] == "otro teórico-práctico y Jesu-\nChristo"


def test_dehyphenation_uses_glyph_positions_when_pdfium_joined_the_line() -> None:
    # PDFium output "medita-ción": the hyphen glyph is on one line, "c" on the next.
    texto = "la medita-ción"
    posiciones = [[i, 0.1 + 0.02 * i, 0.1, 0.02, 0.03] for i in range(10)]
    posiciones += [[10, 0.1, 0.2, 0.02, 0.03], [11, 0.12, 0.2, 0.02, 0.03], [12, 0.14, 0.2, 0.02, 0.03], [13, 0.16, 0.2, 0.02, 0.03]]
    pages = [{"texto": texto, "posiciones": posiciones, "lectura": [{"inicio": 3, "fin": 14, "tipo": "prosa"}]}]
    clean_pages(pages)
    page = pages[0]
    assert page["texto"] == "la meditación"
    # The hyphen glyph is dropped and every later glyph shifts by one.
    assert [p[0] for p in page["posiciones"]] == list(range(9)) + list(range(9, 13))
    assert page["posiciones"][9][1:] == [0.1, 0.2, 0.02, 0.03]
    assert page["lectura"] == [{"inicio": 3, "fin": 13, "tipo": "prosa"}]
    # Highlights still land on real glyphs.
    (start, end), = match_ranges(page["texto"], "meditacion")[0]
    assert (start, end) == (3, 13)


def test_inline_hyphen_on_same_line_is_kept() -> None:
    texto = "Jesu-Christo"
    posiciones = [[i, 0.1 + 0.02 * i, 0.1, 0.02, 0.03] for i in range(len(texto))]
    pages = [{"texto": texto, "posiciones": posiciones}]
    clean_pages(pages)
    assert pages[0]["texto"] == texto and len(pages[0]["posiciones"]) == len(texto)


def test_header_removal_remaps_positions() -> None:
    pages = []
    for n in range(3):
        texto = f"CABECERA\nfe {n}"
        pages.append({"texto": texto, "posiciones": [[i, 0.0, 0.1 * (i > 8), 0.01, 0.01] for i in range(len(texto)) if texto[i] != "\n"]})
    clean_pages(pages)
    assert pages[0]["texto"] == "fe 0"
    assert [p[0] for p in pages[0]["posiciones"]] == [0, 1, 2, 3]


def test_fold_text_normalizes_quotes_and_soft_hyphens() -> None:
    assert fold_text("“Señor” l’Église «fe» con­ver") == "\"senor\" l'eglise \"fe\" conver"
    ranges, _ = match_ranges("dijo l’Église", "l'eglise")
    assert ranges == [(5, 13)]


def test_assemble_libro_cleans_and_recounts(monkeypatch) -> None:
    from app.services import ingest

    pages = ingest._pages_from_extraction(_pages(*[f"OBRA\n{w} conver-\nsión {w}\n{n}" for n, w in enumerate(["la", "una", "otra"])]), [])
    libro = ingest._assemble_libro(libro_id="x", metadatos=ingest._metadatos_from({"titulo": "x"}), capitulos=[],
                                   pages=pages, fuente="texto", motor=None, modelo=None,
                                   confianza_media=None, origen=[])
    assert libro["paginas"][0]["texto"].strip() == "la conversión la"
    assert libro["paginas"][0]["conteo_palabras"] == 3
    assert libro["conteo_palabras_total"] == 9


def test_cleanup_can_be_disabled(monkeypatch) -> None:
    from app.services import ingest

    monkeypatch.setattr(ingest, "get_settings", lambda: type("S", (), {"text_cleanup": False})())
    pages = ingest._pages_from_extraction(_pages(*["OBRA\nfe" for _ in range(3)]), [])
    libro = ingest._assemble_libro(libro_id="x", metadatos=ingest._metadatos_from({"titulo": "x"}), capitulos=[], pages=pages,
                                   fuente="texto", motor=None, modelo=None, confianza_media=None, origen=[])
    assert libro["paginas"][0]["texto"] == "OBRA\nfe"


def test_inline_hyphen_with_lower_glyph_box_is_kept() -> None:
    # A real hyphen box is short and mid-height; "p" has a descender: centres differ on one line.
    texto = "teórico-práctico"
    posiciones = [[i, 0.1 + 0.02 * i, 0.10, 0.02, 0.03] for i in range(len(texto))]
    posiciones[7] = [7, 0.24, 0.115, 0.015, 0.004]
    posiciones[8] = [8, 0.26, 0.105, 0.02, 0.04]
    pages = [{"texto": texto, "posiciones": posiciones}]
    clean_pages(pages)
    assert pages[0]["texto"] == texto
