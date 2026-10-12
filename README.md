# Biblioteca Virtual Eclesiástica — Pipeline OCR

Backend de la **Biblioteca Virtual Eclesiástica**: convierte un corpus de libros
eclesiásticos escaneados en algo **buscable, legible y citable**. El loop del
producto es **BUSCAR → LEER → CITAR**.

Documentación: `docs/PRODUCT_BRIEF.md`, `docs/ARCHITECTURE.md`, `docs/API.md` y
`docs/RUNNING.md` (cómo ejecutar la API y la PWA).

- **FastAPI** para la API.
- **MongoDB** (`pymongo`) como store: colección `books` (documento de archivo)
  y `pages` (proyección indexable para búsqueda).
- **pdf-inspector** para clasificar PDF (texto vs escaneado).
- **opendataloader-pdf** para ayudas visuales y bloques aproximados con bounding box de PDFs digitales (requiere Java 11+); el texto y las posiciones de glifos salen de PDFium.
- **pypdfium2** para renderizar cada página a imagen (verificación visual).
- **Mistral Document AI** (`mistral-ocr-latest`) para OCR (PDF escaneado / imágenes).
- **uv** para entorno y dependencias.

El pipeline de ingesta acepta tres fuentes por libro: `paginas/*.txt` (legado),
**cualquier `*.pdf`** (clasificado y extraído local u OCR) o **imágenes**
(`*.png/.jpg/.jpeg/.webp`, ordenadas naturalmente y enviadas a OCR). La
procedencia real (`pdf_digital`, `pdf_escaneado`, `imagenes`, `texto`) queda
registrada por libro y por página.

El modelo de datos conserva los nombres de campo en español de
`modelo_libro.json`; los identificadores en Python están en inglés.

## Requisitos

