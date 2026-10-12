# Arquitectura

Documento técnico del backend/API y su relación con la PWA. Para el encuadre de
producto ver `PRODUCT_BRIEF.md`; para endpoints, `API.md`; para ejecutar,
`RUNNING.md`.

## Vista general

```
PWA (Next.js)  ──HTTP/JSON──►  API FastAPI  ──►  MongoDB (books / pages)
   repo hermano                 pipeline              + archivos en MEDIA_ROOT
   biblioteca-eclesiastica-web  de ingesta/OCR
```

- **API** (`app/`): expone `/api/v1`, corre el pipeline de ingesta y la búsqueda.
- **MongoDB**: store. `books` (documento de archivo del libro) y `pages`
  (proyección indexable, unidad de retrieval).
- **PWA** (repo hermano): consume la API. No comparte código con el backend.

## Pipeline de ingesta (input → output)

```
ENTRADA: un PDF (nombre arbitrario) · un set de imágenes · paginas/*.txt
        │
   (1) CLASIFICAR (pdf-inspector)  → ¿tiene capa de texto?
         ├── digital ─► (2a) TEXTO + GLIFOS (pypdfium2); ayudas visuales (opendataloader)
        └── escaneado ─► (2b) OCR (Mistral)
        │
   (3) NORMALIZAR  orden de páginas · procedencia real (motor, confianza, imagen_url)
                   · texto plegado `texto_busqueda` · conteos
        │
   (4) PERSISTIR   upsert por `libro_id` / `ref`; poda de páginas obsoletas (docs y PNG de página; recortes de figuras y originales no se podan)
               · índices creados al arrancar la API
        │
SALIDA (API): /search · /books · /ref · /cite · /.../imagen
```

Decisiones clave:

- **Fuente alineada (PDF digital)**: `texto` y posiciones de glifos salen de
  una sola pasada nativa de PDFium. Los índices apuntan al texto original,
  sin reordenarlo ni interpolar cajas de runs. OpenDataLoader se ejecuta una
  vez para ayudas visuales y cajas de bloque aproximadas. Sin texto nativo,
  se usan sus bloques o pdf-inspector, indicando el motor real y la limitación.
  `pdf-inspector` sigue siendo el clasificador; sus TextItems no son palabras.
  La localización usa offsets originales y devuelve varias cajas para una frase
  en varias líneas. Véase `PHASE2_LOCALIZATION.md` para evidencia y límites.
- **Degradación elegante en la PWA**: si no hay bloque/imagen, el término igual se
  resalta en el texto de la página. Nunca "no se ve nada".
- **Figuras y fidelidad visual**: se conservan todas las regiones `image`/`figure`
  válidas, incluso pequeñas. No se usa un umbral universal de área ni se elimina
  texto por inclusión geométrica: etiquetas, prosa y pies siguen siendo buscables,
  incluso cuando falla un recorte. Se recorta desde el PNG de página ya renderizado
  y se guarda mediante la misma guarda de rutas que los demás archivos.
  Los recortes son **no verificados**, no una garantía de figura completa.
  El lector abre la página original por defecto para conservar vectores,
  componentes, títulos y disposición; ofrece recortes suplementarios después
  del texto nativo, con dimensiones intrínsecas, pie existente y texto alternativo.
  Los componentes solapados se advierten, sin unir cajas; los paneles separados
  con bordes superiores alineados (hasta 18 pt) se ordenan de izquierda a derecha.
  `orden_fuente` conserva el orden previo cuando se corrige esa disposición.
  Los casos de rotación o crop/media box desplazado conservan la página original
  pero omiten recortes y overlays con advertencia explícita: no se adivina su
  transformación. Ver evidencia y límites en `FIGURE_VISUAL_BEFORE.md`.
- **Búsqueda insensible a acentos**: `texto_busqueda` se guarda plegado
  (`fold_text`) y se indexa con `$text` (`default_language="spanish"`); la query
  también se pliega.
- **Procedencia real** por página: `motor` (`pypdfium2`/`opendataloader`/`pdf-inspector`/`mistral`/`texto`),
  `ocr_confianza` (null cuando no hubo OCR), `imagen_url`, `bloques` (con
  `bbox` e `bbox_norm`).
  `posiciones` almacena arrays compactos `[indice, x, y, ancho, alto]` sobre
  el texto, sin duplicar palabras. La API no devuelve todos los glifos:
  calcula `coincidencias` acotadas para la consulta.

## Modelo de datos

### `books` (documento de archivo)
Compatible con `modelo_libro.json`: `libro_id`, `schema_version`, `metadatos`
(título, autor, género…), `procedencia` (fuente + `ocr`), `origen`, `estado_ingesta`,
`capitulos[]`, `paginas[]` (con `texto`, conteos, `imagen_url`, `bloques`),
`caracteres_totales`, `conteo_paginas`, `conteo_palabras_total`.

### `pages` (proyección indexable)
Un documento por página: `libro_id`, `ref` (`{libro_id}/pagina/{n}`), `numero`,
`capitulo_numero`, `texto`, `texto_busqueda`, conteos, `imagen_url`,
`imagen_ancho`/`imagen_alto`, `bloques` (`bbox`, `bbox_norm`), `figuras`
(`bbox`, `bbox_norm`, `imagen_url`, dimensiones, `tipo`, `orden`, `pie`,
`texto_alternativo`, `estado`, `advertencia`, `orden_fuente`), y campos **desnormalizados** para
filtrar/facetar: `genero`, `autor_normalizado`, `titulo`, `autor`.

Índices (`ensure_indexes`): `$text` sobre `texto_busqueda` (spanish), único sobre
`pages.ref` y `books.libro_id`, índice sobre `pages.libro_id`.

## Módulos

