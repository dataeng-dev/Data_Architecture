"""
===============================================================================
 CAPA BRONCE: INGESTA DE DATOS CRUDOS
===============================================================================

¿Qué es la capa bronce?
-----------------------
Es la primera estación del pipeline. Su único trabajo es traer los datos
de origen (los CSV) al lakehouse SIN modificarlos. Es como fotocopiar los
documentos originales antes de empezar a trabajar con ellos: si algo sale
mal en pasos posteriores, siempre podemos volver a la copia fiel.

Reglas de esta capa
-------------------
1. FIDELIDAD AL ORIGEN
   * Todas las columnas se guardan como TEXTO (en SQL: VARCHAR), aunque
     contengan números o fechas. Así no se pierde nada: por ejemplo, un
     código "000123" no se convierte en el número 123.
   * Los nombres de las columnas se conservan tal como vienen en el CSV.
   * Convertir tipos y limpiar es tarea de la capa PLATA.

2. TRAZABILIDAD (poder responder "¿de dónde salió este dato?")
   A cada fila se le agregan tres columnas de auditoría:
     * _batch_id:     identificador de la ejecución que la cargó.
     * _source_file:  archivo CSV de donde vino.
     * _ingested_at:  fecha y hora exacta de la carga.
   Además, cada carga queda anotada en la tabla `audit.ingestion_log` y en
   el historial de versiones de DuckLake, con un mensaje descriptivo.

3. CARGA COMPLETA (full refresh)
   En cada ejecución la tabla se reemplaza por completo con el contenido
   actual del CSV. No se pierde la historia: DuckLake guarda las versiones
   anteriores y se pueden consultar ("viaje en el tiempo" o time travel).

4. TODO O NADA (transacciones)
   Cada tabla se carga dentro de una TRANSACCIÓN: o se guarda completa o no
   se guarda nada. Nunca queda una tabla a medio cargar.
"""

import json
import os
import subprocess
import time

import duckdb

from pipeline.config import settings
from pipeline.core.base import Layer, StepResult
from pipeline.core.lakehouse import set_commit_message
from typing import Callable

CAT = settings.CATALOG_NAME
BRONZE = f"{CAT}.{settings.SCHEMA_BRONZE}"
INGESTION_LOG = f"{CAT}.{settings.SCHEMA_AUDIT}.ingestion_log"


class BronzeLayer(Layer):
    """Capa bronce: ahora gestionada mediante modelos dbt.

    Actúa como un puente que ejecuta `dbt run` y luego registra los
    resultados en la bitácora para mantener la compatibilidad con
    la aplicación web y el CLI.
    """

    name = "bronze"

    def run(
        self,
        con: duckdb.DuckDBPyConnection,
        batch_id: str,
        tables: list[str] | None = None,
        on_start: Callable[[str], None] | None = None,
        on_step: Callable[[StepResult], None] | None = None,
    ) -> list[StepResult]:
        
        self._ensure_ingestion_log(con)
        
        self.log.info("Iniciando capa bronce mediante dbt | batch=%s", batch_id)

        # Construir comando dbt
        cmd = ["uv", "run", "dbt", "run", "--select", "bronze", "--profiles-dir", "."]
        if tables:
            # Filtrar por los modelos específicos
            models_to_run = [f"bronze_{t}" for t in tables]
            # O simplemente el nombre del modelo. Los modelos los nombramos igual que la tabla.
            cmd = ["uv", "run", "dbt", "run", "--select"] + tables + ["--profiles-dir", "."]
            
        # Ejecutar dbt
        self.log.info("Ejecutando: %s", " ".join(cmd))
        
        if on_start:
            on_start("dbt run")
            
        # Añadir PYTHONPATH para que dbt encuentre dbt_plugin.py
        env = os.environ.copy()
        env["PYTHONPATH"] = str(settings.PROJECT_ROOT)
        process = subprocess.run(cmd, capture_output=True, text=True, cwd=settings.PROJECT_ROOT, env=env)
        
        if process.returncode != 0:
            self.log.error("dbt run falló:\n%s", process.stdout)
            
        # Leer resultados
        run_results_path = settings.PROJECT_ROOT / "target" / "run_results.json"
        results = []
        
        if run_results_path.exists():
            with open(run_results_path, encoding="utf-8") as f:
                data = json.load(f)
                
            for result in data.get("results", []):
                # unique_id es del tipo: model.lakehouse_dbt.bronze.product
                model_id = result.get("unique_id", "")
                table_name = model_id.split(".")[-1]
                
                status_dbt = result.get("status")
                seconds = result.get("execution_time", 0.0)
                
                # Intentar obtener filas insertadas si está disponible
                adapter_response = result.get("adapter_response", {})
                rows = adapter_response.get("rows_affected", 0)
                
                error_msg = result.get("message") if status_dbt == "error" else None
                status = "SUCCESS" if status_dbt == "success" else "FAILED"
                
                # Obtener la cuenta de filas consultando directamente la tabla si fue exitoso
                if status == "SUCCESS":
                    try:
                        rows = con.execute(f"SELECT count(*) FROM {BRONZE}.{table_name}").fetchone()[0]
                    except Exception:
                        pass
                
                step_result = StepResult(self.name, table_name, status, rows, seconds, error_msg)
                results.append(step_result)
                
                # Insertar en bitácora
                self._log_ingestion(con, batch_id, table_name, f"{table_name}.csv", rows, seconds, status, error_msg)
                
                if on_step:
                    on_step(step_result)
                    
        return results

    @staticmethod
    def _ensure_ingestion_log(con: duckdb.DuckDBPyConnection) -> None:
        con.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {INGESTION_LOG} (
                batch_id      VARCHAR,
                layer         VARCHAR,
                table_name    VARCHAR,
                source_file   VARCHAR,
                rows_loaded   BIGINT,
                duration_sec  DOUBLE,
                status        VARCHAR,
                error_message VARCHAR,
                logged_at     TIMESTAMP WITH TIME ZONE
            )
            """
        )

    def _log_ingestion(
        self,
        con: duckdb.DuckDBPyConnection,
        batch_id: str,
        table_name: str,
        source_file: str,
        rows: int,
        seconds: float,
        status: str,
        error: str | None,
    ) -> None:
        con.execute(
            f"INSERT INTO {INGESTION_LOG} VALUES (?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)",
            [batch_id, self.name, table_name, source_file,
             rows, round(seconds, 3), status, error],
        )
