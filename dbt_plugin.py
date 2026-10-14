"""
Plugin de dbt-duckdb que conecta dbt al lakehouse DuckLake.

dbt abre su propia sesión de DuckDB (en memoria, ver profiles.yml). Este
plugin se ejecuta al abrir esa sesión y "adjunta" el lakehouse con las
MISMAS opciones que usa el pipeline (pipeline/core/lakehouse.py), tomadas
de la configuración central (pipeline/config/settings.py).
"""

from dbt.adapters.duckdb.plugins import BasePlugin

from pipeline.config import settings


def _sql_str(value: object) -> str:
    """Texto entre comillas simples, escapando las comillas internas."""
    return "'" + str(value).replace("'", "''") + "'"


class Plugin(BasePlugin):
    def configure_connection(self, conn):
        for ext in ("ducklake", "sqlite"):
            conn.execute(f"INSTALL {ext}")
            conn.execute(f"LOAD {ext}")
        conn.execute(
            f"ATTACH {_sql_str(f'ducklake:sqlite:{settings.CATALOG_PATH}')} AS {settings.CATALOG_NAME} ("
            f"DATA_PATH {_sql_str(str(settings.LAKE_DATA_PATH) + '/')}, "
            f"DATA_INLINING_ROW_LIMIT {settings.DATA_INLINING_ROW_LIMIT})"
        )
