"""
===============================================================================
 CONSULTAS AL CATÁLOGO DEL LAKEHOUSE
===============================================================================

Este archivo agrupa las consultas de información (metadatos) del lakehouse,
para que tanto la terminal (main.py) como la app (app.py) usen el mismo
código.

Es como el "mostrador de informes" de la biblioteca: aquí se pregunta qué
tablas existen, qué versiones hay y qué se ha cargado.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from pipeline.config import settings
from pipeline.core.lakehouse import get_connection

CAT = settings.CATALOG_NAME


def list_tables() -> pd.DataFrame:
    """Devuelve la lista de tablas con sus filas, archivos y tamaño.

    Une información de DuckDB (tamaño estimado) con información del
    catálogo de DuckLake (archivos Parquet).
    """
    with get_connection() as con:
        return con.sql(
            f"""
            SELECT t.schema_name AS Esquema,
                   t.table_name AS Tabla,
                   t.estimated_size AS Filas,
                   i.file_count AS "Archivos Parquet",
                   round(i.file_size_bytes / 1024 / 1024, 2) AS "Tamaño (MB)"
            FROM duckdb_tables() t
            LEFT JOIN ducklake_table_info('{CAT}') i ON i.table_name = t.table_name
            WHERE t.database_name = '{CAT}'
            ORDER BY t.schema_name, t.table_name
            """
        ).df()


def list_snapshots(limit: int = 50) -> pd.DataFrame:
    """Devuelve el historial de versiones (snapshots) del lakehouse."""
    with get_connection() as con:
        return con.sql(
            f"""
            SELECT snapshot_id AS Versión,
                   snapshot_time AS Fecha,
                   author AS Autor,
                   commit_message AS Mensaje
            FROM ducklake_snapshots('{CAT}')
            ORDER BY snapshot_id DESC
            LIMIT {limit}
            """
        ).df()


def ingestion_log(limit: int = 100) -> pd.DataFrame:
    """Devuelve la bitácora de ejecuciones de carga."""
    with get_connection() as con:
        try:
            return con.sql(
                f"""
                SELECT batch_id AS Batch,
                       layer AS Capa,
                       table_name AS Tabla,
                       rows_loaded AS Filas,
                       round(duration_sec, 2) AS Segundos,
                       status AS Estado,
                       error_message AS Error,
                       logged_at AS Fecha
                FROM {CAT}.{settings.SCHEMA_AUDIT}.ingestion_log
                ORDER BY logged_at DESC
                LIMIT {limit}
                """
            ).df()
        except duckdb.Error:
            # Si la tabla aún no existe (ej. primera ejecución), devolver vacío
            return pd.DataFrame()


def table_columns(schema: str, table: str) -> pd.DataFrame:
    """Devuelve las columnas y tipos de una tabla específica."""
    with get_connection() as con:
        return con.sql(
            f"""
            SELECT column_name AS Columna,
                   data_type AS Tipo
            FROM information_schema.columns
            WHERE table_catalog = '{CAT}'
              AND table_schema = '{schema}'
              AND table_name = '{table}'
            ORDER BY ordinal_position
            """
        ).df()


def preview_table(schema: str, table: str, version: int | None = None, limit: int = 100) -> pd.DataFrame:
    """Devuelve una muestra de datos de la tabla.

    Si se indica `version`, hace "time travel" y muestra cómo estaba la tabla
    en ese snapshot en particular.
    """
    query = f"SELECT * FROM {CAT}.{schema}.{table}"
    if version is not None:
        query += f" AT (VERSION => {version})"
    query += f" LIMIT {limit}"

    with get_connection() as con:
        return con.sql(query).df()
