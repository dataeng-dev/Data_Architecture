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

import io
import zipfile

import duckdb
import pandas as pd

from pipeline.config import settings
from pipeline.core.lakehouse import _sql_str, get_connection

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


def export_gold_to_powerbi() -> pd.DataFrame:
    """Materializa cada tabla de la capa Gold como un único archivo Parquet limpio.

    ¿Por qué no apuntar Power BI directo a `database/lake_data/gold`?
    Porque DuckLake guarda allí múltiples archivos históricos (snapshots) y
    tablas temporales de dbt (`*__dbt_tmp`). Al exportar desde `lake.gold`,
    DuckDB resuelve el catálogo y entrega exactamente la versión vigente de
    cada tabla en un archivo `<tabla>.parquet` listo para Power BI.
    """
    export_dir = settings.POWERBI_EXPORT_PATH
    schema_gold = settings.SCHEMA_GOLD

    with get_connection() as con:
        rows = con.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_catalog = ?
              AND table_schema = ?
            ORDER BY table_name
            """,
            [CAT, schema_gold],
        ).fetchall()

        tables = [r[0] for r in rows if not r[0].endswith("__dbt_tmp")]
        if not tables:
            return pd.DataFrame()

        export_dir.mkdir(parents=True, exist_ok=True)

        # Limpiar archivos .parquet antiguos de tablas que ya no existan
        expected_files = {f"{t}.parquet" for t in tables}
        for existing_file in export_dir.glob("*.parquet"):
            if existing_file.name not in expected_files:
                existing_file.unlink()

        summary: list[dict[str, object]] = []
        for table_name in tables:
            out_file = export_dir / f"{table_name}.parquet"
            con.execute(
                f"COPY (SELECT * FROM {CAT}.{schema_gold}.{table_name}) "
                f"TO {_sql_str(out_file)} (FORMAT PARQUET)"
            )
            row_count = con.execute(
                f"SELECT count(*) FROM {CAT}.{schema_gold}.{table_name}"
            ).fetchone()[0]
            size_kb = round(out_file.stat().st_size / 1024, 2)
            summary.append(
                {
                    "Tabla": table_name,
                    "Filas": row_count,
                    "Tamaño (KB)": size_kb,
                    "Archivo": str(out_file),
                }
            )

        return pd.DataFrame(summary)


def build_powerbi_gold_zip() -> bytes:
    """Empaqueta los archivos `.parquet` de la capa Gold en un ZIP en memoria."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for parquet_file in sorted(settings.POWERBI_EXPORT_PATH.glob("*.parquet")):
            zf.write(parquet_file, arcname=parquet_file.name)
    return buffer.getvalue()


def powerbi_m_script(folder_path: str | None = None) -> str:
    """Genera un script Power Query (M) para cargar las tablas Parquet en Power BI."""
    target_path = folder_path or str(settings.POWERBI_EXPORT_PATH)
    escaped_path = target_path.replace('"', '""')
    return (
        "let\n"
        f'    RutaCarpeta = "{escaped_path}",\n'
        "    Archivos = Folder.Files(RutaCarpeta),\n"
        '    SoloParquet = Table.SelectRows(Archivos, each Text.Lower([Extension]) = ".parquet"),\n'
        "    Tablas = Table.AddColumn(\n"
        "        SoloParquet,\n"
        '        "Datos",\n'
        "        each Parquet.Document(File.Contents([Folder Path] & [Name]))\n"
        "    ),\n"
        "    Resultado = Table.SelectColumns(Tablas, {\"Name\", \"Datos\"})\n"
        "in\n"
        "    Resultado"
    )

