# Despliegue en producción

Guía paso a paso del stack decidido: **PWA en Vercel Hobby**, **API + cola + worker
en Render (free, Docker)**, **MongoDB Atlas (free)**, **Cloudflare R2** y
**Mistral OCR**. Las variables de la API están definidas en `app/config.py`; las de
la PWA en `auth.ts`, `lib/api.ts` y `lib/server/api.ts` del repo
`biblioteca-eclesiastica-web`.

Toda cifra de límites, precios o cuotas de un tercero aparece como
**verificar en el panel del proveedor**: cambian y no se copian aquí.

## Orden recomendado

1. MongoDB Atlas → 2. Cloudflare R2 → 3. Secretos compartidos → 4. Render (API)
→ 5. Vercel (PWA) → 6. Google OAuth → 7. CORS final → 8. Mistral → 9. Admin y smoke.

Hay dependencias circulares benignas (la API necesita el origen de Vercel para
CORS; Vercel necesita la URL de Render). Se resuelven desplegando Render primero con
un `CORS_ORIGINS` provisional y corrigiéndolo en el paso 7.

## 1. MongoDB Atlas

1. Crear cuenta y un proyecto; **Create cluster** con el plan gratuito (M0).
   Elegir la región más cercana a la de Render. Límites de almacenamiento y
   conexiones: **verificar en el panel del proveedor**.
2. **Database Access** → usuario con contraseña y rol `readWrite` sobre la base
   `biblioteca` (evitar `atlasAdmin`).
3. **Network Access** → Render free no tiene IP de salida fija: permitir
   `0.0.0.0/0` y compensar con una contraseña larga y el usuario acotado. Si se
   pasa a un plan de Render con IPs fijas, restringir a esas IPs.
4. **Connect → Drivers** → copiar la cadena `mongodb+srv://usuario:clave@cluster.../`.
   Es el valor de `MONGODB_URI` (secreto). `MONGODB_DB=biblioteca`.
5. **Índices**: la API llama a `ensure_indexes()` al arrancar (incluye el índice
   `$text`, el único parcial de `trabajos.sha256` y los TTL). Opcional, para
   crearlos antes del primer arranque desde tu máquina:

   ```powershell
   $env:MONGODB_URI = '<cadena de Atlas>'
   uv run python scripts/create_search_index.py
   ```

   Si Mongo no responde al arrancar la API solo registra una advertencia y
   continúa; revisar los logs de Render tras el primer despliegue.

## 2. Cloudflare R2

1. **R2 → Create bucket** (p. ej. `biblioteca`). Las condiciones del plan gratuito
   y de salida de datos: **verificar en el panel del proveedor**.
2. **R2 → Manage API tokens → Create API token**: permiso *Object Read & Write*,
   **limitado a este bucket**. Guardar `Access Key ID` y `Secret Access Key`
   (se muestran una sola vez) → `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`.
3. Endpoint S3: `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` →
   `S3_ENDPOINT_URL`. `S3_BUCKET=biblioteca`. `S3_REGION` se queda en `auto`.
4. **Cómo se sirven las imágenes** (elegir una; es lo que decide `S3_PUBLIC_BASE_URL`):

   | Opción | Configuración | Compromisos |
   |---|---|---|
   | URL pública | Bucket → Settings → *Public access* (dominio `r2.dev`) o dominio propio; `S3_PUBLIC_BASE_URL=https://pub-xxxx.r2.dev` (sin barra final) | Simple y cacheable. `r2.dev` es para uso de desarrollo/bajo tráfico (verificar condiciones en el panel); un dominio propio permite caché de Cloudflare. Los objetos son públicos por URL. |
   | GET firmado | Dejar `S3_PUBLIC_BASE_URL` vacío | Bucket privado; la API firma cada URL con vigencia de 1 h. No persistir URLs: se piden de nuevo a la API. Las URLs cambian en cada respuesta, lo que reduce el valor de la caché del navegador. |

