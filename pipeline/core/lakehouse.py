"""
===============================================================================
 CONEXIÓN AL LAKEHOUSE (DuckLake)
===============================================================================

¿Qué hace este archivo?
-----------------------
Se encarga de "abrir la puerta" del lakehouse. Cualquier parte del programa
que necesite leer o escribir datos pide aquí una conexión ya lista.

¿Cómo funciona DuckLake? (explicación sencilla)
-----------------------------------------------
Imagina una biblioteca:

  * Los LIBROS son los datos -> se guardan como archivos Parquet en
    `database/lake_data/`.
  * El FICHERO o catálogo de la biblioteca (qué libros hay, en qué estante
    están, qué ediciones existen) son los metadatos -> se guardan en el
    archivo SQLite `database/metadata.sqlite`.
  * El BIBLIOTECARIO que sabe usar el fichero para encontrar los libros es
    DuckDB, el motor que ejecuta las consultas SQL.

Este archivo "contrata al bibliotecario" (abre DuckDB), le entrega el
fichero (SQLite) y le indica dónde están los estantes (carpeta de Parquet).
"""

from __future__ import annotations

# `duckdb` es la librería del motor de base de datos DuckDB.
import duckdb

# Traemos la configuración central (rutas, nombres, etc.).
from pipeline.config import settings


def _sql_str(value: object) -> str:
    """Convierte un valor en un texto válido para escribir dentro de SQL.

    En SQL los textos van entre comillas simples: 'hola'. Si el texto ya
    contiene una comilla simple (por ejemplo, una carpeta llamada "O'Brien"),
    hay que duplicarla ('O''Brien') para que SQL no se confunda.

    El guion bajo al inicio del nombre (`_sql_str`) es una convención de
    Python para indicar "función de uso interno de este archivo".
    """
    return "'" + str(value).replace("'", "''") + "'"


def get_connection() -> duckdb.DuckDBPyConnection:
    """Abre DuckDB, conecta el lakehouse y lo deja listo para usar.

    Pasos que realiza:
        1. Crea las carpetas `database/` y `database/lake_data/` si no existen.
        2. Abre una sesión de DuckDB en memoria (temporal).
        3. Activa las extensiones necesarias (complementos de DuckDB).
        4. "Adjunta" (ATTACH) el lakehouse: une el catálogo SQLite con la
           carpeta de archivos Parquet bajo el nombre `lake`.
        5. Se asegura de que existan los esquemas bronze/silver/gold/audit.

    Devuelve:
        Una conexión de DuckDB con la que se pueden ejecutar consultas SQL.
    """
    # --- Paso 1: crear carpetas -------------------------------------------
    # `parents=True`  -> crea también las carpetas intermedias si faltan.
    # `exist_ok=True` -> si la carpeta ya existe, no lanza error.
    settings.DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    settings.LAKE_DATA_PATH.mkdir(parents=True, exist_ok=True)

    # --- Paso 2: abrir DuckDB ---------------------------------------------
    # Sin indicar un archivo, DuckDB trabaja "en memoria". No es problema:
    # los datos importantes NO quedan aquí, sino en el lakehouse adjunto.
    con = duckdb.connect()

    # --- Paso 3: activar extensiones --------------------------------------
    # Las extensiones son complementos que amplían lo que DuckDB sabe hacer:
    #   * ducklake: permite trabajar con el formato de lakehouse DuckLake.
    #   * sqlite:   permite leer y escribir archivos SQLite (nuestro catálogo).
    # INSTALL las descarga (solo la primera vez) y LOAD las activa.
    for ext in ("ducklake", "sqlite"):
        con.execute(f"INSTALL {ext}")
        con.execute(f"LOAD {ext}")

    # --- Paso 4: adjuntar el lakehouse ------------------------------------
    # La instrucción final que se envía a DuckDB se ve más o menos así:
    #
    #   ATTACH 'ducklake:sqlite:/.../database/metadata.sqlite' AS lake (
    #       DATA_PATH '/.../database/lake_data/',
    #       DATA_INLINING_ROW_LIMIT 0
    #   )
    #
    # Se lee como: "conecta un lakehouse DuckLake cuyo catálogo es este
    # archivo SQLite, llámalo `lake` y guarda sus datos en esta carpeta".
    # Si el archivo SQLite no existe, DuckLake lo crea automáticamente.
    con.execute(
        f"""
        ATTACH {_sql_str(f"ducklake:sqlite:{settings.CATALOG_PATH}")} AS {settings.CATALOG_NAME} (
            DATA_PATH {_sql_str(str(settings.LAKE_DATA_PATH) + "/")},
            DATA_INLINING_ROW_LIMIT {settings.DATA_INLINING_ROW_LIMIT}
        )
        """
    )

    # `USE lake` lo deja como base de datos por defecto, para no tener que
    # escribir siempre el prefijo `lake.` en las consultas.
    con.execute(f"USE {settings.CATALOG_NAME}")

    # --- Paso 5: asegurar los esquemas ------------------------------------
    ensure_schemas(con)
    return con


def ensure_schemas(con: duckdb.DuckDBPyConnection) -> None:
    """Crea los esquemas (carpetas lógicas) de la arquitectura medallón si faltan.

    Primero pregunta cuáles ya existen y solo crea los que no están.
    Así se puede ejecutar el pipeline muchas veces sin errores.
    """
    # `information_schema.schemata` es una tabla estándar de SQL que lista
    # los esquemas existentes. El signo `?` es un "espacio reservado": DuckDB
    # lo reemplaza de forma segura por el valor de la lista que sigue.
    #
    # La construcción `{ row[0] for row in ... }` arma un CONJUNTO con los
    # nombres encontrados (un conjunto es una lista sin repetidos en la que
    # es muy rápido preguntar "¿está este elemento?").
    existing = {
        row[0]
        for row in con.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE catalog_name = ?",
            [settings.CATALOG_NAME],
        ).fetchall()
    }
    for schema in settings.SCHEMAS:
        if schema not in existing:
            con.execute(f"CREATE SCHEMA {settings.CATALOG_NAME}.{schema}")


def set_commit_message(
    con: duckdb.DuckDBPyConnection, message: str, extra_info: str | None = None
) -> None:
    """Pone una "etiqueta" a la versión (snapshot) que se está guardando.

    Cada vez que se confirman cambios en DuckLake se crea una nueva versión
    del lakehouse, parecido al historial de versiones de un documento en la
    nube. Esta función le agrega a esa versión:
        * un autor (definido en settings.COMMIT_AUTHOR),
        * un mensaje legible (p. ej. "bronze: full refresh product"),
        * información extra opcional (en formato JSON).

    IMPORTANTE: debe llamarse DENTRO de una transacción, es decir, entre
    BEGIN y COMMIT (ver bronze.py), porque etiqueta justamente esos cambios.
    """
    con.execute(
        f"CALL {settings.CATALOG_NAME}.set_commit_message(?, ?, extra_info => ?)",
        [settings.COMMIT_AUTHOR, message, extra_info],
    )
