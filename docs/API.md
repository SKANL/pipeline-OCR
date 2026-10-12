# API

Base: `/api/v1`. JSON. Todas las respuestas salvo error son objetos JSON.

## Autenticación

- Los endpoints de **lectura** son públicos.
- Las **escrituras** aceptan una de dos credenciales:
  - `Authorization: Bearer <jwt>` de un editor, emitido por el **servidor** de la PWA (nunca el
    navegador): HS256 con `AUTH_SECRET`; claims `sub` = `email` (email de Google), `iat`, `exp`
    (vigencia ≤ 10 min), `iss` = `"biblioteca-web"`, `aud` = `"biblioteca-api"`. Tolerancia de reloj 30 s.
  - `X-API-Key` = `API_KEY` (scripts de operación; equivale a admin).
- Roles: `ADMIN_EMAILS` (admins sin fila) o la colección `editores` `{email, rol: editor|admin, creado}`.
  Emails sin distinguir mayúsculas.
- `POST /ingest` (rutas del servidor) es solo para **admin u ops**, y además exige que la ruta real
  (symlinks resueltos) quede dentro de `INGEST_ALLOWED_ROOTS`; sin raíces configuradas responde 403.
- Sin `API_KEY` ni `AUTH_SECRET` las escrituras quedan abiertas (modo dev; aviso al arrancar).

Errores: `401` sin credencial o token inválido/vencido · `403` cuenta sin rol suficiente o ruta no
permitida · `429` límite de solicitudes superado (header `Retry-After` en segundos).

## Límites de solicitudes

Token bucket en memoria por cliente (email del token; si no, IP). `GET /search`:
`RATE_LIMIT_SEARCH_PER_MIN` (120). Escrituras: `RATE_LIMIT_WRITE_PER_MIN` (20). `X-Forwarded-For`
solo cuenta con `TRUST_PROXY_HEADERS=true` (activarlo en Render). Por instancia: con varias
instancias, mover a Mongo/Redis.

## CORS

`CORS_ORIGINS` (lista separada por comas) define los orígenes permitidos (por
defecto `http://localhost:3000,http://localhost:3010`). Necesario para que la PWA llame a la API.

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | `{ "status": "ok" }`. |
| `POST` | `/ingest` | Ingesta un directorio del servidor. Body `{ "root": "..." }`. Devuelve resumen. |
| `POST` | `/ingest/upload` | Ingesta multipart **síncrona** (operación/local): `files` (PDF o imágenes), `libro_id?`, `metadatos?` (JSON). |
| `POST` | `/uploads` | Pide URLs PUT firmadas: `{ archivos: [{ nombre, tipo_contenido, tamano, sha256, titulo? }], metadatos?, ocr_proveedor? }`; PDF/TXT: un trabajo por archivo (`trabajos`). `ocr_proveedor` (`tesseract` \| `mistral` \| `glm`, `422` si no existe) fija el OCR de ese trabajo; omitido usa `OCR_PROVIDER`. |
| `POST` | `/uploads/{id}/completar` | Verifica (HEAD) los objetos subidos y encola el trabajo (`202`). |
| `GET` | `/trabajos/{id}` | Estado público del trabajo: `titulo`, `estado`, `etapa`, `progreso`, `error`, `libro_id` (al completar). |
| `GET` | `/trabajos?limit=20` | Editor: sus trabajos recientes (admin: todos). |
| `GET` | `/yo` | `{ email, rol }` del token Bearer (`rol` null si no es editor); 401 sin token. |
| `GET` | `/editores` | Admin: lista `[{ email, rol, creado }]`. |
| `POST` | `/editores` | Admin: alta/cambio `{ email, rol: "editor"|"admin" }` (`201`). |
| `DELETE` | `/editores/{email}` | Admin: baja (`204`, idempotente). |
| `PATCH` | `/books/{libro_id}` | Editor: edita `metadatos` (`titulo`, `subtitulo`, `autor`, `autor_normalizado`, `editorial`, `anio_publicacion`, `idioma`, `genero`, `tradicion`, `isbn`, `temas`, `descripcion`); campos desconocidos → 422. Actualiza también `pages`. |
| `DELETE` | `/books/{libro_id}` | Editor: borra libro, páginas, trabajos + checkpoints y media `{libro_id}/` (`204`, idempotente). |
| `POST` | `/books/{libro_id}/reprocesar` | Editor: reencola el trabajo desde los originales guardados con los metadatos actuales (`202 { trabajo_id, estado }`). Cuerpo opcional `{ ocr_proveedor }` para reprocesar con otro OCR (`422` si no existe); `409` si hay uno activo o el libro no vino de la cola. |
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
  `fuentes` es un mapa `{ fuente: n_libros }`. Un libro que falla (p. ej. el OCR
  activo no está disponible) no aborta: queda en `errors[]` y la respuesta es `200`.
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
- `422`: en `/ingest/upload`, la fuente requiere OCR y el proveedor activo (`OCR_PROVIDER`) no está disponible (binario o clave ausente);
  o parámetros fuera de rango. (En `/ingest` ese error va en `errors[]` con `200`.)