5. **CORS del bucket** (R2 → bucket → Settings → CORS Policy). Imprescindible para
   la subida directa desde el navegador (`PUT`) y para mostrar imágenes (`GET`).
   Sustituir el origen de Vercel por el real:

   ```json
   [
     {
       "AllowedOrigins": [
         "http://localhost:3010",
         "https://<tu-app>.vercel.app"
       ],
       "AllowedMethods": ["PUT", "GET", "HEAD"],
       "AllowedHeaders": ["content-type"],
       "MaxAgeSeconds": 3600
     }
   ]
   ```

   Sin esta política el navegador bloquea el `PUT` y la subida falla aunque la
   API esté bien. Si se usa un dominio propio para la PWA, añadirlo.

## 3. Secretos compartidos

Generar dos valores aleatorios (por ejemplo `npx auth secret` o
`python -c "import secrets;print(secrets.token_urlsafe(48))"`):

- **Secreto del token API**: va en la API como `AUTH_SECRET` y en la PWA como
  `API_AUTH_SECRET`. **Deben ser idénticos**: la PWA firma un JWT HS256 de 5 min
  por llamada y la API lo verifica (`iss=biblioteca-web`, `aud=biblioteca-api`).
- **Secreto de sesión de Auth.js**: va en la PWA como `AUTH_SECRET` (distinto del
  anterior; mismo nombre pero otro servicio).

Ojo con el nombre: `AUTH_SECRET` en Render ≠ `AUTH_SECRET` en Vercel.

## 4. Render (API + cola + worker)

1. Subir el repo a GitHub (decisión del usuario; esta guía no empuja nada).
2. Render → **New → Blueprint** → elegir el repo. Render lee `render.yaml`
   (servicio `biblioteca-api`, runtime Docker, plan `free`,
   `healthCheckPath: /health`) y pide los valores de las variables
   `sync: false`.
3. Variables (las marcadas **secreto** no se comparten ni se commitean):

   | Variable | Valor | Secreto |
   |---|---|---|
   | `MONGODB_URI` | cadena de Atlas | sí |
   | `MONGODB_DB` | `biblioteca` (ya en `render.yaml`) | no |
   | `S3_ENDPOINT_URL` | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` | no |
   | `S3_BUCKET` | nombre del bucket | no |
   | `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | token de R2 | sí |
   | `S3_PUBLIC_BASE_URL` | URL pública del bucket, o vacío para URLs firmadas | no |
   | `AUTH_SECRET` | secreto del token API (paso 3) | sí |
   | `ADMIN_EMAILS` | tu email de Google (coma para varios) | no |
   | `CORS_ORIGINS` | `https://<tu-app>.vercel.app` (más `http://localhost:3010` si hace falta) | no |
   | `MISTRAL_API_KEY` | clave de Mistral (paso 8); sin ella el OCR no funciona | sí |
   | `MISTRAL_OCR_MODEL` | `mistral-ocr-latest` (ya en `render.yaml`) | no |
   | `TRUST_PROXY_HEADERS` | `true` (ya en `render.yaml`): Render proxea y la IP real viene en `X-Forwarded-For`; sin esto el rate limit ve una sola IP | no |
   | `INGEST_ALLOWED_ROOTS` | vacío (ya en `render.yaml`): `POST /ingest` queda deshabilitado; se usan las subidas firmadas | no |
   | `API_KEY` | opcional, solo scripts de operación (`X-API-Key` equivale a admin). Si se define, tratarlo como secreto | sí |
   | `WORKER_ENABLED` | `true` por defecto: el worker corre dentro del proceso web. Dejarlo así (Render free no tiene workers) | no |

   Valores opcionales que ya tienen default razonable: `MAX_FILE_BYTES` (50 MiB),
   `MAX_UPLOAD_BYTES` (100 MiB), `RATE_LIMIT_SEARCH_PER_MIN` (120),
   `RATE_LIMIT_WRITE_PER_MIN` (20), `PAGE_IMAGE_DPI` (150), `TEXT_CLEANUP`,
   `SCAN_PREPROCESS`. Sin `AUTH_SECRET` ni `API_KEY` las escrituras quedan
   **abiertas**: nunca desplegar así.
