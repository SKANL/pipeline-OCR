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


## Después de P2–P4 y del lote de opendataloader

Entre paréntesis, la diferencia con la línea base.

| Ítem | Modo | Págs | CER | WER | Fuga cab./pie | Cortes rotos | Guiones fin línea /1k | Recall@10 | MRR | Seg. | Seg. ODL | Sesgo residual ° | Orientación OK |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| astete-1787 | ocr ⚠ Error de OCR (PDF): API error occurred: Status 429. Body: {" | — | — | — | — | — | — | — | — | — | — | — | — |
| astete-1787 | capa | 20 | 0.1061 (-0.0044) | 0.2563 (-0.0395) | 0/4 | n/a | 0.61 (+0.01) | 0.625 (+0.125) | 0.625 (+0.125) | 42.0 (-4.2) | 38.2 (-2.6) | n/a | n/a |
| molinero-1695 | ocr ⚠ Error de OCR (PDF): API error occurred: Status 429. Body: {" | — | — | — | — | — | — | — | — | — | — | — | — |
| molinero-1695 | capa | 5 | n/a | n/a | n/a | n/a | 0.0 | n/a | n/a | 261.8 (+215.8) | 258.4 (+216.2) | n/a | n/a |
| ordo-1812 | ocr ⚠ Error de OCR (PDF): API error occurred: Status 429. Body: {" | — | — | — | — | — | — | — | — | — | — | — | — |
| ordo-1812 | capa | 5 | n/a | n/a | n/a | n/a | 0.0 | n/a | n/a | 54.0 (+29.5) | 52.8 (+31.5) | n/a | n/a |
| astete-1700-foto | ocr ⚠ Error de OCR (imagen): API error occurred: Status 429. Body: | — | — | — | — | — | — | — | — | — | — | — | — |
| constitucion-1978 | digital | 39 | n/a | n/a | 0/117 (-116) | n/a | 0.0 | 1.0 | 1.0 | 12.9 (-99.1) | 5.1 (-91.6) | n/a | n/a |
| sint-guiones | digital | 4 | 0.0 (-0.0594) | 0.0 (-0.0912) | 0/12 (-12) | 0/9 (-9) | 0.0 | 1.0 | 0.583 | 1.7 (-9.1) | 1.4 (-8.7) | n/a | n/a |
| sint-dos-columnas | digital | 3 | 0.0 | 0.0 | n/a | n/a | 0.0 | 1.0 | 0.75 | 1.9 (-10.8) | 1.5 (-9) | n/a | n/a |
| sint-tipografia | digital | 2 | 0.0 | 0.0 | n/a | n/a | 0.0 | 1.0 | 0.833 | 1.3 (-6.3) | 1.1 (-6.3) | n/a | n/a |
| sint-foto-movil | geometria | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0.0 (-0.75) | True |
| sint-libro | digital | 3 | 0.0 | 0.0 | n/a | n/a | 0.0 | 1.0 | 0.472 (-0.028) | 0.0 | 0.0 | n/a | n/a |

### Lectura honesta

- **P2 (limpieza)**: la fuga de cabeceras/pies baja de 116/117 a 0/117 (BOE) y de 12/12 a 0/12;
  los cortes rotos bajan de 9/9 a 0/9; el CER de sint-guiones pasa de 0,0594 a 0. En la capa de
  astete-1787 el WER baja de 0,296 a 0,256 y el recall sube de 0,5 a 0,625. Hubo una regresión
  intermedia (un compuesto en la misma línea se unía por error en sint-dos-columnas, CER 0,0021);
  se corrigió con una prueba antes de cerrar P2.
- **P3 (preprocesado)**: la foto simulada llega al OCR derecha (antes estaba de costado) y con
  sesgo residual 0°. Cuesta 0,7–0,9 s por foto. **No se midió su efecto en el OCR** (Mistral
  dio 429).
- **P4 (búsqueda)**: neutro en este conjunto de consultas (mismo recall y MRR). Las consultas
  no dependen del título; el peso del título y el orden estable de los empates están cubiertos
  por pruebas (`tests/test_search_relevance.py`). La baja de MRR en sint-libro (0,5 → 0,472)
  viene de empates de puntaje con otros libros del corpus, no de cambios en su texto.
- **opendataloader una vez por PDF original**: una JVM por libro en vez de una por página. En el
  BOE (39 págs.) pasa de 112 s a 12,9 s (ODL de 96,7 s a 5,1 s). En molinero/ordo/astete el
  tiempo **sube**, porque la evaluación procesa solo 5–20 páginas pero opendataloader ahora
  analiza el libro completo (56/126/421 págs.). En un trabajo real se procesan todas las páginas,
  así que pesa el costo por página: ~1 s antes contra ~0,1–0,6 s ahora. El límite es la memoria
  que ocupa el JSON de un libro enorme (anotado como `ponytail:` en `jobs._structure`).
- **OCR**: Mistral siguió respondiendo 429 en ambas corridas; 0 páginas consumidas. Las filas
  `ocr` y la medición de P3 sobre la foto real quedan pendientes. Las respuestas se guardan en
  caché por página, así que repetir la corrida no gasta páginas de nuevo.

## OCR por proveedor: Tesseract (F1, 2026-10-11)

Corrida local dentro de la imagen Docker (`tesseract-ocr` 5 + `spa` + `lat`, `OCR_LANGS=spa+lat`,
PDF rasterizado a 300 DPI), sin llamadas remotas:
`python -m tests.tools.evaluate_corpus --etiqueta tesseract --ocr-proveedor tesseract --solo astete-1787,molinero-1695,ordo-1812,astete-1700-foto`
(JSON en `docs/evaluacion/tesseract.json`). Mistral (plan sin OCR) y GLM (sin clave) no se corrieron.

| Ítem | Modo | Págs | CER | WER | Recall@10 | MRR | Seg. | Seg. ODL |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| astete-1787 | ocr (Tesseract) | 20 | **0.0904** | **0.1902** | 0.625 | 0.562 | 126.0 | 42.5 |
| astete-1787 | capa (texto incrustado) | 20 | 0.1061 | 0.2563 | 0.625 | 0.625 | 75.9 | 68.0 |
| molinero-1695 | ocr (Tesseract) | 5 | n/a | n/a | n/a | n/a | 293.1 | 271.1 |
| ordo-1812 | ocr (Tesseract) | 5 | n/a | n/a | n/a | n/a | 88.6 | 68.5 |
| astete-1700-foto | ocr (Tesseract) | 1 | 0.3502 | 0.6341 | n/a | n/a | 2.4 | 0.0 |

Lectura:

- **astete-1787 contra Wikisource**: Tesseract mejora a la capa de texto incrustada del escaneo
  (CER 0,106 → 0,090; WER 0,256 → 0,190). Mismo recall; el MRR baja (0,625 → 0,562) por un
  acierto que cae del primer puesto.
- **Foto real (astete-1700)**: CER 0,35 / WER 0,63: tipografía antigua (s larga, ligaduras)
  fotografiada; Tesseract no alcanza para esto. Es el caso donde un proveedor remoto (GLM, Mistral)
  debería compararse cuando haya clave.
- **Costo**: ~4,0–4,4 s por página (render 300 DPI + Tesseract), restando el tiempo de ODL,
  en un CPU de escritorio. **Render free (0,1 CPU)**: no medido allí; por escala de CPU esperar
  del orden de decenas de segundos por página (~40 s), aceptable para una cola en segundo plano
  pero no para respuesta inmediata. Memoria de Tesseract por página: no medida (un proceso por
  página, liberado al terminar).

## opendataloader on/off (F2, 2026-10-11)

PDF digital de 3 páginas (`sint-dos-columnas.pdf`), ruta real de trabajo (`jobs._extract_page`
por página, una JVM por PDF original), local:

| `OPENDATALOADER_ENABLED` | Corrida 1 | Corrida 2 | Bloques ODL | Motor del texto |
|---|---:|---:|---:|---|
| `true` | 2,83 s | 1,92 s | 6 | pypdfium2 |
| `false` | 0,44 s | 0,70 s | 0 | pypdfium2 |

Sin opendataloader el texto, las posiciones de glifos y la indexación no cambian (PDFium); se
pierden las cajas aproximadas de ODL y los recortes de figuras que dependen de ellas. En libros
largos el ahorro crece: en esta evaluación ODL pesa 42–297 s por libro escaneado.
