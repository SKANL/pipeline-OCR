# Fase 2: localización nativa y límites verificados

> Nota de ubicación: los comandos de evidencia conservan las rutas usadas en su
> ejecución. Hoy los módulos API son `tests.tools.<nombre>` y los cuatro harnesses
> web están en `tests/tools/` del repo web. Los inputs son `tests/fixtures/` del API.
> Ver [mapeo](../tests/fixtures/README.md) y [herramientas](../tests/tools/README.md).
> La evidencia histórica y sus URLs no se movieron.

**Actualización del 11 de octubre de 2026:** los resultados siguientes son el
snapshot histórico de fase 2. La separación posterior de notas y soportes
visuales, con remapeo de los mismos glifos nativos, se documenta en
`FIX_CONFIRMED_PDF_DEFECTS.md`; no modifica estas mediciones históricas.

La ingesta digital ahora alinea el texto leído/buscado con cajas de glifos de
PDFium. Las cajas de bloque siguen disponibles como aproximación explícita.
La misma consulta se recalcula al abrir o recargar el lector, sin depender
de un índice de bloque guardado en un enlace anterior.

## Comparación sobre los mismos PDF

Snapshots locales completos: `_media/phase2-evidence/before/` y
`_media/phase2-evidence/after-final/`. Son los mismos archivos, verificados por
SHA-256, con 43 páginas en total. No se ejecutó OCR remoto. El snapshot
intermedio `after/` se conserva; `after-final/` añade advertencia explícita para
glifos sin correspondencia Unicode, sin sobrescribir evidencia previa.

Se probaron 12 consultas conocidas (cuatro por PDF), incluyendo títulos,
palabras repetidas, etiquetas de diagramas y una frase entre líneas. Los conteos
son **coincidencias de estas consultas**, no una medida global de exactitud.
Para comparar registros anteriores, se aplicó el localizador conservador a
sus snapshots: cajas repetidas/ambiguas no se asignan al primer bloque.
El comportamiento anterior de mejor bloque por consulta también está archivado
en `before/report.json`; no se confunde con geometría de palabra.

| PDF | Páginas | Antes: exactas / bloque / sin ubicación | Después: exactas / bloque / sin ubicación | Caracteres antes → después |
|---|---:|---:|---:|---:|
| Attention | 15 | 0 / 2 / 11 | 13 / 0 / 0 | 38.778 → 39.588 |
| BERT | 16 | 0 / 2 / 16 | 18 / 0 / 0 | 63.805 → 63.949 |
| ResNet | 12 | 0 / 1 / 24 | 25 / 0 / 0 | 53.770 → 59.330 |
| **Total** | **43** | **0 / 5 / 51** | **56 / 0 / 0** | **156.353 → 162.867** |

`comparison-final.json` contiene consultas, substrings originales y diagnóstico
por página. Los 56 resultados medidos no alcanzaron el límite de respuesta.
La frase `"recurrent or convolutional"` de Attention 1 produce **dos cajas**.
`Pre-training` de BERT 3 conserva tanto la etiqueta del diagrama como las
apariciones en la prosa. ResNet conserva el original con vectores completos.

## Retención y orden: diagnóstico, no prueba de precisión

Se conserva todo el texto devuelto por la fuente nativa, incluidos pies,
etiquetas y material que antes no estaba en los bloques. Un fallo de estructura,
recorte o renderizado no borra ese texto. El lector representa `texto` tal cual;
no vuelve a regenerarlo a partir de los bloques de otra fuente.

El cambio de fuente modifica separación, guiones, fórmulas y orden de notas.
El diagnóstico por multiconjunto de tokens registra 63/355/171 tokens anteriores
no idénticos y 392/713/1.754 tokens agregados para Attention/BERT/ResNet.
Por ejemplo, `multiplicative` puede aparecer como `multi-plicative` y
`convolutional` como `convolu-tional`; los índices matemáticos también difieren.
Estos números y la similitud de secuencia por página **no prueban retención
semántica completa**. Se mantiene el orden nativo de PDFium, sin reordenación
heurística; no se certifica el orden lógico perfecto de columnas, tablas,
fórmulas o etiquetas de figuras. Desde P2 (`services/cleanup.py`) el libro armado
quita cabeceras/pies repetidos y guiones de fin de línea borrando caracteres y
remapeando `posiciones`/`lectura`; ver `docs/EVALUACION_PIPELINE.md`.

## API instalada y decisión técnica

`inspector.json` registra versiones, propiedades reales, contrato de coordenadas
y CropBox/MediaBox/rotación de las 43 páginas.

| PDF | TextItems | Runs con varias palabras |
|---|---:|---:|
| Attention | 1.705 | 641 |
| BERT | 3.225 | 1.455 |
| ResNet | 2.802 | 1.485 |

