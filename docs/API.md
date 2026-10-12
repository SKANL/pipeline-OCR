# API

Base: `/api/v1`. JSON. Todas las respuestas salvo error son objetos JSON.

## Autenticación

- Los endpoints de **escritura** (`POST /ingest`, `POST /ingest/upload`) exigen el
  header `X-API-Key` **solo si** `API_KEY` está configurada en el entorno. Si
  `API_KEY` está vacía, quedan abiertos (modo demo).
- Los endpoints de **lectura** son públicos.

## CORS

`CORS_ORIGINS` (lista separada por comas) define los orígenes permitidos (por
defecto `http://localhost:3000,http://localhost:3010`). Necesario para que la PWA llame a la API.

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | `{ "status": "ok" }`. |
| `POST` | `/ingest` | Ingesta un directorio del servidor. Body `{ "root": "..." }`. Devuelve resumen. |
| `POST` | `/ingest/upload` | Ingesta multipart: `files` (PDF o imágenes), `libro_id?`, `metadatos?` (JSON). |
| `GET` | `/search` | Búsqueda full-text. Params: `q` (oblig.), `genero`, `autor`, `limit` (1–100), `offset`. |
| `GET` | `/facets` | Facetas: `{ "generos": [{ "valor", "count" }], "autores": [...] }`. |
| `GET` | `/books` | Lista de metadatos. Params: `genero`, `autor` (contiene, sin diacríticos), `limit`, `offset`. |
| `GET` | `/books/{libro_id}` | Metadatos + capítulos (sin texto de páginas). |
| `GET` | `/books/{libro_id}/paginas` | Índice de páginas sin texto. Params: `limit`, `offset`. |
| `GET` | `/ref/{libro_id}/pagina/{numero}` | Página con texto, bloques, figuras, imagen y navegación. `q` opcional recalcula las coincidencias (máx. 500 caracteres). |
| `GET` | `/pages/{libro_id}/pagina/{numero}/imagen` | Imagen PNG de la página (404 si no hay). |
| `GET` | `/cite/{libro_id}/pagina/{numero}?estilo=apa` | Cita formateada (`apa`, `chicago`, `mla`). |

## Formas de respuesta (resumen)

- **`/search`** → `{ total, resultados: [ { libro_id, titulo, autor, ref, numero,
  capitulo_numero, snippet, score, imagen_url, bbox, bloque_idx, bbox_norm } ] }`.
  `snippet` es HTML seguro: texto escapado (`html.escape`) y `<mark>` alrededor de los términos; `bloque_idx`/`bbox_norm`
  conservan la localización aproximada anterior. `coincidencias` añade hasta
  8 coincidencias por resultado; el lector recalcula la lista con `/ref?q=`.
- **`/ingest`** → `{ books, pages, books_processed, errors, fuentes }` donde
  `fuentes` es un mapa `{ fuente: n_libros }`. Un libro que falla (p. ej. falta
  `MISTRAL_API_KEY`) no aborta: queda en `errors[]` y la respuesta es `200`.
- **`/ingest/upload`** → `{ libro_id, books, pages, books_processed, errors,
  fuente }` (un solo libro, `fuente` escalar).
- **`/cite`** → `{ cita, ref, estilo }`.

## Errores

### Contrato de localización en `/ref?q=` y `/search`

- `coincidencias`: lista ordenada por offset original. Cada entrada contiene
  `inicio`, `fin`, `rects`, `precision`, `fuente`, `advertencia`.
- `inicio`/`fin`: rango semiabierto en **puntos de código Unicode** de `texto`.
  No son índices UTF-16. La PWA usa `Array.from(texto)` para conservarlos.
- `rects`: lista de `[x, y, ancho, alto]` normalizados, origen superior izquierdo
  de la página renderizada. Las frases entre líneas producen varias cajas;
  no se genera una envolvente gigante ni se subdivide proporcionalmente un run.
- `precision`: `exacta` (geometría completa de glifos nativos), `bloque`
  (región aproximada, con advertencia), `sin_localizar` (sin rectángulos).
  `exacta` describe la geometría de los glifos, no certifica la transcripción
  completa ni el orden lógico de una página compleja.
- Coincidencia literal insensible a mayúsculas, acentos y ligaduras (NFKD),
  con espacios equivalentes entre líneas. Los términos independientes se
  localizan como subcadenas (OR); las comillas dobles delimitan una frase.
  La coincidencia más larga gana en solapamientos. Comillas sin cerrar se
  descartan como delimitadores. No se aplica stemming, negación ni operadores.
  MongoDB conserva su ranking lingüístico `$text`: un resultado puede no tener
  coincidencia literal. Snippet, marcado del lector y cajas comparten esta
  semántica literal; no se presenta el ranking como una localización geométrica.