- Python >= 3.13
- [`uv`](https://docs.astral.sh/uv/) (probado con 0.7.10)
- MongoDB local (opcional para los tests; requerido para ingesta/búsqueda real)
- API key de Mistral (opcional, solo si se usa OCR)

## Instalación

```powershell
uv sync
```

Copia el archivo de ejemplo y ajusta los valores:

```powershell
Copy-Item .env.example .env
```

Variables de entorno:

| Variable | Descripción | Default |
|---|---|---|
| `MONGODB_URI` | URI de conexión a MongoDB | `mongodb://localhost:27017` |
| `MONGODB_DB` | Nombre de la base de datos | `biblioteca` |
| `MISTRAL_API_KEY` | API key de Mistral (OCR; requerida para PDF escaneado/imágenes) | _(vacío)_ |
| `MISTRAL_OCR_MODEL` | Modelo de OCR | `mistral-ocr-latest` |
| `MEDIA_ROOT` | Directorio raíz de originales almacenados | `./_media` |
| `MAX_UPLOAD_BYTES` | Límite de tamaño por subida (bytes) | `104857600` |
| `PAGE_IMAGE_DPI` | Resolución del render PDF -> PNG | `150` |
| `API_KEY` | Si no está vacía, `POST /ingest*` exige el header `X-API-Key` | _(vacío)_ |
| `CORS_ORIGINS` | Orígenes permitidos, separados por coma | `http://localhost:3000,http://localhost:3010` |

## Ejecutar la API

```powershell
uv run uvicorn app.main:app --reload
```

- Documentación interactiva: http://localhost:8000/docs
- Salud: http://localhost:8000/health

## Datos de prueba y búsqueda

Los insumos están en `tests/fixtures/`. El reset local ya está activo
(3 libros, 43 páginas); mover fixtures no requiere reingesta. Generar los
3 libros ficticios solo si faltan, en `tests/fixtures/text-books/`:

```powershell
uv run python -m tests.tools.seed_test_data
```

La API también los crea al arrancar (si Mongo no responde, solo avisa). Crea los índices de MongoDB (incluido el índice `$text` de búsqueda):

```powershell
uv run python scripts/create_search_index.py
```

Ingesta el directorio de prueba:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/api/v1/ingest `
  -ContentType "application/json" `
  -Body '{"root": "tests/fixtures/text-books"}'
```

Solo si faltan, generar PDF de ejemplo. El smoke escribe DB/media y puede usar
OCR con una key configurada; no ejecutarlo para verificar la organización:

```powershell
uv run python -m tests.tools.make_sample_pdf
uv run python -m tests.tools.smoke_upload
```

## Tests

Los tests de parseo, citación y utilidades **no requieren MongoDB**. Los tests de
búsqueda se **omiten** automáticamente si MongoDB no está accesible.

```powershell
uv run pytest
```

## Endpoints (`/api/v1`)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/ingest` | Ingesta un directorio (`{ "root": "..." }`) y devuelve resumen. |
| `POST` | `/ingest/upload` | Ingesta multipart: `files` (PDF o imágenes), `libro_id` (opcional), `metadatos` (JSON opcional). |
| `GET` | `/search` | Búsqueda full-text. Params: `q`, `genero`, `autor`, `limit`, `offset`. |
| `GET` | `/facets` | Facetas de filtros: `{ "generos": [{ "valor", "count" }], "autores": [...] }`. |
| `GET` | `/books` | Lista de metadatos. Params: `genero`, `autor` (contiene, sin diacríticos), `limit`, `offset`. |
| `GET` | `/books/{libro_id}` | Metadatos + capítulos (sin texto de páginas). |
| `GET` | `/books/{libro_id}/paginas` | Índice de páginas sin texto. Params: `limit`, `offset`. |
| `GET` | `/ref/{libro_id}/pagina/{numero}` | Página con texto, bloques, figuras, imagen y navegación. `q` opcional recalcula coincidencias. |
| `GET` | `/pages/{libro_id}/pagina/{numero}/imagen` | Imagen PNG de la página (404 si no hay). |
| `GET` | `/cite/{libro_id}/pagina/{numero}?estilo=apa` | Cita formateada (`apa`, `chicago`, `mla`). |
| `GET` | `/media/...` | Archivos estáticos de `MEDIA_ROOT` (imágenes de página y recortes). |
| `GET` | `/health` | `{ "status": "ok" }`. |

## Estructura

```
app/
  main.py            # app FastAPI y routers bajo /api/v1
  config.py          # Settings (pydantic-settings)
  db.py              # cliente Mongo, colecciones, ensure_indexes()
  models.py          # modelos Pydantic (nombres ES de modelo_libro.json)
  security.py        # API key para endpoints de escritura
  routers/           # ingest, upload, search, books, citations
  services/
    ingest.py        # pipeline de ingesta (armado puro + persistencia)
    extract.py       # router de extracción: PDF digital/escaneado o imágenes
    pdf_classify.py  # clasificación con pdf-inspector
    structure.py     # bloques con bounding box (opendataloader)
    locator.py       # texto/glifos nativos (PDFium) y coincidencias literales
    pdf_layout.py    # layout nativo: orden de lectura y ayudas visuales
    render.py        # render de páginas a PNG (pypdfium2)
    ocr.py           # cliente Mistral OCR (imagen / lista / PDF)
    storage.py       # almacenamiento de originales (local, swappable)
    text.py          # fold y limpieza de texto (búsqueda sin acentos)
    naming.py        # slug y orden natural
    search.py        # búsqueda $text + snippets
    citation.py      # citas apa / chicago / mla
scripts/
  dev.ps1
  create_search_index.py
tests/
  tools/              # seed, generación, smoke, medición, evidencia y probes
  fixtures/           # real-pdfs/, text-books/, generated-pdfs/ (locales)
docs/source/          # originales Office sin cambios
```

## Estructura del corpus de entrada

Ubicaciones y comandos: [fixtures](tests/fixtures/README.md),
[tools](tests/tools/README.md), [fuentes originales](docs/source/README.md).
PWA en 3010; harness en `../biblioteca-eclesiastica-web/tests/tools/`.

```
<root>/
  <carpeta-libro>/
    metadatos.json       # metadatos del libro (opcional: libro_id, capitulos)
    paginas/             # fuente de texto legada
      001.txt            # una página por archivo, UTF-8
      002.txt
    <cualquier>.pdf      # fuente PDF (se clasifica: digital vs escaneado)
    imagenes/            # imágenes para OCR (o *.png/.jpg/.jpeg/.webp al mismo nivel)
```

En subida (`/ingest/upload`) la fuente se elige así: si hay un PDF se ingesta
como libro PDF; si solo hay imágenes, como libro de imágenes (orden natural).
