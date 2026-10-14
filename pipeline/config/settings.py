"""
===============================================================================
 CONFIGURACIÓN CENTRAL DEL LAKEHOUSE
===============================================================================

¿Qué es este archivo?
---------------------
Es el "panel de control" del proyecto. Aquí se escriben, en un solo lugar,
todos los valores que el resto del código necesita conocer:

  1. DÓNDE están las cosas (carpetas y archivos).
  2. CÓMO se llama y cómo se configura el lakehouse.
  3. QUÉ archivos CSV se deben cargar y con qué nombre de tabla.

¿Por qué centralizarlo?
-----------------------
Si mañana cambia una carpeta o llega un CSV nuevo, solo se modifica este
archivo; el resto del código no se toca. Es como tener la libreta de
direcciones de la empresa en un único sitio en vez de repartida en notas.

Pequeño glosario
----------------
* Lakehouse: un repositorio de datos que combina lo mejor de un "data lake"
  (archivos baratos y flexibles) y de un "data warehouse" (tablas ordenadas
  que se consultan con SQL).
* DuckLake: la tecnología de lakehouse que usamos. Guarda los DATOS en
  archivos Parquet y la "ficha técnica" de esos datos (METADATOS) en una
  base de datos aparte; en nuestro caso, un archivo SQLite.
* Parquet: formato de archivo para datos en tablas. Está comprimido y
  organizado por columnas, por eso ocupa mucho menos que un CSV y se lee
  más rápido.
* Metadatos: "datos sobre los datos". Por ejemplo, qué tablas existen, qué
  columnas tienen, en qué archivos están y qué versiones hay de cada una.
* Esquema: una "carpeta lógica" dentro de la base de datos para agrupar
  tablas (por ejemplo, todas las tablas de la capa bronce).
"""

# `from __future__ import annotations` es una instrucción técnica de Python
# que permite escribir las "pistas de tipo" (p. ej. `dict[str, object]`)
# de forma moderna. No cambia el comportamiento del programa.
from __future__ import annotations

# `dataclass` sirve para crear "fichas" con campos (como un formulario) sin
# escribir mucho código. `field` permite dar valores por defecto a esos campos.
from dataclasses import dataclass, field

# `Path` representa rutas de carpetas/archivos y funciona igual en Linux,
# Mac y Windows (se encarga de las barras "/" o "\" automáticamente).
from pathlib import Path

# =============================================================================
# 1. RUTAS (¿dónde están las cosas?)
# =============================================================================

# Carpeta raíz del proyecto. Se calcula a partir de la ubicación de ESTE
# archivo: settings.py está en  <raíz>/pipeline/config/settings.py, así que
# subiendo dos niveles (`parents[2]`) llegamos a <raíz>.
# Gracias a esto el proyecto funciona sin importar en qué computador esté.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Carpeta donde están los CSV originales (la "materia prima").
DATA_DIR = PROJECT_ROOT / "data"

# Carpeta donde vive todo lo que administra el lakehouse.
DATABASE_DIR = PROJECT_ROOT / "database"

# Archivo SQLite que funciona como CATÁLOGO de DuckLake: solo guarda
# metadatos (qué tablas hay, sus columnas, sus versiones, etc.).
CATALOG_PATH = DATABASE_DIR / "metadata.sqlite"

# Carpeta donde DuckLake guarda los DATOS reales en archivos Parquet.
# Dentro se organizan así:  lake_data/<esquema>/<tabla>/archivo.parquet
LAKE_DATA_PATH = DATABASE_DIR / "lake_data"

# =============================================================================
# 2. PARÁMETROS DE DUCKLAKE
# =============================================================================

# Nombre con el que nos referimos al lakehouse dentro de las consultas SQL.
# Por ejemplo, una tabla se escribe como:  lake.bronze.product
#                                          ^^^^ ^^^^^^ ^^^^^^^
#                                     catálogo esquema  tabla
CATALOG_NAME = "lake"

