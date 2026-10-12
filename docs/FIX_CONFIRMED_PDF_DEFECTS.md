# Corrección acotada de defectos PDF confirmados

> Nota de ubicación: comandos y resultados conservan sus rutas históricas.
> Equivalentes actuales: API `uv run python -m tests.tools.<nombre>`;
> web `node --test tests/tools/test-reader-image.mjs tests/tools/test-reader-matches.mjs`.
> [Inputs actuales](../tests/fixtures/README.md); evidencia y respaldos sin mover.

11 de octubre de 2026. **Resultado: cinco soportes nativos completos en las
páginas inspeccionadas, un respaldo visual completo explícito y tres defectos
concretos de lectura corregidos. BERT 15 permanece parcial.** No se certifica
exactitud general ni se consideran los respaldos como figuras detectadas.

## Evidencia reproducida y preservada

Evidencia final **E**: `_media/fix-confirmed-pdf-20261011-delivery/` (ignorada).
Baseline **B**: `_media/validation-complex-20261011/`, conservado íntegramente.
Se inspeccionaron visualmente los originales de las siete páginas afectadas,
las láminas de recortes previos y todos los soportes finales listados abajo.

La reproducción local extrae nuevamente la secuencia nativa sin partición y
comprueba igualdad literal con `B/results.json`. Recorta otra vez los candidatos
conservados del conversor sobre los originales, sin volver a ejecutar Java ni
OCR. Luego aplica la partición y el mismo helper de composición usado por el
builder de ingesta. Los SHA-256 de Attention, BERT y ResNet coinciden con B.
Los PDF originales y los datos existentes no se modificaron.

`E/report.json` conserva cajas, componentes, estados, consultas, texto final y
posiciones. En **cada página comparada** se comprueba:

- Retención de todos los caracteres nativos; solamente se agregan separadores.
- Igualdad del multiconjunto `(carácter, caja de glifo)` antes/después: los offsets
  se remapean junto con los glifos, sin interpolar coordenadas ni reextraer texto.
- Conteos independientes de soportes detectados, respaldos y candidatos no
  cubiertos. Los 14/24 componentes de BERT se conservan como `componentes`.

## Antes / después por defecto

Todas las rutas de la última columna son relativas a E. Los `original-N.png`
de cada libro permiten comparar el soporte con la página original completa.

| Defecto | Antes reproducido | Después y estado | Prueba visual final |
|---|---|---|---|
| Attention 4 | Dos imágenes sin encabezados; pie compartido asociado solo a la derecha. | **Resuelto en esta página:** un soporte compuesto por las dos imágenes, sus encabezados nativos y el mismo Figure 2. La asociación requiere el pie compartido y ausencia de prosa intermedia. | `attention-after/figuras/4-0.png` |
| BERT 3 | 14 componentes significativos sin flechas, marcos ni contexto completo. | **Resuelto en esta página:** un soporte basado en el Form nativo, con ambos paneles, flechas, embeddings, entradas, títulos y Figure 1. Los 14 componentes no se clasifican como ruido. | `bert-after/figuras/3-0.png` |
| BERT 15, diagrama | 24 fragmentos significativos; etiquetas y relaciones fuera de los recortes. | **Parcial:** se reemplazan las miniaturas incompletas por un soporte seleccionable de página completa, con los cuatro paneles y Figure 4. `detectada=false`, `precision=pagina`, `estado=pagina_original`; no se afirma segmentación fiable. Los 24 componentes siguen registrados. | `bert-after/figuras/15-0.png` |
| ResNet 2 | Cero candidatos de imagen, pese al bloque residual vectorial. | **Resuelto en esta página:** el Form nativo delimita el bloque completo, incluyendo `identity`, ambas capas, suma, flechas y Figure 2. | `resnet-after/figuras/2-0.png` |
| ResNet 4 | Cero candidatos; comparación de tres redes ausente. | **Resuelto en esta página:** soporte del Form completo con VGG-19, red plana, red residual, shortcuts y Figure 3 completo. | `resnet-after/figuras/4-0.png` |
| ResNet 6, diagrama | Cero candidatos; dos bloques vectoriales ausentes. | **Resuelto en esta página:** ambos bloques, flechas, dimensiones y Figure 5 completo. Se corrigió también la asociación del pie dividido por cambios de fuente en varios objetos nativos. | `resnet-after/figuras/6-0.png` |
| ResNet 3, lectura | La nota 2 interrumpía `in which σ denotes` / `ReLU [29]`. | **Resuelto para la continuación medida:** `after-3.txt`, líneas 38–39, une las columnas sin la nota. Esta se conserva en una sección independiente. La consulta `"denotes ReLU"` es `exacta`, con dos rectángulos reales. | `resnet/reading-3.png` |
| ResNet 6, lectura | Etiquetas y Figure 5 interrumpían `We have shown that` / `parameter-free, identity shortcuts help with training`. | **Resuelto para la continuación medida:** prosa continua; etiquetas y pie pertenecen al segmento visual. La frase entre columnas es `exacta`. Las filas `ResNet-152 21.43 5.71` y `ResNet-152 19.38 4.49` conservan coincidencias exactas. | `resnet/reading-6.png` |
| BERT 15, nota | `predicted the ma-14Note that...` en la línea 95 del baseline. | **Resuelto para esta unión:** el cuerpo termina en `ma-`; las notas 14/15 se conservan por separado. `"Note that"` mantiene geometría exacta. No se completa la palabra que continúa en otra página. | `bert/reading-15.png` |
| BERT 15, búsqueda de etiquetas | Seis etiquetas visibles ausentes del texto nativo. | **Bloqueado para búsqueda sin reconocimiento:** son contornos vectoriales, no texto Unicode recuperable por las fuentes nativas comprobadas. Preservación visual completa y advertencia explícita; no se genera texto. | `bert/path-only-15.png`, `bert/missing-labels.json`, `bert/alternate-text.json` |