### Subidas firmadas y trabajos

Flujo de la PWA (requiere backend S3/R2; con almacenamiento local `/uploads` responde `501`).
El bucket debe permitir `PUT` por CORS desde el origen de la PWA.

1. `POST /uploads` `{ archivos: [{ nombre, tipo_contenido, tamano, sha256, titulo? }], metadatos?, ocr_proveedor? }`
   valida tipos (`application/pdf`, `image/jpeg`, `image/png`, `image/webp`, `text/plain`; mezclar
   imágenes con documentos da `422`), `MAX_FILE_BYTES` por archivo y `MAX_UPLOAD_BYTES` en total (`413`).
   - **PDF/TXT**: un trabajo (y un libro) **por archivo**. `titulo` del archivo, o `metadatos.titulo`
     si hay un solo archivo, o el nombre del archivo sin extensión (`_`/`-` → espacios).
   - **Imágenes** (fotos de páginas): un solo trabajo/libro con las páginas **en el orden enviado**;
     título = `metadatos.titulo` o el nombre del primer archivo.
   - `metadatos` (`autor`, `genero`, `anio`) se aplican a todos los libros.

   Respuesta `201` (o `200` si todos los trabajos ya existían):
   ```json
   {
     "id": "…", "titulo": "…", "estado": "esperando_subida", "etapa": "subiendo", "libro_id": "…",
     "existente": false, "expira_en": "…", "archivos": ["…"],
     "trabajos": [
       { "id": "665f…", "titulo": "mi libro uno", "estado": "esperando_subida", "etapa": "subiendo",
         "libro_id": "mi-libro-uno-1a2b3c4d", "existente": false, "expira_en": "2026-10-12T18:15:00+00:00",
         "archivos": [{ "nombre": "mi_libro-uno.pdf", "clave": "mi-libro-uno-1a2b3c4d/000-mi_libro-uno.pdf",
                        "url": "https://…", "metodo": "PUT", "encabezados": { "Content-Type": "application/pdf" } }] },
       { "id": "6660…", "titulo": "Libro Dos", "estado": "completado", "etapa": "disponible",
         "libro_id": "libro-dos-9f8e7d6c", "existente": true, "expira_en": null, "archivos": [] }
     ]
   }
   ```
   Los campos de nivel superior repiten `trabajos[0]` (compatibilidad). El cliente hace `PUT url` con los
   `encabezados` dados (el `Content-Type` va firmado). Las URLs vencen a los 15 min; repetir la llamada
   con los mismos archivos da URLs nuevas para los mismos `id`.
2. `POST /uploads/{id}/completar` (uno por trabajo) comprueba que cada objeto exista con el tamaño
   declarado (`409` si no) y pasa el trabajo a `pendiente`: `202 { trabajo_id, estado }`. Repetirlo es inocuo.
3. `GET /trabajos/{id}` →
   ```json
   { "id": "…", "titulo": "Libro Dos", "estado": "procesando", "etapa": "leyendo_paginas",
     "progreso": { "paginas_hechas": 3, "paginas_total": 40 }, "intentos": 1, "error": null,
     "libro_id": null, "creado_en": "…", "actualizado_en": "…" }
   ```
   `libro_id` solo al completar. Consultar con backoff (p. ej. 2 s → 30 s).
4. `GET /trabajos?limit=20` (editor; `limit` 1–100) → lista con la misma forma que `GET /trabajos/{id}`,
   del más nuevo al más viejo: los trabajos del editor (`creado_por`); un admin ve todos.

Estados: `esperando_subida` → `pendiente` → `procesando` → `completado` | `fallido`. Un fallo
transitorio vuelve a `pendiente` con backoff; `error` es un mensaje público, sin detalles internos.
El id de la subida es el id del trabajo.

**Etapas** (`etapa`, para mostrar al usuario): `subiendo` (archivos aún no recibidos) → `en_espera`
(en cola, también esperando un reintento) → `leyendo_paginas` (ver `progreso`) → `preparando_busqueda`
(guardando e indexando) → `disponible` (con `libro_id`) | `fallido` (con `error`). Los trabajos
anteriores sin `etapa` la derivan de `estado`.

**Idempotencia**: la clave de cada trabajo es el `sha256` de su contenido (un archivo: su sha256; varias
imágenes: sha256 de sus sha256 en el orden enviado). Volver a subir los mismos bytes devuelve ese trabajo
con `existente: true`, su `id` y `libro_id`, sin URLs ni duplicados. Si el trabajo previo quedó
`fallido`, se reabre con URLs nuevas. `libro_id` = `slug(titulo)-{sha256[:8]}`. El worker recalcula el
sha256: si no coincide con el declarado, el trabajo falla sin reintentos.

`/ingest/upload` (multipart) sigue siendo síncrono a propósito: es la vía de scripts de operación y
del backend local; la PWA usa `/uploads`, que no retiene bytes ni la petición en la API.

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
