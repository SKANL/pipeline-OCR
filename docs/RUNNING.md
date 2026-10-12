# Cómo ejecutar (API + PWA)

Todo lo necesario para levantar el backend y la PWA en local, **desde este
repositorio**.

Puertos canónicos: **una API en 8000 y una PWA en 3010**.
Biblioteca: http://localhost:3010/biblioteca.

## Requisitos

- Python 3.13 + [`uv`](https://docs.astral.sh/uv/)
- Docker (para MongoDB local) — o un MongoDB ya corriendo en `:27017`
- Node.js + npm (para la PWA)
- Java 11+ (opendataloader; opcional: sin Java la ingesta degrada, no rompe)

La PWA vive en el repo **hermano**: `..\biblioteca-eclesiastica-web`
(`C:\code\biblioteca-eclesiastica-web`).

## 1. MongoDB (y S3 local)

```powershell
docker compose up -d   # Mongo :27017, S3 local SeaweedFS :9000 (sin autenticación, cualquier clave), bucket `biblioteca`
docker compose down    # detener (los volúmenes se conservan)
```

Alternativa solo Mongo:

```powershell
docker run -d --name biblio-mongo -p 27017:27017 mongo:8
# si ya existe: docker start biblio-mongo
```

## 2. API

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Ajustar valores sin sobrescribir credenciales existentes.
uv sync
$env:CORS_ORIGINS = 'http://localhost:3010'
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- API: http://localhost:8000 · docs interactivas: http://localhost:8000/docs
- El reset ya está activo; verificar con GET, sin reingesta:

```powershell
Invoke-RestMethod "http://localhost:8000/api/v1/books"
Invoke-RestMethod "http://localhost:8000/api/v1/ref/attention/pagina/4"
```

- Solo para una base de prueba nueva, cargar datos (escribe DB/media):

```powershell
uv run python -m tests.tools.seed_test_data      # solo si faltan fixtures
uv run python scripts/create_search_index.py     # índices (incluye $text)
Invoke-RestMethod -Method Post http://localhost:8000/api/v1/ingest `
  -ContentType "application/json" -Body '{"root":"tests/fixtures/text-books"}'
Invoke-RestMethod "http://localhost:8000/api/v1/search?q=gracia&limit=3"
```

## 3. PWA

```powershell
Set-Location ..\biblioteca-eclesiastica-web
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
$env:NEXT_PUBLIC_API_BASE_URL = 'http://localhost:8000'
npm install
npm run dev -- -p 3010
```

- PWA: http://localhost:3010
- Producción local: definir `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`
  **antes de** `npm run build`, y luego `npx next start -p 3010`.
  Next.js incorpora ese valor al bundle; cambiarlo solo al ejecutar `next start`
  no actualiza un build existente.
- ⚠️ Rebuildear **sin** `next start` corriendo y reiniciar después (si no, quedan
  chunks viejos → la UI se rompe).

## Correr ambos de una (desde acá)

```powershell
pwsh -File scripts/dev.ps1
```

Verifica propietario (command line del proyecto o ancestro) y salud de ambos
listeners antes de arrancar nada. Reutiliza servicios saludables, incluso una
PWA ejecutada con `next start`; solo inicia los puertos ausentes, sin alternativos.
Un propietario ajeno/no verificable o un listener no saludable causa un error;
no detiene procesos. Un mutex evita lanzamientos concurrentes del script.
MongoDB se comprueba solo cuando falta la API.

Para una API nueva, el launcher aplica `CORS_ORIGINS=http://localhost:3010`
como valor predeterminado del proceso (conserva un override explícito heredado).
Para una PWA nueva en desarrollo aplica `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`.
No modifica `.env` ni `.env.local`, y restaura las variables de la consola al salir.
Los listeners reutilizados conservan su configuración actual.

## Estado del reset local (2026-10-11)

Reset completado: **`processed_verified`, 3 libros y 43 páginas**.
Evidencia: `_media/local-reset-20261011-161334/manifest.ejson`.
Consultar la biblioteca en http://localhost:3010/biblioteca; no requiere otro reset
ni reingesta.

Inputs actuales: `tests/fixtures/{real-pdfs,text-books,generated-pdfs}`.
La mudanza conserva bytes/hashes; no altera la DB ni los URLs de media.
`_media/local-reset-20261011-161334/generated` es storage activo; respaldos y
evidencia histórica permanecen intactos. Office original: `docs/source/`.

## Scripts útiles (API)

| Script | Para qué |
|---|---|
| `tests.tools.seed_test_data` | Genera `tests/fixtures/text-books/` solo si faltan. |
| `scripts/create_search_index.py` | Crea los índices de MongoDB. |
| `tests.tools.make_sample_pdf` | Genera `tests/fixtures/generated-pdfs/` solo si faltan. |
| `tests.tools.smoke_upload` | Upload: escribe DB/media, puede invocar OCR. |
| `tests.tools.smoke_local` | Ingesta + búsqueda; escribe DB/media. |
| `tests.tools.medir_cobertura_bbox` | Mide sobre `tests/fixtures/real-pdfs/`; ingesta y escribe DB/media. |

Ejecutar desde raíz API: `uv run python -m tests.tools.<nombre>`.
Índice: [tests/tools/README.md](../tests/tools/README.md).
Validar con `uv run pytest` y `uv run python -m compileall app tests/tools scripts`.
Pytest limpia su DB; sin autorización de borrado usar un Mongo loopback
inaccesible y reportar skips. Web: `npm test`, `npm run lint`,
`npm run typecheck -- --incremental false`. No reconstruir `.next` con producción
activa en 3010; usar una copia aislada si hace falta build.

## Troubleshooting

- **La API no arranca / no encuentra Mongo** → revisar `MONGODB_URI` en `.env` y
  que `biblio-mongo` esté arriba.
- **La PWA muestra "No se pudo conectar"** → la API no está corriendo o
  `NEXT_PUBLIC_API_BASE_URL` está mal.
- **UI rara tras cambios** → reiniciar **ambos** servers (API y PWA); un server
  viejo sirve código viejo.
- **`npm run build` falla** → correrlo con el workdir del repo de la PWA (no desde
  la API).
