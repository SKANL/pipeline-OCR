# AGENTS.md — Biblioteca Virtual Eclesiástica (API)

Instrucciones para agentes que trabajan en **este** repositorio (backend/API + pipeline de ingesta).

## Qué es

Backend FastAPI + MongoDB que convierte libros (PDF, imágenes o texto) en algo
**buscable, legible y citable**. Loop del producto: **BUSCAR → LEER → CITAR**.

Documentación: producto en `docs/PRODUCT_BRIEF.md`, arquitectura en
`docs/ARCHITECTURE.md`, endpoints en `docs/API.md`, y cómo ejecutar en
`docs/RUNNING.md`.

## Stack

- Python 3.13 + **uv** (entorno y dependencias) + FastAPI + `pymongo`.
- **pdf-inspector**: clasifica el PDF (texto vs escaneado).
- **opendataloader-pdf**: ayudas visuales y bloques aproximados de PDFs digitales (**requiere Java 11+**); texto y glifos vienen de PDFium.
- **pypdfium2**: renderiza cada página a PNG (verificación visual).
- **Mistral Document AI**: OCR de PDF escaneado / imágenes.

## Comandos

```powershell
uv sync                                  # entorno + dependencias
uv run pytest                            # tests (los de Mongo se omiten si no hay Mongo)
uv run python -m compileall app tests/tools scripts  # chequeo de sintaxis
uv run uvicorn app.main:app --reload     # API en http://localhost:8000
```

Operación en `scripts/` (`dev.ps1`, `create_search_index.py`); seed, smoke,
medición y evidencia en `tests/tools/`: `uv run python -m tests.tools.<nombre>`.
Insumos en `tests/fixtures/{real-pdfs,text-books,generated-pdfs}`;
Office original en `docs/source/`. Ver `docs/RUNNING.md` y los README locales.
Puertos canónicos: API 8000, PWA 3010.

## Estructura

- `app/main.py` — app FastAPI y routers bajo `/api/v1`.
- `app/config.py` — `Settings` (pydantic-settings, lee `.env`).
- `app/db.py` — cliente Mongo, colecciones `books`/`pages`, `ensure_indexes()`.
- `app/models.py` — modelos Pydantic.
- `app/security.py` — API key para endpoints de escritura.
- `app/routers/` — `ingest`, `upload`, `search`, `books`, `citations`.
- `app/services/` — `ingest`, `extract`, `pdf_classify`, `structure`, `render`,
  `ocr`, `storage`, `text`, `naming`, `search`, `citation`.

## Convenciones (IMPORTANTE)

- **Nombres de campo en español** (los de `modelo_libro.json`): `libro_id`,
  `paginas`, `conteo_palabras`, `texto_busqueda`, etc. **Identificadores Python
  en inglés.**
- **Búsqueda**: el texto se guarda plegado en `texto_busqueda` (`fold_text`, sin
  acentos) y se indexa con `$text`; la query también se pliega. Buscar sin tildes
  debe funcionar.
- **Fuente alineada**: en PDF digital, `texto` y posiciones de glifos salen de
  PDFium (`services/locator.py`). OpenDataLoader conserva ayudas visuales y
  cajas aproximadas; sin texto nativo se usan sus bloques o pdf-inspector como
  respaldo. Indicar siempre motor y precisión reales; no subdividir runs para
  simular geometría de palabra. Ver `docs/PHASE2_LOCALIZATION.md`.
- **Credenciales**: siempre en `.env` (nunca en el código). `.env` está en
  `.gitignore`.
- Dependencias: siempre con `uv` (no `pip`/`venv` a mano). Se versionan
  `pyproject.toml` y `uv.lock`.

## Reglas de trabajo

- Antes de dar un cambio por hecho: `uv run pytest` y `compileall`.
- **Reiniciar el servidor** tras cambios de código (si no, se sirve código viejo).
- `ingest.py` es el módulo grande: respetar los builders compartidos
  (`_extract_pdf_source`, `_extract_image_source`) para no duplicar.
- No commitear `_media/`, los corpus locales de `tests/fixtures/` ni `.env`.
- `_media/local-reset-20261011-161334/generated` está activo (3 libros, 43 páginas):
  no mover/borrar media, respaldos ni evidencia al organizar fixtures.
- Pytest elimina su DB de test. Sin autorización de operaciones destructivas,
  usar un endpoint MongoDB loopback inaccesible y reportar los skips explícitos.