4. Esperar el build (instala Java para opendataloader; puede tardar) y comprobar
   `https://<servicio>.onrender.com/health` → `{"status":"ok"}`.
5. Anotar la URL pública de la API: es `API_BASE_URL` / `NEXT_PUBLIC_API_BASE_URL`
   en Vercel.

### Límites del plan gratuito de Render

Cifras exactas: **verificar en el panel del proveedor**. Lo que la arquitectura
asume (ver `ARCHITECTURE.md`): 512 MB de RAM, CPU compartida muy reducida, disco
efímero, sin workers separados, y suspensión tras ~15 min sin tráfico HTTP.

- **Suspensión**: la primera petición tras dormir tarda en responder (arranque en
  frío). Un trabajo en curso se detiene al dormir; al despertar, su lease
  (5 min) ya venció y se reintenta con el siguiente claim (cada reinicio consume
  un intento, máximo 5).
- **Mantener despierta (opcional)**: un ping externo a `/health` cada ~10 min
  (cron-job.org, UptimeRobot o un workflow programado de GitHub Actions). Revisar
  las horas gratuitas mensuales de instancia en el panel: un servicio siempre
  despierto debe caber en ellas. Solo es necesario si se quiere que la cola avance
  sin que nadie visite el sitio.
- **Memoria**: opendataloader arranca una JVM; en 512 MB un PDF grande puede
  agotar memoria. El PDF se procesa por páginas con checkpoints, pero no existe un
  flag para desactivar opendataloader: si hay reinicios por OOM en los logs,
  subir de plan o limitar el tamaño de los archivos (`MAX_FILE_BYTES`).
- **Camino de mejora**: plan de pago de Render (sin suspensión, más RAM/CPU, IPs
  de salida fijas para restringir Atlas), y/o separar el worker en un servicio
  propio (`WORKER_ENABLED=false` en la web, `true` en el worker; el diseño de la
  cola ya admite varias instancias por claim atómico y lease).

## 5. Vercel (PWA)

1. Vercel → **Add New → Project** → importar `biblioteca-eclesiastica-web`.
   Framework: Next.js (autodetectado). Hobby plan: condiciones y límites
   (incluido uso comercial) **verificar en el panel del proveedor**.
2. Variables de entorno (Production, y Preview si se usa):

   | Variable | Valor | Secreto |
   |---|---|---|
   | `NEXT_PUBLIC_API_BASE_URL` | URL de Render, sin barra final. Se incorpora al bundle **en build**: cambiarla exige redeploy | no |
   | `API_BASE_URL` | misma URL (la usan los Server Actions; si falta cae a la pública) | no |
   | `AUTH_SECRET` | secreto de sesión de Auth.js (paso 3) | sí |
   | `AUTH_GOOGLE_ID` | Client ID de Google | no |
   | `AUTH_GOOGLE_SECRET` | Client secret de Google | sí |
   | `API_AUTH_SECRET` | **igual** al `AUTH_SECRET` de Render | sí |

   Sin `AUTH_SECRET`, `AUTH_GOOGLE_ID` y `AUTH_GOOGLE_SECRET` el botón "Ingresar"
   se oculta. `AUTH_TRUST_HOST=true` solo hace falta fuera de Vercel (p. ej.
   `next start` en localhost).
3. Desplegar y anotar el dominio (`https://<tu-app>.vercel.app`).

## 6. Google OAuth

1. Google Cloud Console → proyecto → **APIs & Services → OAuth consent screen**
   (tipo External; en modo *Testing* solo entran los emails agregados como test
   users; publicar la app si deben entrar otros).
2. **Credentials → Create credentials → OAuth client ID → Web application**.
3. **Authorized JavaScript origins**:
   - `http://localhost:3010`
   - `https://<tu-app>.vercel.app`
4. **Authorized redirect URIs**:
   - `http://localhost:3010/api/auth/callback/google`
   - `https://<tu-app>.vercel.app/api/auth/callback/google`
5. Copiar Client ID y secret a Vercel (`AUTH_GOOGLE_ID`, `AUTH_GOOGLE_SECRET`) y
   redeployar. Cuentas de Google con email no verificado se rechazan al entrar.