Las imágenes `reading-N.png` son **extractos del texto medido y sus segmentos**,
renderizados para comparar lectura; no son capturas de navegación de la PWA.

## Mecanismo comprobado de las etiquetas BERT 15

En una copia cargada solamente en memoria se ocultaron todos los objetos de
texto nativo y se anularon las matrices de las 24 imágenes. Las seis etiquetas
siguen visibles en `path-only-15.png`: clasificación de pares, clasificación
individual, Question Answering Tasks, tagging, SQuAD v1.1 y CoNLL-2003 NER.
No aparecen en el texto de ningún objeto nativo inspeccionado.

El probe de texto alternativo inspeccionó 526 objetos: **sin árbol estructural y
cero registros de marked content**, por lo que no encontró `ActualText` ni texto
alternativo etiquetado. El Form devuelve límites verticales aproximadamente
`-38397..39712`, fuera de la página. Sus puntos de trazado se usan únicamente
para separar texto visual de prosa; no certifican límites de tinta o de recorte.
Por eso la representación sigue siendo la página completa de respaldo.

## Implementación y límites

- `pdf_layout.py` reconoce imágenes/Form nativos; asocia encabezados y pies con
  geometría real. No une paneles independientes por proximidad ni suprime
  candidatos pequeños. Los candidatos fuera de un soporte se conservan.
- La lectura particiona establemente los índices nativos en `prosa`, `visual` y
  `nota`, usando soportes y reglas nativas al pie de la columna. Mantiene el
  orden relativo del cuerpo de PDFium; **no es un algoritmo general de orden de
  lectura**. Numeración, fórmulas, guiones y otros casos no se normalizan.
- `lectura` viaja de forma aditiva por extracción, modelos, documento de página
  y respuesta HTTP. El lector muestra soportes completos en el segmento visual,
  notas por separado y texto nativo del soporte en un desplegable buscable.
  Nunca borra ese texto porque un recorte resulte satisfactorio.
- Los soportes siguen sin certificación semántica universal. Rotación y cajas
  desplazadas conservan las guardas anteriores y el original como respaldo.
- No se refrescaron registros existentes. Las nuevas posiciones/segmentos
  requieren extracción local nueva; los registros anteriores conservan su
  comportamiento compatible. No se prueba aquí routing real, clipboard ni
  otras interacciones pendientes de la PWA.

## Verificaciones y reproducción

Con E inexistente y los directorios padre comprobados:

```powershell
uv run python -m scripts.fix_confirmed_pdf_evidence
uv run python -m scripts.probe_confirmed_pdf
uv run python -m scripts.check_confirmed_pdf
```

Los scripts rechazan sobrescribir E; para repetir se debe elegir otro namespace.
El probe adicional de alternate text se conserva en `E/probe-alternate.py`.

| Verificación final | Resultado y evidencia |
|---|---|
| `uv run pytest --basetemp <E>/pytest-temp` | **102 passed**, cero skipped; `pytest.log`. Siete fixtures deterministas nuevas: paneles/pie, Form vectorial, columnas/nota, recorte fallido, Unicode/remapeo, paneles independientes, builder/pie multifuente. |
| `uv run python -m compileall -q app scripts` | **PASS**; `compileall.log`. |
| `npm run build` | **PASS**, Next 16.4.0/Turbopack; `npm-build.log`. Copia aislada de fuente en `E/web-check`, junction de dependencias, solamente `turbopack.root=C:/code` en la configuración generada para resolverla. |
| `npm run lint` | **PASS** sobre la misma copia; `npm-lint.log`. |
| `node --test scripts/test-reader-image.mjs scripts/test-reader-matches.mjs` | **8 passed** desde el proyecto web; `reader-unit-check.json`; advertencia existente de tipo de módulo, sin fallos. |

Mongo de tests: `mongodb://127.0.0.1:27017`, base
`biblioteca_fix_confirmed_pdf_20261011`, comprobada distinta de la configuración
de aplicación. Los tests y la evidencia corrieron en procesos nuevos, con el
código actual; no se utilizó un servidor antiguo como prueba.

Se identificaron los servidores Next del proyecto en 3010/3011 y API en
8000/8010. No se detuvieron ni se sobrescribió su `.next`; **no sirven todavía
el build aislado de esta corrección**. La activación/reinicio y eventual refresh
guardado de muestras no forman parte de esta evidencia. Un intento aislado
anterior con webpack falló en el parser de URLs de `next/font`; sus logs quedan
en `fix-confirmed-pdf-20261011-release/`. El build final usa el motor normal
Turbopack y pasa; no se modificaron las fuentes ni la configuración productiva.

No hubo despliegue, commits, agentes, lifecycle de revisión ni OCR/Mistral remoto.
Se conservaron los namespaces intermedios y toda la evidencia previa.

**skill_resolution:** ambos AGENTS, `VALIDATION_COMPLEX_PDFS.md` y
`PHASE2_LOCALIZATION.md` leídos primero; skills exactos solicitados `pdf`,
`web-design-guidelines` (incluido `guidelines.md`) y `gitnexus-debugging` leídos
desde sus rutas indicadas. CodeGraph se intentó antes del contexto de fuente;
sin índice disponible, se usaron lecturas dirigidas, sin inicialización ni
registro de skills. Se consultó documentación actual y API instalada de PDFium,
además de la guía local de Next Link.
