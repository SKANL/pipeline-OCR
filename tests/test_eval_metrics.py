"""Evaluation metrics and the Wikisource ground-truth normalizer."""

from tests.tools.eval_metrics import broken_splits, error_rates, leakage, levenshtein, wikitext_to_text


def test_levenshtein() -> None:
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein(["a", "b"], ["a", "c", "b"]) == 1


def test_wikitext_strips_markup_and_keeps_template_text() -> None:
    raw = ("<noinclude><pagequality level=\"3\" />{{CP|18}}</noinclude>{{Grandeinicial|T}}Odo "
           "{{sc|Fiel ''Christiano''|1em}} [[File:X.svg|20px]] Teo-<br>logía{{brecha}}")
    assert wikitext_to_text(raw) == "TOdo Fiel Christiano  Teología"


def test_error_rates_are_accent_and_punctuation_insensitive() -> None:
    assert error_rates(["La oración, señor."], ["la oracion senor"]) == (0.0, 0.0)
    cer, wer = error_rates(["la oracon"], ["la oracion"])
    assert wer == 0.5 and 0 < cer < 0.2


def test_leakage_and_broken_splits() -> None:
    assert leakage(["TITULO\ncuerpo\n12"], [["Título", "12", "Pie"]]) == (2, 3)
    split = [{"cabeza": "conver-", "cola": "sión", "correcta": "conversión"}]
    assert broken_splits(["la conver-\nsión y conver-sión"], split) == 2
    assert broken_splits(["la conversión"], split) == 0
    compound = [{"cabeza": "teórico-", "cola": "práctico", "correcta": "teórico-práctico"}]
    assert broken_splits(["estudio teórico-práctico"], compound) == 0
    assert broken_splits(["estudio teóricopráctico"], compound) == 1