- Límites: 100 coincidencias por página, 8 por resultado de búsqueda, 64 cajas
  por coincidencia, 32 unidades de consulta y 100.000 caracteres nativos para
  geometría por página. Superar el límite de glifos conserva todo el texto y
  activa advertencia; geometría incompleta degrada a bloque o sin ubicación.
  `coincidencias_truncadas` indica coincidencias adicionales fuera de la lista.
- `q` ausente devuelve la página sin calcular coincidencias. `motor` y
  `advertencia_localizacion` informan procedencia/limitaciones de la página.
  No se exponen todos los glifos. Campos anteriores de bloque/bbox se conservan.
- PWA: `q`, `ver` y `coincidencia` viajan por URL. Navegar a otra página vuelve
  a calcular sus coincidencias; no reutiliza el bloque de una consulta anterior.
  Los controles anterior/siguiente aparecen únicamente cuando hay otra
  coincidencia disponible. Sin imagen, el marcado preciso del texto funciona.

### Contrato de figuras en `/ref`

- `bloques`: `bbox`, `texto`, `bbox_norm`, `tipo` (tipo semántico del conversor),
  `orden` (orden de lectura del árbol, incluidos los pies en listas).
- `imagen_url` (página y figuras) es una URL lista para usar: `/media/...` con
  almacenamiento local, o del bucket S3 (pública o firmada con expiración de 1 h).
  No persistirla: pedirla de nuevo a la API.
- `figuras`: `bbox`, `bbox_norm`, `imagen_url`, `imagen_ancho`, `imagen_alto`,
  `tipo`, `orden`, `orden_fuente`, `pie`, `texto_alternativo`, `estado`, `advertencia`.
  Los campos nuevos tienen valores por defecto para documentos anteriores.
- `estado`: `no_verificado` (recorte guardado, integridad semántica no certificada),
  `fragmento` (solapamiento significativo; cajas conservadas sin unión),
  `pagina_original` (fallo de recorte/guardado o geometría no soportada).
  `imagen_url` puede ser null: el candidato no desaparece por un fallo.
- `pie` copia únicamente un pie existente, inequívoco y cercano bajo el recorte;
  puede ser null. No se inventan descripciones; sin pie el alt describe el recurso
  y remite al original. El pie también se conserva en `texto`/`bloques`.
- Las cajas no finitas, invertidas o vacías se rechazan. Una caja fuera de página
  no se recorta silenciosamente. Rotación y crop/media box desplazado activan
  el respaldo original y deshabilitan overlays; se registran advertencias.
- La página original usa `imagen_url` e `imagen_ancho`/`imagen_alto` de la página,
  y el endpoint `/pages/.../imagen` sigue disponible. No detectar imágenes no
  demuestra que una página carezca de diagramas vectoriales.

La PWA usa `?ver=imagen`/`?ver=texto`; sin `ver` abre el original por defecto.
El estado se conserva en navegación suave, recarga y pasos por páginas sin imagen.
Los recortes se muestran como ayudas después del texto nativo, a tamaño intrínseco adaptable,
con carga, error, reintento y enlace al original.

### Códigos HTTP

- `400`: entrada inválida (p. ej. `metadatos` no es JSON, mezclar PDF e imágenes,
  o `root` de `/ingest` inexistente / no es un directorio).
- `401`: falta/incorrecta `X-API-Key` cuando `API_KEY` está configurada.
- `404`: libro/página/imagen inexistente.
- `413`: subida supera `MAX_UPLOAD_BYTES`.
- `422`: en `/ingest/upload`, la fuente requiere OCR y falta `MISTRAL_API_KEY`;
  o parámetros fuera de rango. (En `/ingest` ese error va en `errors[]` con `200`.)

### Comportamiento de arranque y subida

- Al arrancar, la API llama a `ensure_indexes()` (incluido el índice `$text`);
  si MongoDB no responde se registra una advertencia y el arranque continúa.
- `/ingest/upload` es un endpoint síncrono (`def`): FastAPI lo ejecuta en el
  threadpool y no bloquea el event loop. Límites y validaciones no cambian.

## Ejemplos

```powershell
# Buscar
Invoke-RestMethod "http://localhost:8000/api/v1/search?q=gracia&limit=5"

# Subir un PDF
curl.exe -X POST http://localhost:8000/api/v1/ingest/upload `
  -F "files=@libro.pdf" -F "libro_id=mi-libro" -F 'metadatos={"titulo":"Mi Libro"}'

# Citar
Invoke-RestMethod "http://localhost:8000/api/v1/cite/mi-libro/pagina/1?estilo=apa"
```