`pdf-inspector.extract_text_with_positions()` ofrece `x/y/width/height`, pero
TextItem es un **run**, no una palabra. Su marco documentado normaliza texto
dibujado a 90° y no aplica `/Rotate`; no se usa para afirmar cajas exactas.
Por esa razón, la variante mínima usa PDFium como fuente conjunta de texto y
geometría. OpenDataLoader mantiene ayudas visuales/cajas de respaldo.

Se usa `FPDFText_GetUnicode` por índice nativo con `get_charbox`, evitando la
suposición de que `get_text_range()` devuelve un carácter por índice: su API
UCS-2 puede insertar/excluir caracteres. El marcador nativo de guion
discrecional se representa como `-`; glifos sin Unicode quedan como `�`, con
advertencia. NFKD/diacríticos/espacios se pliegan solamente para comparar,
manteniendo un mapa a índices del texto original, incluidos combinatorios.

## Evidencia visual inspeccionada

En `_media/phase2-evidence/after-final/`:

- `attention-1-4-matches.png`: página completa con frase entre líneas, dos cajas.
- `bert-3-2-matches.png` y `bert-3-2-crop.png`: etiqueta y repeticiones reales.
- `bert-1-1-crop.png`: caja de los glifos de BERT, no toda la línea.
- `resnet-1-1-matches.png`: título conocido contra el original completo.
- `resnet-3-3-crop.png`: palabra localizada en la geometría original.
- `attention/paginas/`, `bert/paginas/`, `resnet/paginas/`: originales completos.

Las imágenes anotadas se generan sobre el PNG original renderizado, con
rectángulos nativos; no a partir de texto regenerado de bloques. Los recortes
de figuras permanecen no verificados: los componentes pequeños de BERT pueden
ser fragmentos útiles y ResNet tiene arte vectorial sin candidatos de imagen.
Esta fase **no afirma que todas las ayudas visuales estén corregidas**.

## Guardas y compatibilidad

- Rotación de página y CropBox/MediaBox desplazado: texto/original conservados,
  geometría exacta deshabilitada, advertencia visible. Glifos girados o sin caja
  válida tampoco adquieren geometría inventada.
- Sin geometría completa: una única región de bloque inequívoca se etiqueta
  `bloque`; cajas ambiguas producen `sin_localizar`. Nunca se corta un run
  proporcionalmente ni se añade altura mínima a una caja de glifo.
- NFD, acentos, ligaduras y caracteres fuera del BMP mantienen offsets originales.
  Una búsqueda parcial dentro de una ligadura puede localizar su glifo completo;
  no se inventan subcajas dentro de ese glifo.
- Los registros anteriores conservan texto y campos bbox/bloque. Para obtener
  glifos requieren una extracción digital local nueva. NFKD al indexar beneficia
  las ligaduras de los registros nuevos; índices antiguos no se migran solos.
- Las 43 páginas de fixtures se actualizaron únicamente en MongoDB local,
  reutilizando snapshots medidos y medios en un namespace nuevo. Respaldo:
  `_media/phase2-evidence/db-before.json`; resultado: `db-after.json`.
  No se borraron archivos, documentos ni evidencia anterior.

## Verificación y reproducción

- `uv run pytest`: **95 passed**; incluye 19 regresiones nuevas del localizador.
- `uv run python -m compileall app scripts`: correcto.
- `npm run build` y `npm run lint`: correctos.
- `node --test scripts/test-reader-image.mjs scripts/test-reader-matches.mjs`:
  **8 passed**.
- Fixture de componentes reales sin servidor: **23 comprobaciones** en escritorio
  1280×800 y móvil 390×844. Next Link/navegación se simulan; no equivale a una
  verificación de routing de producción. Resultados:
  `browser-desktop-final.json`, `browser-mobile-final.json`.
- `uv run python -m scripts.verify_phase2_local_api`: contrato HTTP en proceso
  contra MongoDB local, 13/18/25 coincidencias exactas y originales PNG válidos.
  No requiere arrancar ni reiniciar un servidor. Captura de la fixture sintética:
  `reader-multirect-desktop.png` (separada de la evidencia de PDF reales).

Los scripts `phase2_evidence.py`, `phase2_compare.py`,
`phase2_inspector_probe.py` y `refresh_phase2_fixtures.py` se ejecutan como
`uv run python -m scripts.<nombre>`. Rechazan sobrescribir evidencia existente.
El refresh verifica la extracción actual y exige MongoDB loopback antes de
escribir. No se reiniciaron servidores, desplegó, delegó ni crearon commits.

**skill_resolution:** se leyeron ambos AGENTS, los skills solicitados `pdf` y
`web-design-guidelines` (incluido `guidelines.md`), y los contextos aplicables
`graphify`, `work-unit-commits`, `cognitive-doc-design`, `playwright-cli`.
CodeGraph se consultó primero en ambos proyectos; al no existir índice se usó
fuente dirigida, sin inicialización. Se consultaron API instalada de PDFium,
guía local de Next Link y documentación actual de PDFium/Next.
