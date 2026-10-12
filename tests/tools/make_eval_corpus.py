"""Generate the 5 synthetic evaluation items with exact ground truth.

Deterministic: same code -> same text, layout and ground truth. Output goes to
`tests/fixtures/generated-pdfs/eval/` (gitignored); this file is the ground
truth spec. Synthetic files are NEVER sent to OCR.

Uso: uv run python -m tests.tools.make_eval_corpus
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests/fixtures/generated-pdfs/eval"

# `|` marks an allowed line-break point; a trailing `-` before `|` is a real compound.
SENTENCES = [
    "La conver|sión del alma comienza con la humil|dad y la oración constante.",
    "Quien persevera en la miseri|cordia alcanza la verdadera sabi|duría del corazón.",
    "El estudio teórico-|práctico de la doctrina ayuda a los fieles sencillos.",
    "Los mandamientos se guardan con obe|diencia y con amor a Dios y al prójimo.",
    "La caridad es paciente, es benigna, y no busca su propio prove|cho.",
    "Toda la vida espiri|tual se ordena a la unión con Dios por la gracia.",
    "Las obras de miseri|cordia corporales y espiri|tuales son catorce.",
    "El examen de concien|cia se hace cada noche antes del descanso.",
    "La espe|ranza sostiene al peregrino en medio de las tribula|ciones.",
    "Los santos padres enseñaron la medita|ción de las Escrituras.",
]
HEADER = "TRATADO DE LA VIDA ESPIRITUAL"
FOOTER = "Capítulo I. De la oración"


def wrap(words: list[str], width: int) -> list[tuple[str, bool]]:
    """Greedy wrap; returns (line, ends_with_split) and splits at `|` markers."""
    lines: list[tuple[str, bool]] = []
    line = ""
    for word in words:
        plain = word.replace("|", "")
        if not line or len(line) + 1 + len(plain) <= width:
            line = f"{line} {plain}".strip()
            continue
        if "|" in word:
            head, tail = word.split("|", 1)
            piece = head if head.endswith("-") else head + "-"
            if len(line) + 1 + len(piece) <= width:
                lines.append((f"{line} {piece}", True))
                line = tail
                continue
        lines.append((line, False))
        line = plain
    lines.append((line, False))
    return lines


def ground_truth(lines: list[tuple[str, bool]]) -> tuple[str, list[dict]]:
    """Page text with splits rejoined (compounds keep their hyphen) + split list."""
    out, splits = "", []
    for index, (line, split) in enumerate(lines):
        if split:
            head = line.rsplit(" ", 1)[-1]
            tail = lines[index + 1][0].split(" ", 1)[0]
            compound = _is_compound(head)
            joined = (head + tail) if compound else (head[:-1] + tail)
            splits.append({"cabeza": head, "cola": tail, "correcta": joined})
            out += line if compound else line[:-1]
        else:
            out += line + " "
    return out.strip(), splits


def _is_compound(head: str) -> bool:
    return any(f"{head}|" in s for s in SENTENCES)


def paragraph_words(seed: int, count: int) -> list[str]:
    rng = random.Random(seed)
    words: list[str] = []
    for _ in range(count):
        words += rng.choice(SENTENCES).split()
    return words


def make_hyphen_pdf(path: Path) -> dict:
    """(1) Digital PDF: hyphenated breaks + running header/footer + page numbers."""
    from reportlab.lib.pagesizes import A5
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A5, invariant=1)
    width, height = A5
    pages, furniture, splits = [], [], []
    words = paragraph_words(1, 60)
    lines = wrap(words, 48)
    start = 0
    while start < len(lines):
        chunk = lines[start:start + 24]
        if chunk[-1][1]:  # never end a page on a split line
            chunk = chunk[:-1]
        start += len(chunk)
        number = 11 + len(pages)
        c.setFont("Helvetica", 8)
        c.drawCentredString(width / 2, height - 30, HEADER)
        y = height - 60
        c.setFont("Helvetica", 10)
        for line, _ in chunk:
            c.drawString(40, y, line)
            y -= 13
        c.setFont("Helvetica", 8)
        c.drawCentredString(width / 2, 40, FOOTER)
        c.drawCentredString(width / 2, 28, str(number))
        c.showPage()
        text, page_splits = ground_truth(chunk)
        pages.append(text)
        splits += page_splits
        furniture.append([HEADER, FOOTER, str(number)])
    c.save()
    return {"paginas": pages, "mobiliario": furniture, "cortes": splits,
            "consultas": [{"q": "conversion", "pagina": 1}, {"q": "misericordia", "pagina": 1},
                          {"q": "\"examen de conciencia\"", "pagina": None}, {"q": "tribulaciones", "pagina": None}]}


def make_two_column_pdf(path: Path) -> dict:
    """(2) Two-column digital PDF (left column drawn first, as typesetters do)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    width, height = A4
    pages = []
    for page in range(3):
        texts = []
        for column in range(2):
            words = [w.replace("|", "") for w in paragraph_words(100 + page * 2 + column, 14)]
            lines = [line for line, _ in wrap(words, 38)][:45]
            x = 40 if column == 0 else width / 2 + 10
            y = height - 50
            c.setFont("Helvetica", 9)
            for line in lines:
                c.drawString(x, y, line)
                y -= 12
            texts.append(" ".join(lines))
        c.showPage()
        pages.append(" ".join(texts))
    c.save()
    return {"paginas": pages, "mobiliario": [[] for _ in pages], "cortes": [],
            "consultas": [{"q": "\"santos padres\"", "pagina": None}, {"q": "caridad paciente", "pagina": None}]}


