# Brief de Producto — Biblioteca Virtual Eclesiástica

> Estado: en firme (MVP). Base: análisis de comparables (Sefaria, Shamela, CBETA, CCEL, Logos) + investigación de comportamiento de búsqueda en bibliotecas digitales.

Fuentes originales: [source/README.md](source/README.md).
Insumos de pruebas: `tests/fixtures/`; herramientas API: `tests/tools/`.

## 1. Problema y oportunidad

Un corpus de libros eclesiásticos (meta: 1000 títulos) existe en papel/escaneado y es prácticamente inutilizable para consulta: no se puede buscar dentro, ni saltar a un pasaje, ni citar con precisión.

La oportunidad no es "digitalizar". Cualquiera con un escáner digitaliza. La oportunidad es **convertir el corpus en algo consultable y citable**: que una persona encuentre el pasaje exacto y se lo lleve con su referencia.

## 2. Usuario héroe

**El estudioso / predicador / investigador que busca un pasaje para estudiar, preparar una predicación o citar.**

No es el lector de tapa a tapa. No es el archivero. No es el "administrador de escaneos".

Jobs por orden de frecuencia:
1. "¿Qué dice la biblioteca sobre *X*?" -> encontrar los pasajes relevantes.
2. "Quiero leer este pasaje en contexto" -> leer la página.
3. "Necesito la cita" -> copiar autor + obra + página en un formato usable.

Verbos del producto: **BUSCAR -> LEER -> CITAR**.

## 3. Propuesta de valor (el moat)

El texto es commodity. El valor está en cuatro propiedades que los comparables demuestran:

1. **Dirección canónica** — cada página tiene una referencia estable y citable (libro / capítulo / página).
2. **Relevancia con evidencia** — resultado con el término resaltado y enlace directo a la página, no un "libro encontrado".
3. **Cita verificable** — copiar una cita formateada y poder contrastar el texto contra el escaneo original.
4. **Relaciones** (Fase 2) — comentarios, referencias cruzadas y temas.

## 4. Loop central

`escribir una palabra -> lista de pasajes con cita -> abrir la página -> copiar la cita`

Métrica de éxito del loop: de la consulta a la cita copiada en el menor número de pasos posible.

## 5. MVP (Fase 1)

| # | Feature | Criterio de aceptación |
|---|---|---|
| 1 | Buscar full-text | Devuelve pasajes rankeados con snippet resaltado y ref; respuesta < 300 ms en el set de prueba |
| 2 | Filtros | Por género y autor |
| 3 | Leer página | Deep link por ref; tipografía legible; navegación capítulo anterior/siguiente |
| 4 | Copiar cita | Genera cita en formato estándar (autor, título, capítulo, página) |
| 5 | Pipeline de ingesta | Escanea un directorio, lee `.txt` (UTF-8, orden natural de páginas), calcula conteos, `upsert=True`, y puebla MongoDB Atlas |

Los entregables de la consigna (modelo + Atlas + script de bulk upload) son **el motor del punto 5**, no el producto.

## 6. Fase 2 (diferencial, pospuesto)

- Capa de referencias cruzadas / temas (knowledge graph).
- Verificación texto vs escaneo (procedencia visual).
- Offline real (PWA con cache).
- "Campos de investigación" guardados (subconjuntos de la biblioteca).
- *Linker*: pegar un texto libre y detectar automáticamente las citas.
- Búsqueda en lenguaje natural y sinopsis de resultados con IA.

## 7. No-goals del MVP

- App móvil nativa (se prefiere PWA: alcance, cero instalación, links compartibles).
- Cuentas, roles y permisos complejos.
- Panel de administración vistoso.
- Soporte multi-edición / multi-traducción.

## 8. Métricas

- Latencia de búsqueda (p95) y tiempo a primer resultado.
- Tasa de cero-resultados.
- Relevancia top-3 (evaluación manual sobre un set de consultas).
- Cobertura: % de páginas con texto y con confianza OCR aceptable.

## 9. Arquitectura (3 capas, todo en tiers gratuitos)

| Capa | Tecnología | Servicio gratis |
|---|---|---|
| Cliente | PWA search-first | Vercel / Netlify / Cloudflare Pages |
| API + ingesta | Python (FastAPI + pymongo + `mistralai`) | Render / Fly |
| OCR | Mistral Document AI (`/v1/ocr`, `mistral-ocr-latest`) | Créditos mensuales del plan Free/Education |
| Storage de imágenes | Objetos (escaneos para verificación) | Cloudflare R2 / Backblaze B2 |
| Base de datos | MongoDB Atlas M0 + Atlas Search | Free tier |

Backend en **un solo lenguaje (Python)** para cumplir el requisito de `pymongo` sin fricción.

## 10. Modelo de datos

### 10.1 `books` — documento de archivo/agregado
Plantilla: `modelo_libro.json`. Es la **fuente de verdad** del libro y satisface la consigna (metadatos + `capitulos[]` + `paginas[]` embebidas + campos automáticos `conteo_palabras` por página y `caracteres_totales` por libro).

### 10.2 `pages` — proyección de búsqueda (unidad indexable)
Se deriva de `books`. Es lo que indexa `$text` (sobre `texto_busqueda`, texto plegado sin acentos); permite ranking, snippets y citas sin cargar el libro completo.

```json
{
  "libro_id": "slug-unico-del-libro",
  "ref": "slug-unico-del-libro/pagina/1",
  "numero": 1,
  "capitulo_numero": 1,
  "texto": "Texto completo de la pagina.",
  "conteo_palabras": 0,
  "ocr_confianza": null,
  "imagen_url": null,
  "genero": "teologia",
  "autor_normalizado": "apellido, nombre"
}
```

Notas de diseño:
- Se **desnormalizan** `genero` y `autor_normalizado` en `pages` para poder filtrar/facetar directo en la colección.
- Índice `$text` de MongoDB sobre `texto_busqueda` (no Atlas Search); facetas por `genero` y `autor_normalizado`.
- Se evita el documento-por-libro con texto embebido como *primitive de retrieval* (límite BSON de 16 MB + rendimiento).

### 10.3 `links` / `topics` — Fase 2

## 11. Riesgos y banderas abiertas

- **Licencias y canon**: no todo libro "eclesiástico" es de dominio público o de la misma tradición (católico / protestante / ortodoxo). Definir el alcance del corpus y la política de derechos.
- **Costo de OCR a escala**: la corrida completa de 1000 libros (~150-200k páginas) no entra en tiers gratuitos; el MVP se demuestra sobre un set chico. El pipeline queda 100% funcional igual.
- **Calidad OCR**: en material antiguo/escaneado, el error de OCR es un riesgo de credibilidad. Mitigar con `ocr_confianza` y revisión humana (rol QA & Data).
- **Límite de Atlas M0**: 512 MB duros (incluye índices). Tier de demo; la arquitectura debe poder escalar el storage sin rediseño.
- **Créditos Mistral**: validar en la cuenta que los créditos del plan aplican al endpoint `/v1/ocr`.
