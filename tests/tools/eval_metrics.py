"""Pure metrics for `evaluate_corpus` (no side effects, importable from tests)."""

from __future__ import annotations

import re
from pathlib import Path

from app.services.text import fold_text


# --------------------------------------------------------------------------
def _template(match: re.Match) -> str:
    _, *params = match.group(1).split("|")
    keep = [p for p in params if "=" not in p and not re.fullmatch(r"\s*[\d.]*\s*(px|em|%)?\s*", p)]
    return " ".join(keep)


def wikitext_to_text(raw: str) -> str:
    """Strip Wikisource markup: noinclude, files, tags, quotes; keep template text."""
    s = re.sub(r"<noinclude>.*?</noinclude>", "", raw, flags=re.S)
    s = re.sub(r"\[\[File:[^\]]*\]\]", "", s)
    s = re.sub(r"-<br\s*/?>", "", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</?[a-zA-Z]+[^>]*>", "", s)
    s = s.replace("'''", "").replace("''", "")
    previous = None
    while previous != s:
        previous, s = s, re.sub(r"\{\{([^{}]*)\}\}", _template, s)
    return re.sub(r"\{\{[^|{}]*\|?|\}\}", "", s).strip()


def wikisource_pages(path: Path) -> dict[int, dict]:
    """PDF page -> {"texto", "mobiliario"}; `{{CP|n}}` in noinclude is the printed page number."""
    out = {}
    for number, body in re.findall(r"=== PDF page (\d+) ===\n(.*?)(?=\n=== PDF page|\Z)", path.read_text(encoding="utf-8"), re.S):
        cp = re.search(r"<noinclude>[^<]*?(?:<pagequality[^>]*/>)?\{\{CP\|'*(\d+)'*\}\}", body)
        out[int(number)] = {"texto": wikitext_to_text(body), "mobiliario": [cp.group(1)] if cp else []}
    return out


def norm_words(text: str) -> list[str]:
    return re.findall(r"\w+", fold_text(text))


def levenshtein(a, b) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def error_rates(outputs: list[str], truths: list[str]) -> tuple[float, float]:
    """(CER, WER) summed over pages, on folded word streams."""
    chars = char_err = words = word_err = 0
    for out, gt in zip(outputs, truths):
        o, g = norm_words(out), norm_words(gt)
        char_err += levenshtein(" ".join(o), " ".join(g))
        chars += len(" ".join(g))
        word_err += levenshtein(o, g)
        words += len(g)
    return char_err / max(chars, 1), word_err / max(words, 1)


def leakage(outputs: list[str], furniture: list[list[str]]) -> tuple[int, int]:
    """Furniture strings (headers, footers, page numbers) found as a whole line."""
    leaked = total = 0
    for out, items in zip(outputs, furniture):
        lines = {" ".join(norm_words(line)) for line in out.splitlines()}
        for item in items:
            total += 1
            leaked += " ".join(norm_words(item)) in lines
    return leaked, total


def broken_splits(outputs: list[str], splits: list[dict]) -> int:
    """Wrong renderings of known line-break splits.

    Plain words: occurrences still hyphenated (`medita-ción`, `medita-\\nción`).
    Real compounds (`teórico-práctico`): occurrences wrongly joined.
    """
    text = fold_text("\n".join(outputs))
    count = 0
    for head, tail, correct in {(s["cabeza"], s["cola"], s["correcta"]) for s in splits}:
        head, tail, correct = fold_text(head).rstrip("-"), fold_text(tail), fold_text(correct)
        pattern = re.escape(head + tail) if "-" in correct else re.escape(head) + r"-\s*" + re.escape(tail)
        count += len(re.findall(r"(?<!\w)" + pattern + r"(?!\w)", text))
    return count


def residual_hyphens(outputs: list[str]) -> float:
    """Line-end hyphens between letters per 1000 words (GT-free)."""
    text = "\n".join(outputs)
    return 1000 * len(re.findall(r"\w-[ \t]*\n[ \t]*\w", text)) / max(len(text.split()), 1)


