"""Modelos Pydantic del dominio.

Los nombres de campos en MongoDB/JSON conservan el español de
`modelo_libro.json`. Los identificadores Python usan inglés.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class OcrInfo(BaseModel):
    """Información del motor de OCR usado para el libro."""

    motor: Optional[str] = None
    modelo: Optional[str] = None
    fecha: Optional[datetime] = None
    confianza_media: Optional[float] = None


class Procedencia(BaseModel):
    """Origen del texto (texto plano, PDF digital/escaneado, imágenes, OCR)."""

    fuente: str = "texto"
    scan_base_url: Optional[str] = None
    ocr: OcrInfo = Field(default_factory=OcrInfo)


class Metadatos(BaseModel):
    """Metadatos bibliográficos del libro."""

    titulo: str
    subtitulo: Optional[str] = None
    autor: Optional[str] = None
    autor_normalizado: Optional[str] = None
    editorial: Optional[str] = None
    anio_publicacion: Optional[int] = None
    idioma: str = "es"
    genero: Optional[str] = None
    tradicion: Optional[str] = None
    isbn: Optional[str] = None
    temas: list[str] = Field(default_factory=list)
    descripcion: Optional[str] = None


class Capitulo(BaseModel):
    """Capítulo con su rango de páginas."""

    numero: int
    titulo: Optional[str] = None
    pagina_inicio: Optional[int] = None
    pagina_fin: Optional[int] = None


class Bloque(BaseModel):
    """Bloque de texto con su ubicación en la página (capa de verificación)."""

    bbox: Optional[list[float]] = None  # PDF points; None for OCR blocks (image-only geometry)
    texto: str
    bbox_norm: Optional[list[float]] = None
    tipo: str = "paragraph"
    orden: Optional[int] = None


class Figura(BaseModel):
    """Figura/imagen de una página; se muestra como recorte, no como texto."""

    bbox: list[float]
    bbox_norm: Optional[list[float]] = None
    imagen_url: Optional[str] = None
    imagen_ancho: Optional[int] = None
    imagen_alto: Optional[int] = None
    tipo: str = "image"
    orden: Optional[int] = None
    pie: Optional[str] = None
    texto_alternativo: Optional[str] = None
    estado: str = "no_verificado"
    orden_fuente: Optional[int] = None
    detectada: Optional[bool] = None
    precision: Optional[str] = None
    componentes: list[list[float]] = Field(default_factory=list)
    advertencia: Optional[str] = None


class Pagina(BaseModel):
    """Página individual con su texto y conteos automáticos."""

    numero: int
    ref: str
    capitulo_numero: Optional[int] = None
    texto: str = ""
    conteo_palabras: int = 0
    conteo_caracteres: int = 0
    ocr_confianza: Optional[float] = None
    imagen_url: Optional[str] = None
    imagen_ancho: Optional[int] = None
    imagen_alto: Optional[int] = None
    motor: Optional[str] = None
    bbox: Optional[list[float]] = None
    bloques: list[Bloque] = Field(default_factory=list)
    figuras: list[Figura] = Field(default_factory=list)
    lectura: list[dict] = Field(default_factory=list)
    posiciones: list[list[float]] = Field(default_factory=list)
    advertencia_localizacion: Optional[str] = None


class TextMatch(BaseModel):
    """Rango [inicio, fin) en puntos de código del texto original, no UTF-16.

    rects: [x, y, ancho, alto] normalizado, origen superior izquierdo.
    exacta certifica cajas de glifos nativos; bloque es solo una aproximación.
    """

    inicio: int
    fin: int
    rects: list[list[float]] = Field(default_factory=list)
    precision: str
    fuente: Optional[str] = None
    advertencia: Optional[str] = None


class Libro(BaseModel):
    """Documento de archivo/agregado almacenado en la colección `books`."""

    libro_id: str
    schema_version: str = "1.0.0"
    metadatos: Metadatos
    procedencia: Procedencia = Field(default_factory=Procedencia)
    origen: list[str] = Field(default_factory=list)
    estado_ingesta: str = "pending"
    capitulos: list[Capitulo] = Field(default_factory=list)
    paginas: list[Pagina] = Field(default_factory=list)
    caracteres_totales: int = 0
    conteo_paginas: int = 0
    conteo_palabras_total: int = 0
    creado_en: Optional[datetime] = None
    actualizado_en: Optional[datetime] = None


class SearchHit(BaseModel):
    """Un resultado de búsqueda con snippet resaltado."""

    libro_id: str
    titulo: Optional[str] = None
    autor: Optional[str] = None
    ref: str
    numero: int
    capitulo_numero: Optional[int] = None
    snippet: str
    score: Optional[float] = None
    imagen_url: Optional[str] = None
    bbox: Optional[list[float]] = None
    bloque_idx: Optional[int] = None
    bbox_norm: Optional[list[float]] = None
    coincidencias: list[TextMatch] = Field(default_factory=list)
    coincidencias_truncadas: bool = False


class SearchResponse(BaseModel):
    """Respuesta paginada de búsqueda."""

    total: int
    resultados: list[SearchHit]


class BookSummary(BaseModel):
    """Resumen de libro para el listado de `books`."""

    libro_id: str
    metadatos: Metadatos
    estado_ingesta: str
    conteo_paginas: int
    conteo_palabras_total: int
    caracteres_totales: int
    actualizado_en: Optional[datetime] = None


class BookListResponse(BaseModel):
    """Respuesta paginada del listado de libros."""

    total: int
    resultados: list[BookSummary]


class PageSummary(BaseModel):
    """Resumen de página para el índice del lector (sin texto)."""

    numero: int
    ref: str
    capitulo_numero: Optional[int] = None
    conteo_palabras: int = 0
    imagen_url: Optional[str] = None


class PageListResponse(BaseModel):
    """Respuesta paginada del índice de páginas de un libro."""

    total: int
    resultados: list[PageSummary]


class FacetValue(BaseModel):
    """Valor de faceta con su conteo de libros."""

    valor: str
    count: int


class FacetsResponse(BaseModel):
    """Facetas disponibles para poblar los filtros de la UI."""

    generos: list[FacetValue] = Field(default_factory=list)
    autores: list[FacetValue] = Field(default_factory=list)


class PageResponse(BaseModel):
    """Página con enlaces de navegación anterior/siguiente."""

    libro_id: str
    ref: str
    numero: int
    capitulo_numero: Optional[int] = None
    texto: str
    conteo_palabras: int
    conteo_caracteres: int
    imagen_url: Optional[str] = None
    imagen_ancho: Optional[int] = None
    imagen_alto: Optional[int] = None
    bloques: list[Bloque] = Field(default_factory=list)
    figuras: list[Figura] = Field(default_factory=list)
    lectura: list[dict] = Field(default_factory=list)
    ref_anterior: Optional[str] = None
    ref_siguiente: Optional[str] = None
    motor: Optional[str] = None
    coincidencias: list[TextMatch] = Field(default_factory=list)
    coincidencias_truncadas: bool = False
    advertencia_localizacion: Optional[str] = None


class CitationResponse(BaseModel):
    """Cita formateada devuelta por el endpoint de citación."""

    cita: str
    ref: str
    estilo: str