TYPO_TEXT = [
    "El ﬁel cristiano dice: “Señor, ten misericordia”. Las ﬂores del campo y los ﬁeles "
    "del pueblo alaban a Dios. «La fe sin obras está muerta», enseña Santiago. "
    "El niño preguntó: ‘¿Qué es la gracia?’ y el maestro respondió con ﬁrmeza.",
    "La aﬂicción del justo es breve; la ﬁdelidad de Dios es eterna. Año tras año, "
    "la Iglesia canta: “Gloria in excelsis Deo”. «Bienaventurados los pobres de espíritu».",
]


def make_typography_pdf(path: Path) -> dict:
    """(3) Ligatures, curly quotes and accents with an embedded TTF (Vera ships with reportlab)."""
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.pagesizes import A5
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(TTFont("Vera", os.path.join(os.path.dirname(reportlab.__file__), "fonts", "Vera.ttf")))
    c = canvas.Canvas(str(path), pagesize=A5, invariant=1)
    width, height = A5
    for text in TYPO_TEXT:
        c.setFont("Vera", 10)
        y = height - 50
        for line, _ in wrap(text.split(), 50):
            c.drawString(40, y, line)
            y -= 14
        c.showPage()
    c.save()
    return {"paginas": TYPO_TEXT, "mobiliario": [[], []], "cortes": [],
            "consultas": [{"q": "fieles", "pagina": 1}, {"q": "aflicción", "pagina": 2},
                          {"q": "\"la fe sin obras\"", "pagina": 1}, {"q": "fidelidad", "pagina": 2}]}


def make_phone_photo(path: Path) -> dict:
    """(4) Simulated phone scan: 4° skew, noise, grey margins, EXIF orientation 6."""
    from PIL import Image, ImageDraw, ImageFont
    import reportlab

    font = ImageFont.truetype(os.path.join(os.path.dirname(reportlab.__file__), "fonts", "Vera.ttf"), 26)
    page = Image.new("L", (1100, 1500), 250)
    draw = ImageDraw.Draw(page)
    words = [w.replace("|", "") for w in paragraph_words(7, 12)]
    lines = [line for line, _ in wrap(words, 55)][:34]
    for index, line in enumerate(lines):
        draw.text((70, 80 + index * 40), line, fill=20, font=font)
    canvas = Image.new("L", (1400, 1800), 150)
    canvas.paste(page, (150, 150))
    skewed = canvas.rotate(4.0, resample=Image.BICUBIC, fillcolor=150)
    noise = Image.effect_noise(skewed.size, 18)
    noisy = Image.blend(skewed, noise, 0.15)
    stored = noisy.transpose(Image.Transpose.ROTATE_90)  # sensor orientation
    exif = Image.Exif()
    exif[0x0112] = 6  # display = rotate 90° clockwise
    stored.convert("RGB").save(path, "JPEG", quality=85, exif=exif.tobytes())
    return {"paginas": [" ".join(lines)], "angulo": 4.0, "exif_orientacion": 6, "mobiliario": [[]], "cortes": [],
            "consultas": []}


TXT_PAGES = [
    "Capítulo primero. De la fe. La fe es una virtud sobrenatural por la cual creemos "
    "firmemente lo que Dios ha revelado.",
    "Capítulo segundo. De la esperanza. Por la esperanza confiamos alcanzar la vida eterna "
    "y los medios para conseguirla.",
    "Capítulo tercero. De la caridad. La caridad nos mueve a amar a Dios sobre todas las cosas "
    "y al prójimo como a nosotros mismos.",
]


def make_text_book(path: Path) -> dict:
    """(5) Plain .txt book, pages separated by form feed (upload job format)."""
    path.write_text("\f".join(TXT_PAGES), encoding="utf-8")
    return {"paginas": TXT_PAGES, "mobiliario": [[], [], []], "cortes": [],
            "consultas": [{"q": "esperanza", "pagina": 2}, {"q": "\"vida eterna\"", "pagina": 2},
                          {"q": "projimo", "pagina": 3}]}


ITEMS = {
    "sint-guiones.pdf": make_hyphen_pdf,
    "sint-dos-columnas.pdf": make_two_column_pdf,
    "sint-tipografia.pdf": make_typography_pdf,
    "sint-foto-movil.jpg": make_phone_photo,
    "sint-libro.txt": make_text_book,
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in ITEMS.items():
        gt = build(OUT / name)
        (OUT / f"{name}.gt.json").write_text(json.dumps(gt, ensure_ascii=False, indent=1), encoding="utf-8")
        print(name, len(gt["paginas"]), "páginas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