| Módulo | Rol |
|---|---|
| `services/ingest.py` | Pipeline: detecta fuente, arma y persiste. Builders compartidos. |
| `services/extract.py` | Router de extracción (digital/OCR/imágenes) + `extract_local_pdf_texts`. |
| `services/pdf_classify.py` | Clasificación con pdf-inspector. |
| `services/structure.py` | Bloques con bounding box (opendataloader) + `normalize_bbox`. |
| `services/render.py` | Render de página a PNG y tamaño de página (pypdfium2). |
| `services/ocr.py` | Cliente Mistral OCR (imagen / lista / PDF). |
| `services/storage.py` | Almacenamiento por clave (`{libro_id}/{original}`, `{libro_id}/paginas/{n}.png`, `{libro_id}/figuras/{p}-{i}.png`): local bajo `MEDIA_ROOT` o S3-compatible (R2 en prod, SeaweedFS local) si hay `S3_ENDPOINT_URL` + `S3_BUCKET`. Mongo guarda **claves** en `imagen_url`; la URL se arma al responder (`media_url`: `/media/...` local, `S3_PUBLIC_BASE_URL` + clave o GET firmado). Al re-ingestar se poda todo objeto bajo `{libro_id}/` que el libro nuevo no referencia (páginas, recortes, originales). |
| `services/text.py` | `fold_text`, patrón diacrítico-insensible, limpieza de Markdown. |
| `services/naming.py` | `slugify` y orden natural. |
| `services/search.py` | `search_pages` (`$text`), snippet y bloque coincidente. |
| `services/locator.py` | Texto/glifos nativos, Unicode con índices originales, coincidencias literales y precisión explícita. |
| `services/pdf_layout.py` | Layout nativo de PDFium: orden de lectura y composición de ayudas visuales. |
| `services/citation.py` | Citas APA / Chicago / MLA. |
| `services/jobs.py` | Cola Mongo de trabajos de ingesta + worker en proceso. |
| `routers/jobs.py` | Subidas con URL firmada (`/uploads`) y estado (`/trabajos`). |

## Cola de trabajos (`services/jobs.py`)

Render free no tiene workers aparte y duerme tras 15 min sin HTTP entrante, así que la cola vive en
Mongo (`trabajos`) y un **hilo worker por instancia** (arrancado en el `lifespan`, `WORKER_ENABLED`)
la drena:

- **Claim atómico** (`find_one_and_update`): un trabajo `pendiente` con `disponible_desde <= ahora`,
  o uno `procesando` cuyo lease (`bloqueado_hasta`) venció porque la instancia durmió o cayó. Cada
  claim suma un intento.
- **Lease + heartbeat**: lease de 5 min, renovado tras cada página junto con `progreso`. Si otro
  worker tomó el trabajo, el anterior se detiene (`LeaseLost`).
- **Reintentos**: error transitorio → `pendiente` con backoff exponencial + jitter
  (30 s · 2^(n-1) · [1, 2), tope 1 h). `ValueError` (validación, sha256 distinto) y OCR no
  configurado son permanentes. Tras `max_intentos` (5) → `fallido`; también un trabajo que se cae
  en bucle sin intentos restantes.
- **Checkpoints por página** (`trabajo_paginas`): cada página terminada se guarda y un reintento
  salta las ya hechas. Un PDF se corta en PDFs de una página y cada uno pasa por los mismos builders
  (`_extract_pdf_source` / `_extract_image_source`, parámetro `first_page`): memoria acotada a una
  página. Al final se arma el libro, se persiste (`_persist`) y se borran los checkpoints.
- **Idempotencia**: índice único parcial sobre `trabajos.sha256`; las subidas nunca completadas
  caducan a las 24 h (TTL parcial sobre `estado: esperando_subida`).

**Techos**: un worker por instancia y un trabajo a la vez. Si Render duerme a mitad de un trabajo,
este sigue cuando la instancia despierta (próxima petición HTTP) y el lease venció; cada reinicio
consume un intento. Para que la cola avance sin tráfico, un ping externo a `/health` cada ~10 min
(cron-job.org, GitHub Actions) mantiene la instancia despierta (las 750 h/mes gratis alcanzan para
un servicio). Con opendataloader activo, cada página arranca la JVM: lento con 0.1 CPU.

## Seguridad de escritura

- `app/security.py`: `require_editor` acepta token Bearer HS256 de la PWA (Auth.js + Google; ver
  `docs/API.md`) o `X-API-Key`; `require_admin` para `/editores` y `POST /ingest`. Roles desde
  `ADMIN_EMAILS` o la colección `editores`. Los libros y trabajos guardan `creado_por` (email).
- `app/ratelimit.py`: token bucket en memoria por cliente (búsqueda generosa, escrituras estrictas),
  `429` + `Retry-After`. Techo: por instancia.
- `POST /ingest` confinado a `INGEST_ALLOWED_ROOTS` (rutas reales); deshabilitado si no se configura.

## Límites conocidos / escalado

- **MongoDB Atlas M0**: 512 MB duros (incluye índices) → tier de demo, no de
  corpus completo. La arquitectura permite escalar el store sin rediseño.
- **Costo OCR**: la corrida completa del corpus no entra en tiers gratuitos; el
  pipeline es funcional igual sobre un set reducido.
- **Java**: opendataloader requiere Java 11+; si falta, la ingesta degrada (texto
  de respaldo, sin bloques) sin romperse.
- **Arte vectorial/compuesto**: no hay detección robusta de sus límites. BERT tiene
  fragmentos válidos que ni siquiera se solapan; ResNet tiene diagramas visibles
  sin candidatos `image`. La página original es el respaldo explícito, no un
  indicador de ausencia de figuras. Los documentos anteriores requieren nueva
  extracción local para recuperar texto que la heurística previa había omitido.