# DuckLake tiene una función llamada "data inlining": cuando una tabla es
# muy pequeña, guarda sus filas directamente dentro del catálogo (el SQLite)
# en lugar de crear un archivo Parquet.
# Con el valor 0 la desactivamos: TODOS los datos van a Parquet y el SQLite
# queda exclusivamente con metadatos, tal como se pidió en el diseño.
DATA_INLINING_ROW_LIMIT = 0

# Esquemas de la "arquitectura medallón". Es una forma de organizar los
# datos por niveles de calidad, como si fueran medallas:
#   * bronze (bronce): datos crudos, tal como llegan de la fuente.
#   * silver (plata):  datos limpios, con tipos correctos y sin duplicados.
#   * gold   (oro):    datos listos para el negocio (indicadores, reportes).
#   * audit:           tablas de control para saber qué se cargó y cuándo.
SCHEMA_BRONZE = "bronze"
SCHEMA_SILVER = "silver"
SCHEMA_GOLD = "gold"
SCHEMA_AUDIT = "audit"

# Lista con todos los esquemas que deben existir en el lakehouse.
SCHEMAS = (SCHEMA_BRONZE, SCHEMA_SILVER, SCHEMA_GOLD, SCHEMA_AUDIT)

# Cada vez que el pipeline guarda cambios, DuckLake crea una "versión"
# (llamada snapshot). Este texto queda registrado como el AUTOR de esa versión,
# igual que la firma en un documento.
COMMIT_AUTHOR = "medallion-pipeline"


# =============================================================================
# 3. REGISTRO DE FUENTES (¿qué archivos se cargan?)
# =============================================================================

# `@dataclass(frozen=True)` crea una "ficha" cuyos valores NO se pueden
# modificar después de creada (frozen = congelada). Así evitamos cambios
# accidentales en la configuración mientras el programa se ejecuta.
@dataclass(frozen=True)
class SourceTable:
    """Ficha que describe UN archivo CSV de origen y la tabla que genera.

    Campos:
        file_name:    nombre del archivo dentro de la carpeta `data/`.
        table_name:   nombre que tendrá la tabla en el lakehouse.
        description:  explicación breve, en lenguaje de negocio.
        read_options: ajustes especiales de lectura, solo si un archivo los
                      necesita (por ejemplo, si usa ";" en vez de "," como
                      separador: {"delim": ";"}). Por defecto, ninguno.
    """

    file_name: str
    table_name: str
    description: str = ""
    # `default_factory=dict` significa "si no se indica nada, usar un
    # diccionario vacío". (Se escribe así por una regla técnica de Python.)
    read_options: dict[str, object] = field(default_factory=dict)

    # `@property` permite usar `source.path` como si fuera un campo más,
    # aunque en realidad se calcula en el momento.
    @property
    def path(self) -> Path:
        """Ruta completa al archivo CSV (carpeta data + nombre del archivo)."""
        return DATA_DIR / self.file_name


# Lista de todas las fuentes que alimentan la capa bronce.
# Los datos corresponden al conjunto público "Dunnhumby – The Complete
# Journey": compras de unos 2.500 hogares en una cadena de supermercados.
#
# La carga la hace dbt, así que para agregar un CSV nuevo hay que:
#   1. Declararlo en `models/sources.yml`.
#   2. Crear su modelo en `models/bronze/<tabla>.sql` (copiar uno existente).
#   3. Añadir aquí su línea, para que la app y la bitácora lo tengan en cuenta.
SOURCES: tuple[SourceTable, ...] = (
    SourceTable("campaign_desc.csv", "campaign_desc", "Campañas: tipo y días de inicio/fin"),
    SourceTable("campaign_table.csv", "campaign_table", "Hogares que recibieron cada campaña"),
    SourceTable("causal_data.csv", "causal_data", "Exhibición y publicidad por producto/tienda/semana"),
    SourceTable("coupon.csv", "coupon", "Cupones y productos asociados por campaña"),
    SourceTable("coupon_redempt.csv", "coupon_redempt", "Redenciones de cupones por hogar"),
    SourceTable("hh_demographic.csv", "hh_demographic", "Datos demográficos de los hogares"),
    SourceTable("product.csv", "product", "Catálogo de productos"),
    SourceTable("transaction_data.csv", "transaction_data", "Transacciones de compra"),
)
