# Evaluación del pipeline (corpus de prueba)

Mide la calidad del texto que produce la ingesta real (ruta de trabajos: una
página por vez con `jobs._extract_page` → builders de `ingest` →
`_assemble_libro`) y la búsqueda (`search.search_pages` sobre una base
descartable `biblioteca_eval` en Mongo local, que se borra en cada corrida).

```powershell
uv run python -m tests.tools.make_eval_corpus             # 5 sintéticos deterministas
uv run python -m tests.tools.evaluate_corpus --etiqueta base
```

Resultados crudos: `docs/evaluacion/<etiqueta>.json`.

## Corpus

| Ítem | Tipo | Verdad de referencia |
|---|---|---|
| astete-1787 | escaneo 1787 (con capa OCR previa embebida), 20 págs. | Wikisource págs. 5–28 (wikitexto normalizado; CC BY-SA 4.0). `{{CP\|n}}` = número de página impreso |
| molinero-1695 | escaneo 1695 (capa previa), págs. 10–14 | sin GT |
| ordo-1812 | escaneo en latín 1812, págs. 10–14 | sin GT |
| astete-1700-foto | foto de página (JPEG) | transcripción manual de la portada (aprox.). Foto CC BY-SA 4.0, Biblioteca Nacional de España (catalogo.bne.es a4748779) |
| constitucion-1978 | PDF nacido digital (BOE consolidado, 39 págs.; sin derechos de autor, art. 13 LPI) | cabeceras/pies conocidos + consultas |
| sint-guiones | PDF digital: cortes con guion, cabecera, pie y número de página | exacta (generador) |
| sint-dos-columnas | PDF digital a dos columnas | exacta |
| sint-tipografia | ligaduras ﬁ/ﬂ, comillas tipográficas, acentos (fuente Vera embebida) | exacta |
| sint-foto-movil | foto simulada: sesgo 4°, ruido, márgenes, EXIF orientación 6 | geometría exacta; **nunca** se envía a OCR |
| sint-libro | `.txt` con páginas separadas por `\f` | exacta |

El quinto ítem real (PDF digital en español de dominio público) se cubrió con
la Constitución consolidada del BOE (boe.es, SHA-256 `1a6d7ae6…68168b2330`).
Los PDF escaneados se clasifican como imagen, así que la ruta normal es OCR;
`capa` fuerza la ruta digital para medir la capa OCR embebida por separado.

## Métricas

- **CER/WER**: distancia de edición sobre palabras plegadas (sin acentos,
  minúsculas, sin puntuación), sumada por página.
- **Fuga cab./pie**: cabeceras, pies y números de página de referencia que
  aparecen como línea completa en el texto (menor es mejor).
- **Cortes rotos**: palabras partidas a fin de línea que siguen partidas
  (`medita-ción`), o compuestos reales unidos por error.
- **Guiones fin línea /1k**: guiones residuales `x-⏎y` por mil palabras (sin GT).
- **Recall@10 / MRR**: consultas por libro (plegadas; frases entre comillas);
  acierto = la página esperada (o el libro, si no se fija página) en el top 10.
- **Seg. / Seg. ODL**: tiempo total y tiempo dentro de opendataloader (JVM).
- **Geometría** (sint-foto-movil): sesgo residual y orientación de la imagen
  que recibiría el OCR, medidos con un perfil de proyección independiente del
  código evaluado. Con la imagen de costado el sesgo no es significativo.

## Línea base (antes de P2–P4)

| Ítem | Modo | Págs | CER | WER | Fuga cab./pie | Cortes rotos | Guiones fin línea /1k | Recall@10 | MRR | Seg. | Seg. ODL | Sesgo residual ° | Orientación OK |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| astete-1787 | ocr ⚠ Error de OCR (PDF): API error occurred: Status 429. Body: {" | — | — | — | — | — | — | — | — | — | — | — | — |
| astete-1787 | capa | 20 | 0.1105 | 0.2958 | 0/4 | n/a | 0.6 | 0.5 | 0.5 | 46.2 | 40.8 | n/a | n/a |
| molinero-1695 | ocr ⚠ Error de OCR (PDF): API error occurred: Status 429. Body: {" | — | — | — | — | — | — | — | — | — | — | — | — |
| molinero-1695 | capa | 5 | n/a | n/a | n/a | n/a | 0.0 | n/a | n/a | 46.0 | 42.2 | n/a | n/a |
| ordo-1812 | ocr ⚠ Error de OCR (PDF): API error occurred: Status 429. Body: {" | — | — | — | — | — | — | — | — | — | — | — | — |
| ordo-1812 | capa | 5 | n/a | n/a | n/a | n/a | 0.0 | n/a | n/a | 24.5 | 21.3 | n/a | n/a |
| astete-1700-foto | ocr ⚠ Error de OCR (imagen): API error occurred: Status 429. Body: | — | — | — | — | — | — | — | — | — | — | — | — |
| constitucion-1978 | digital | 39 | n/a | n/a | 116/117 | n/a | 0.0 | 1.0 | 1.0 | 112.0 | 96.7 | n/a | n/a |
| sint-guiones | digital | 4 | 0.0594 | 0.0912 | 12/12 | 9/9 | 0.0 | 1.0 | 0.583 | 10.8 | 10.1 | n/a | n/a |
| sint-dos-columnas | digital | 3 | 0.0 | 0.0 | n/a | n/a | 0.0 | 1.0 | 0.75 | 12.7 | 10.5 | n/a | n/a |
| sint-tipografia | digital | 2 | 0.0 | 0.0 | n/a | n/a | 0.0 | 1.0 | 0.833 | 7.6 | 7.4 | n/a | n/a |
| sint-foto-movil | geometria | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0.75 | False |
| sint-libro | digital | 3 | 0.0 | 0.0 | n/a | n/a | 0.0 | 1.0 | 0.5 | 0.0 | 0.0 | n/a | n/a |

### Observaciones

- **OCR no disponible**: Mistral respondió `429 Rate limit exceeded` (código
  1300) en todos los intentos, con reintentos y espera; las filas `ocr` quedan
  sin datos. Cero llamadas exitosas, cero páginas consumidas. La capa OCR
  embebida (`capa`) sí se midió.
- La fuga de cabeceras/pies es casi total en PDF digitales (116/117 en el BOE,
  12/12 en el sintético).
- PDFium ya une la línea tras un guion final, pero conserva el guion
  (`medita-ción`): 9/9 cortes rotos.
- **Costo de opendataloader**: la cola procesa un PDF de una página por vez y
  cada página lanza una JVM: ~1 s por página, 85–90 % del tiempo total.
