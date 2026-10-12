"""Utilidades de texto.

`fold_text` es la única fuente de verdad para normalizar texto de cara a la
búsqueda: minúsculas y sin diacríticos. Se usa tanto al indexar como al
consultar para lograr una búsqueda insensible a acentos.

`make_diacritic_insensitive_pattern` construye, a partir de un término, un
patrón de regex que matchea ignorando diacríticos (útil para `$regex` sobre
campos normalizados). `clean_markdown_text` limpia el Markdown que `pdf-inspector`
puede filtrar hacia el texto de la ruta `pdf_digital`.
"""

from __future__ import annotations

import re
import unicodedata


# Typographic quotes fold to ASCII; the soft hyphen disappears.
QUOTES = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'", "“": '"', "”": '"', "„": '"',
                        "‟": '"', "«": '"', "»": '"', "­": None})


def fold_text(value: str) -> str:
    """Devuelve `value` en minúsculas y sin diacríticos.

    Descompone con NFKD y elimina signos combinatorios: "Justificación" pasa
    a "justificacion" y las ligaduras tipográficas se expanden al indexar.
    Las comillas tipográficas pasan a ASCII y el guion blando se elimina.
    """
    decomposed = unicodedata.normalize("NFKD", value.translate(QUOTES))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


# Variantes de cada letra base: permiten matchear "lopez" contra "López".
_DIACRITIC_VARIANTS: dict[str, str] = {
    "a": "aáàâäãåā",
    "e": "eéèêëē",
    "i": "iíìîïī",
    "o": "oóòôöõō",
    "u": "uúùûüū",
    "n": "nñ",
    "c": "cçć",
    "s": "sśš",
    "y": "yýÿ",
    "z": "zźž",
}


def make_diacritic_insensitive_pattern(value: str) -> str:
    """Patrón regex que matchea `value` ignorando mayúsculas y diacríticos.

    Pensado para usarse con `$regex` + `$options: "i"` sobre campos
    normalizados: "lopez" matchea "López" y "LOPEZ".
    """
    parts: list[str] = []
    for char in fold_text(value):
        variants = _DIACRITIC_VARIANTS.get(char)
        parts.append(f"[{variants}]" if variants else re.escape(char))
    return "".join(parts)


_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+")
_BOLD_RE = re.compile(r"(\*\*|__)(.+?)\1")
_ITALIC_STAR_RE = re.compile(r"\*(?!\s)([^*\n]*?[^\s*])\*")
_ITALIC_UNDERSCORE_RE = re.compile(r"(?<![A-Za-z0-9_])_([^_\n]+?)_(?![A-Za-z0-9_])")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def clean_markdown_text(texto: str) -> str:
    """Limpia marcadores Markdown que `pdf-inspector` filtra al texto.

    Elimina encabezados (`# Titulo`), marcas de énfasis (`**`/`__`/`*`/`_`) y
    colapsa líneas en blanco excesivas. Conservador: no toca puntuación
    legítima, multiplicaciones (`2 * 3`) ni guiones bajos internos
    (`snake_case`).
    """
    if not texto:
        return texto
    limpio = _HEADING_RE.sub("", texto)
    limpio = _BOLD_RE.sub(r"\2", limpio)
    limpio = _ITALIC_STAR_RE.sub(r"\1", limpio)
    limpio = _ITALIC_UNDERSCORE_RE.sub(r"\1", limpio)
    limpio = _BLANK_LINES_RE.sub("\n\n", limpio)
    return limpio