## 7. CORS final

Con el dominio de Vercel ya conocido:

- Render: `CORS_ORIGINS=https://<tu-app>.vercel.app` (guardar → redeploy).
  Solo "Copiar cita" llama a la API desde el navegador; el resto de la lectura es
  servidor a servidor.
- R2: el JSON del paso 2.5 con el mismo origen.

## 8. Mistral OCR

1. Crear la API key en la consola de Mistral (La Plateforme) y ponerla en Render
   como `MISTRAL_API_KEY`.
2. **Plan gratuito (Experiment)**: puede permitir que Mistral use los datos
   enviados para entrenar. No subir material con derechos o confidencial sin
   revisar los términos del plan en la consola (**verificar en el panel del
   proveedor**).
3. **Límites**: durante la evaluación (`docs/EVALUACION_PIPELINE.md`) cada llamada
   devolvió `429`. Antes de depender del OCR, revisar en la consola el plan, las
   cuotas de la cuenta y los límites de tasa vigentes (**verificar en el panel del
   proveedor**). Los PDF digitales no usan Mistral; solo los escaneados y las
   fotos de páginas.
4. Un fallo transitorio (incl. 429) se reintenta con backoff (30 s · 2^(n-1), tope
   1 h, 5 intentos) y los checkpoints conservan las páginas ya leídas. Si la clave
   falta, el trabajo falla sin reintentos con un mensaje público.

## 9. Administrador inicial y smoke

`ADMIN_EMAILS` crea administradores sin necesidad de fila en Mongo: poner tu email
de Google ahí. Desde `/editor/editores` (solo admin) se dan de alta editores
(colección `editores`). Quien no esté en la lista inicia sesión pero `/editor`
queda denegado.

### Checklist posterior al despliegue

- [ ] `GET https://<api>/health` → `{"status":"ok"}` (la primera vez puede tardar por arranque en frío).
- [ ] `GET https://<api>/api/v1/books` → `200` (lista vacía en una base nueva).
- [ ] `GET https://<api>/api/v1/search?q=prueba` → `200`; confirma el índice `$text`.
- [ ] La PWA carga `/`, `/buscar` y `/biblioteca` sin errores.
- [ ] "Ingresar" con Google funciona y `/editor` abre para tu email.
- [ ] Subir un PDF digital pequeño en `/editor/subir`: la subida directa al bucket
      termina (si el navegador la bloquea, falta el CORS de R2) y
      `/editor/trabajos/<id>` llega a `completado`.
- [ ] El libro aparece en `/biblioteca`; buscar una palabra suya devuelve resultados.
- [ ] El lector muestra la imagen de la página (confirma `S3_PUBLIC_BASE_URL`/URL firmada y CORS `GET`).
- [ ] "Copiar cita" funciona (confirma `CORS_ORIGINS`).
- [ ] Editar metadatos, reprocesar y borrar el libro de prueba desde `/editor/libros`.
- [ ] Un escaneo/foto: confirmar que Mistral responde (si hay `429`, revisar el paso 8).
- [ ] Logs de Render sin reinicios por memoria ni errores de Mongo/S3.

## Problemas frecuentes

| Síntoma | Causa probable |
|---|---|
| `401` en `/yo` o en escrituras desde la PWA | `API_AUTH_SECRET` (Vercel) ≠ `AUTH_SECRET` (Render), o reloj desfasado >30 s |
| El `PUT` de la subida falla en el navegador | Falta CORS en el bucket o falta el origen de Vercel |
| `501` en `POST /uploads` | La API arrancó sin `S3_ENDPOINT_URL`/`S3_BUCKET` (backend local) |
| Imágenes rotas en el lector | Bucket privado con `S3_PUBLIC_BASE_URL` definido, o falta CORS `GET` |
| Trabajo en `fallido` con OCR | `MISTRAL_API_KEY` ausente o `429` repetido; ver paso 8 |
| Trabajo no avanza | Instancia dormida; usar el ping a `/health` o abrir el sitio |
| `429` propio de la API | Rate limit por cliente; sin `TRUST_PROXY_HEADERS=true` todos comparten una IP |
