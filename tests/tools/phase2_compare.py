"""Compara snapshots locales ya extraídos; no vuelve a ejecutar conversores."""
from collections import Counter
from difflib import SequenceMatcher
import json
import re

from app.services.locator import folded_with_offsets, locate_matches
from tests.tools.phase2_evidence import QUERIES, ROOT


def main():
    result = {}
    for name, queries in QUERIES.items():
        books = {stage: json.loads((ROOT / "_media/phase2-evidence" / ("after-final" if stage == "after" else stage) / f"{name}.json").read_text(encoding="utf-8")) for stage in ("before", "after")}
        reports = {stage: json.loads((ROOT / "_media/phase2-evidence" / ("after-final" if stage == "after" else stage) / "report.json").read_text(encoding="utf-8"))[name] for stage in books}
        assert reports["before"]["sha256"] == reports["after"]["sha256"]
        probes = []
        totals = {stage: Counter() for stage in books}
        for page_number, query in queries:
            probe = {"pagina": page_number, "q": query}
            for stage, book in books.items():
                page = book["paginas"][page_number - 1]
                matches, truncated = locate_matches(page, query)
                counts = Counter(match["precision"] for match in matches)
                totals[stage].update(counts)
                probe[stage] = {"conteos": dict(counts), "sin_coincidencia_textual": not matches, "truncadas": truncated,
                                "fragmentos": [page["texto"][match["inicio"]:match["fin"]] for match in matches]}
            probes.append(probe)
        diagnostics = []
        for old, new in zip(books["before"]["paginas"], books["after"]["paginas"]):
            tokens = [re.findall(r"\w+", folded_with_offsets(page["texto"])[0]) for page in (old, new)]
            old_counts, new_counts = map(Counter, tokens)
            missing = old_counts - new_counts
            added = new_counts - old_counts
            diagnostics.append({"pagina": old["numero"], "caracteres_antes": len(old["texto"]), "caracteres_despues": len(new["texto"]),
                                "tokens_antes": len(tokens[0]), "tokens_despues": len(tokens[1]), "tokens_ausentes": sum(missing.values()), "tokens_agregados": sum(added.values()),
                                "ejemplos_ausentes": missing.most_common(10), "ejemplos_agregados": added.most_common(10),
                                "similitud_secuencia_diagnostica": round(SequenceMatcher(None, *tokens, autojunk=False).ratio(), 4),
                                "glifos_con_caja": len(new["posiciones"]), "advertencia": new["advertencia_localizacion"],
                                "figuras_antes": len(old["figuras"]), "figuras_despues": len(new["figuras"])})
        result[name] = {"sha256": reports["after"]["sha256"], "paginas": reports["after"]["paginas"], "caracteres": {stage: reports[stage]["caracteres"] for stage in books},
                        "conteos_consultas": {stage: dict(counts) for stage, counts in totals.items()}, "consultas": probes, "diagnostico_textual": diagnostics}
        print(name, result[name]["caracteres"], result[name]["conteos_consultas"], "missing tokens", sum(d["tokens_ausentes"] for d in diagnostics), "added", sum(d["tokens_agregados"] for d in diagnostics))
    dest = ROOT / "_media/phase2-evidence/comparison-final.json"
    if dest.exists():
        raise SystemExit("No se sobrescribe la comparación existente")
    dest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(dest)


if __name__ == "__main__":
    main()
